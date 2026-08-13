from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from lets_go_video_agent.application.ports import ObservabilityRepository
from lets_go_video_agent.domain.observability import UsageEvent


@dataclass(frozen=True, slots=True)
class DeepSeekPrices:
    """DeepSeek V4 Flash 官方人民币价格（每 100 万 tokens）。"""

    cache_hit_input: Decimal = Decimal("0.02")
    cache_miss_input: Decimal = Decimal("1")
    output: Decimal = Decimal("2")


class CostLedger:
    """只记录计费元数据，不保存提示词、视频内容或 API Key。"""

    def __init__(
        self,
        path: Path,
        *,
        events: ObservabilityRepository | None = None,
        hydrate_events: bool = False,
    ) -> None:
        self.path = path
        self._events = events
        self._hydrate_events = hydrate_events
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    async def record(self, record: dict[str, Any], usage: UsageEvent) -> None:
        """同时保留 P0 JSONL 兼容记录和 V1.0 可查询的统一用量事件。"""
        self.append(record)
        if self._events is not None:
            await self._events.append_usage_event(usage)

    async def hydrate(self) -> int:
        """内存仓库启动时回放历史账本，让成本中心跨重启仍可按任务归因。"""

        if not self._hydrate_events or self._events is None or not self.path.exists():
            return 0
        existing = await self._events.list_usage_events()
        if existing:
            return 0
        hydrated = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                event = _usage_from_record(record)
            except (json.JSONDecodeError, TypeError, ValueError, ArithmeticError):
                continue
            await self._events.append_usage_event(event)
            hydrated += 1
        return hydrated

    def summary(self) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        total = sum((_record_cost_cny(item) for item in records), Decimal())
        return {
            "currency": "CNY",
            "total_cost_cny": str(total.quantize(Decimal("0.000000001"))),
            "call_count": len(records),
            "records": records[-50:],
        }


class DeepSeekClient:
    """DeepSeek 的窄适配层，直接读取官方 usage 计算人民币实付估算。"""

    provider = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str,
        ledger: CostLedger,
        prices: DeepSeekPrices | None = None,
        proxy_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._api_base = api_base.rstrip("/")
        self._ledger = ledger
        self._prices = prices or DeepSeekPrices()
        self._proxy_url = proxy_url

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        purpose: str,
        video_id: str | None = None,
        trace_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        max_tokens: int = 1800,
        thinking: bool = False,
        reasoning_effort: str = "high",
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if thinking:
            payload["reasoning_effort"] = reasoning_effort
        else:
            payload["temperature"] = 0
        # 深度思考会先生成推理 token，同一问题通常比普通 JSON 回答耗时更长。
        # 这里仅放宽思考请求的读取窗口；普通请求仍保持较短超时，避免 Worker 假死。
        async with httpx.AsyncClient(
            timeout=120 if thinking else 90,
            proxy=self._proxy_url,
        ) as client:
            response = await client.post(
                f"{self._api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        hit = int(usage.get("prompt_cache_hit_tokens") or details.get("cached_tokens") or 0)
        prompt = int(usage.get("prompt_tokens") or 0)
        miss = int(usage.get("prompt_cache_miss_tokens") or max(0, prompt - hit))
        output = int(usage.get("completion_tokens") or 0)
        million = Decimal("1000000")
        cost = (
            Decimal(hit) * self._prices.cache_hit_input
            + Decimal(miss) * self._prices.cache_miss_input
            + Decimal(output) * self._prices.output
        ) / million
        record = {
                "timestamp": datetime.now(UTC).isoformat(),
                "provider": "deepseek",
                "model": body.get("model", self.model),
                "purpose": purpose,
                "video_id": video_id,
                "trace_id": trace_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "cache_hit_input_tokens": hit,
                "cache_miss_input_tokens": miss,
                "output_tokens": output,
                "total_tokens": int(usage.get("total_tokens") or prompt + output),
                "cost_cny": str(cost.quantize(Decimal("0.000000001"))),
                "pricing_source": "DeepSeek official V4 Flash pricing",
            }
        await self._ledger.record(
            record,
            UsageEvent(
                provider="deepseek",
                model=str(body.get("model", self.model)),
                purpose=purpose,
                input_tokens=prompt,
                output_tokens=output,
                original_cost=cost,
                cost_cny=cost,
                cache_hit=hit > 0,
                pricing_version="DeepSeek official V4 Flash pricing",
                video_id=_optional_uuid(video_id),
                trace_id=_optional_uuid(trace_id),
                task_id=_optional_uuid(task_id),
                agent_id=agent_id,
            ),
        )
        content = str(body["choices"][0]["message"].get("content") or "").strip()
        return _parse_json_object(content)


def _parse_json_object(content: str) -> dict[str, Any]:
    """兼容偶发 Markdown 围栏或 JSON 前后说明，避免有效结构化响应被误判。"""
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1]).strip() if len(lines) >= 3 else content
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(content[start : end + 1])
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("expected JSON object", content, 0)
    return parsed


def _usage_from_record(record: dict[str, Any]) -> UsageEvent:
    input_tokens = int(
        record.get("input_tokens")
        or int(record.get("cache_hit_input_tokens") or 0)
        + int(record.get("cache_miss_input_tokens") or 0)
    )
    output_tokens = int(record.get("output_tokens") or 0)
    cost_cny = _record_cost_cny(record)
    pricing_source = str(record.get("pricing_source") or "historical-ledger")
    if (
        str(record.get("provider") or "").lower() == "siliconflow"
        and Decimal(str(record.get("cost_cny") or "0")) == 0
        and cost_cny > 0
    ):
        pricing_source = "SiliconFlow official token pricing (historical recalculation)"
    return UsageEvent(
        provider=str(record.get("provider") or "unknown"),
        model=str(record.get("model") or "unknown"),
        purpose=str(record.get("purpose") or "unknown"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_count=int(record.get("image_count") or 0),
        original_cost=cost_cny,
        cost_cny=cost_cny,
        pricing_version=pricing_source,
        trace_id=_optional_uuid(record.get("trace_id")),
        task_id=_optional_uuid(record.get("task_id")),
        video_id=_optional_uuid(record.get("video_id")),
        agent_id=str(record.get("agent_id")) if record.get("agent_id") else None,
    )


def _record_cost_cny(record: dict[str, Any]) -> Decimal:
    """读取账本费用；修复旧硅基流动记录因余额精度不足而被写成 0 的问题。"""

    stored = Decimal(str(record.get("cost_cny") or "0"))
    if stored > 0 or str(record.get("provider") or "").lower() != "siliconflow":
        return stored
    input_tokens = int(record.get("input_tokens") or 0)
    output_tokens = int(record.get("output_tokens") or 0)
    # Qwen/Qwen3-VL-32B-Instruct：输入 1 元/M tokens，输出 4 元/M tokens。
    return (
        Decimal(input_tokens) * Decimal("1")
        + Decimal(output_tokens) * Decimal("4")
    ) / Decimal("1000000")


def _optional_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None
