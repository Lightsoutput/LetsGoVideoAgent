from __future__ import annotations

import asyncio
import hashlib
import time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from lets_go_video_agent.agents.harness.models import (
    AgentRun,
    AgentStep,
    RunBudget,
    RunStatus,
)
from lets_go_video_agent.agents.harness.tools import ToolRegistry
from lets_go_video_agent.application.ports import ObservabilityRepository
from lets_go_video_agent.domain.common import ModelUsage, utc_now
from lets_go_video_agent.domain.observability import TraceEvent, TraceEventType


class HarnessError(RuntimeError):
    pass


class BudgetExceededError(HarnessError):
    pass


class PolicyDeniedError(HarnessError):
    pass


class ToolExecutionError(HarnessError):
    pass


class BudgetLedger:
    """并发安全的预算账本。

    预算在调用前预留，而不是调用结束后才结算。否则并行的多个模型请求都可能在
    “尚未记账”的窗口内通过检查，最终造成实际费用超标。
    """

    def __init__(self, budget: RunBudget) -> None:
        self.budget = budget
        self.usage = ModelUsage()
        self._started = time.monotonic()
        self._lock = asyncio.Lock()
        self._steps = 0

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)

    async def reserve_step(self) -> int:
        async with self._lock:
            self._check_deadline()
            if self._steps + 1 > self.budget.max_steps:
                raise BudgetExceededError("已达到 Agent 最大步骤数")
            self._steps += 1
            return self._steps

    async def reserve_tool(self) -> None:
        async with self._lock:
            self._check_deadline()
            if self.usage.tool_calls + 1 > self.budget.max_tool_calls:
                raise BudgetExceededError("已达到工具调用预算")
            self.usage.tool_calls += 1

    async def reserve_model(
        self,
        *,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        estimated_cost_usd: Decimal,
    ) -> None:
        async with self._lock:
            self._check_deadline()
            next_calls = self.usage.model_calls + 1
            next_tokens = (
                self.usage.input_tokens
                + self.usage.output_tokens
                + estimated_input_tokens
                + estimated_output_tokens
            )
            next_cost = self.usage.estimated_cost_usd + estimated_cost_usd
            if next_calls > self.budget.max_model_calls:
                raise BudgetExceededError("已达到模型调用预算")
            if next_tokens > self.budget.max_tokens:
                raise BudgetExceededError("已达到 Token 预算")
            if next_cost > self.budget.max_cost_usd:
                raise BudgetExceededError("已达到费用预算")

            self.usage.model_calls = next_calls
            self.usage.input_tokens += estimated_input_tokens
            self.usage.output_tokens += estimated_output_tokens
            self.usage.estimated_cost_usd = next_cost

    def _check_deadline(self) -> None:
        if time.monotonic() - self._started > self.budget.deadline_seconds:
            raise BudgetExceededError("Agent 运行超过时间预算")


