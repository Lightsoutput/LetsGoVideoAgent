from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import Field

from lets_go_video_agent.agents.harness.models import AgentRun
from lets_go_video_agent.bootstrap import build_container
from lets_go_video_agent.config import Settings
from lets_go_video_agent.domain.common import DomainModel, ModelUsage, TimeRange, utc_now
from lets_go_video_agent.domain.qa import (
    AnswerStatus,
    FrameTarget,
    GlobalTarget,
    MomentTarget,
    QuestionTarget,
    RangeTarget,
)
from lets_go_video_agent.fixtures import DEMO_VIDEO_ID


class SyntheticEvalCase(DomainModel):
    id: str
    query: str
    target: QuestionTarget
    require_snapshot: bool = False


class CaseResult(DomainModel):
    id: str
    target_kind: str
    passed: bool
    checks: dict[str, bool]
    answer_status: str
    citation_count: int = Field(ge=0)
    trace_id: str
    usage: ModelUsage


class EvalReport(DomainModel):
    suite: str = "synthetic-p0"
    generated_at: datetime = Field(default_factory=utc_now)
    passed: bool
    passed_cases: int = Field(ge=0)
    total_cases: int = Field(ge=1)
    pass_rate: float = Field(ge=0, le=1)
    total_estimated_cost_usd: str
    results: list[CaseResult]


CASES: tuple[SyntheticEvalCase, ...] = (
    SyntheticEvalCase(
        id="global-summary",
        query="这个视频主要讲了什么？请给出时间戳证据。",
        target=GlobalTarget(),
    ),
    SyntheticEvalCase(
        id="chapter-range",
        query="这一段的阵容与部署顺序是什么？",
        target=RangeTarget(time_range=TimeRange(start_ms=60_000, end_ms=110_000)),
    ),
    SyntheticEvalCase(
        id="moment-context",
        query="70 秒附近的声音与画面共同表达了什么？",
        target=MomentTarget(timestamp_ms=70_000, context_window_ms=10_000),
    ),
    SyntheticEvalCase(
        id="current-frame",
        query="只根据当前帧，说明界面上有什么内容。",
        target=FrameTarget(timestamp_ms=70_000),
        require_snapshot=True,
    ),
)


def _citations_match_target(case: SyntheticEvalCase, timestamps: Sequence[int]) -> bool:
    """检查引用是否真正落在用户指定范围，而不是只要“有引用”就算通过。"""

    if not timestamps:
        return False
    if isinstance(case.target, RangeTarget):
        return all(case.target.time_range.contains(value) for value in timestamps)
    if isinstance(case.target, MomentTarget):
        start = max(0, case.target.timestamp_ms - case.target.context_window_ms)
        end = case.target.timestamp_ms + case.target.context_window_ms
        # 片段证据可能从上下文窗口之前开始，因此要求至少有一个精确锚点命中，
        # 而不是错误地拒绝一条实际与窗口重叠的长字幕或章节证据。
        return any(start <= value <= end for value in timestamps)
    return True


async def evaluate_synthetic_suite() -> EvalReport:
    """运行确定性、零 API 费用的冒烟评测，验证 Harness 的关键产品契约。"""

    container = build_container(
        Settings(
            repository_backend="memory",
            workflow_backend="inline",
            seed_demo_data=True,
            llm_provider="mock",
            vlm_provider="mock",
        )
    )
    await container.startup()
    results: list[CaseResult] = []
    try:
        for case in CASES:
            answer = await container.questions.ask(
                video_id=DEMO_VIDEO_ID,
                query=case.query,
                target=case.target,
            )
            run_record = await container.store.get_run(answer.trace_id)
            run = AgentRun.model_validate(run_record) if run_record is not None else None
            timestamps = [citation.timestamp_ms for citation in answer.citations]
            evidence_ids = {item.id for item in answer.evidence}
            checks = {
                "answered": answer.status is AnswerStatus.ANSWERED,
                "has_citations": bool(answer.citations),
                "citation_provenance": all(
                    citation.evidence_id in evidence_ids for citation in answer.citations
                ),
                "target_alignment": _citations_match_target(case, timestamps),
                "trace_completed": run is not None and run.status.value == "completed",
                "public_trace_only": run is not None
                and all("thought" not in step.model_dump_json().lower() for step in run.steps),
                "within_tool_budget": answer.usage.tool_calls
                <= container.settings.agent_max_tool_calls,
                "snapshot_evidence": (
                    not case.require_snapshot
                    or any(citation.snapshot_url for citation in answer.citations)
                ),
            }
            results.append(
                CaseResult(
                    id=case.id,
                    target_kind=case.target.kind,
                    passed=all(checks.values()),
                    checks=checks,
                    answer_status=answer.status.value,
                    citation_count=len(answer.citations),
                    trace_id=str(answer.trace_id),
                    usage=answer.usage,
                )
            )
    finally:
        await container.shutdown()

    passed_cases = sum(result.passed for result in results)
    total_cost = sum(result.usage.estimated_cost_usd for result in results)
    return EvalReport(
        passed=passed_cases == len(results),
        passed_cases=passed_cases,
        total_cases=len(results),
        pass_rate=passed_cases / len(results),
        total_estimated_cost_usd=str(total_cost),
        results=results,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="运行 LetsGoVideoAgent 的离线合成视频评测。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="可选 JSON 报告路径；不传时仅输出到标准输出。",
    )
    return parser


def _write_report(path: Path, payload: str) -> Path:
    """文件 I/O 放入线程，避免阻塞正在执行 Agent 评测的事件循环。"""

    output = path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{payload}\n", encoding="utf-8")
    return output


async def _async_run(args: argparse.Namespace) -> int:
    report = await evaluate_synthetic_suite()
    payload = report.model_dump_json(indent=2)
    if args.output:
        output = await asyncio.to_thread(_write_report, args.output, payload)
        print(f"评测报告已写入: {output}")
    print(payload)
    return 0 if report.passed else 1


def run(argv: Sequence[str] | None = None) -> int:
    """Console script 入口；返回非零状态可直接作为 CI 的质量门禁。"""

    return asyncio.run(_async_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(run())