class HarnessSession:
    def __init__(
        self,
        *,
        run: AgentRun,
        registry: ToolRegistry,
        allowed_tools: frozenset[str],
        events: ObservabilityRepository | None = None,
    ) -> None:
        self.run = run
        self.registry = registry
        self.allowed_tools = allowed_tools
        self.ledger = BudgetLedger(run.budget)
        self._events = events
        self._trace_sequence = 0
        # QA 的视频检索、当前帧检查与联网补充可以并发，序号分配必须原子化。
        self._event_lock = asyncio.Lock()
        self._tool_call_counts: dict[str, int] = {}

    async def emit(
        self,
        event_type: TraceEventType,
        *,
        name: str,
        status: str | None = None,
        summary: str = "",
        attributes: dict[str, object] | None = None,
    ) -> None:
        """写入可公开展示的事件；不记录 Prompt、隐藏思维链或原始视频内容。"""
        if self._events is None:
            return
        async with self._event_lock:
            self._trace_sequence += 1
            await self._events.append_trace_event(
                TraceEvent(
                    trace_id=self.run.id,
                    sequence=self._trace_sequence,
                    event_type=event_type,
                    name=name,
                    status=status,
                    summary=summary,
                    video_id=self.run.video_id,
                    agent_id=self.run.agent_name,
                    attributes=attributes or {},
                )
            )

    async def invoke_tool(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        if name not in self.allowed_tools:
            raise PolicyDeniedError(f"Agent 无权调用工具: {name}")
        spec = self.registry.get(name)
        if spec is None:
            raise PolicyDeniedError(f"未知工具: {name}")

        # 参数先经过 Pydantic 严格校验；多余字段和错误类型都会被拒绝。
        validated_input = spec.input_model.model_validate(arguments)
        signature = self._call_signature(name, validated_input)
        count = self._tool_call_counts.get(signature, 0) + 1
        if count > self.run.budget.max_repeated_tool_call:
            raise PolicyDeniedError(f"阻止重复工具循环: {name}")
        self._tool_call_counts[signature] = count

        await self.ledger.reserve_tool()
        step_index = await self.ledger.reserve_step()
        await self.emit(
            TraceEventType.TOOL_CALLED,
            name=name,
            status="running",
            summary="工具参数已通过强类型校验",
            attributes={"step_index": step_index},
        )
        started = time.monotonic()
        try:
            raw_result = await asyncio.wait_for(
                spec.handler(validated_input),
                timeout=spec.timeout_seconds,
            )
            result = spec.output_model.model_validate(raw_result)
            self._append_step(
                index=step_index,
                kind="tool",
                name=name,
                status="completed",
                summary=f"参数已校验，返回 {self._result_summary(result)}",
                started=started,
            )
            await self.emit(
                TraceEventType.TOOL_RETURNED,
                name=name,
                status="completed",
                summary=self._result_summary(result),
                attributes={
                    "step_index": step_index,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return result
        except TimeoutError as exc:
            self._append_step(
                index=step_index,
                kind="tool",
                name=name,
                status="timed_out",
                summary="工具执行超时",
                started=started,
            )
            await self.emit(
                TraceEventType.TOOL_RETURNED,
                name=name,
                status="timed_out",
                summary="工具执行超时",
                attributes={"step_index": step_index},
            )
            raise ToolExecutionError(f"工具 {name} 执行超时") from exc
        except Exception as exc:
            self._append_step(
                index=step_index,
                kind="tool",
                name=name,
                status="failed",
                summary=f"{type(exc).__name__}: {str(exc)[:120]}",
                started=started,
            )
            await self.emit(
                TraceEventType.TOOL_RETURNED,
                name=name,
                status="failed",
                summary=type(exc).__name__,
                attributes={"step_index": step_index},
            )
            raise

    async def reserve_model_call(
        self,
        *,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        estimated_cost_usd: Decimal = Decimal("0"),
        model_name: str,
    ) -> None:
        await self.ledger.reserve_model(
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )
        step_index = await self.ledger.reserve_step()
        self.run.steps.append(
            AgentStep(
                index=step_index,
                kind="model",
                name=model_name,
                status="reserved",
                summary=(
                    f"预留输入 {estimated_input_tokens} / 输出 {estimated_output_tokens} tokens"
                ),
            )
        )
        await self.emit(
            TraceEventType.MODEL_REQUESTED,
            name=model_name,
            status="reserved",
            summary="模型预算已预留",
            attributes={
                "step_index": step_index,
                "estimated_input_tokens": estimated_input_tokens,
                "estimated_output_tokens": estimated_output_tokens,
            },
        )

    def complete(self, status: RunStatus, stop_reason: str) -> None:
        self.run.status = status
        self.run.stop_reason = stop_reason
        self.run.usage = self.ledger.usage.model_copy(
            update={"elapsed_ms": self.ledger.elapsed_ms()}
        )
        self.run.finished_at = utc_now()

    def _append_step(
        self,
        *,
        index: int,
        kind: str,
        name: str,
        status: str,
        summary: str,
        started: float,
    ) -> None:
        self.run.steps.append(
            AgentStep(
                index=index,
                kind=kind,
                name=name,
                status=status,
                summary=summary,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        )

    @staticmethod
    def _call_signature(name: str, value: BaseModel) -> str:
        digest = hashlib.sha256(value.model_dump_json().encode("utf-8")).hexdigest()
        return f"{name}:{digest}"

    @staticmethod
    def _result_summary(result: BaseModel) -> str:
        dumped = result.model_dump()
        for value in dumped.values():
            if isinstance(value, list):
                return f"{len(value)} 项结构化结果"
        return "结构化结果"


class AgentHarness:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        events: ObservabilityRepository | None = None,
    ) -> None:
        self.registry = registry
        self.events = events

    def start_session(
        self,
        *,
        run: AgentRun,
        allowed_tools: set[str] | frozenset[str],
    ) -> HarnessSession:
        unknown = set(allowed_tools) - self.registry.names
        if unknown:
            raise ValueError(f"白名单包含未注册工具: {sorted(unknown)}")
        return HarnessSession(
            run=run,
            registry=self.registry,
            allowed_tools=frozenset(allowed_tools),
            events=self.events,
        )
