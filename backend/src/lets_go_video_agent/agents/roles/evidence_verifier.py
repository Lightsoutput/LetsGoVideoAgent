from __future__ import annotations

from uuid import UUID

from pydantic import Field

from lets_go_video_agent.agents.roles.qa_investigator import DraftAnswer
from lets_go_video_agent.domain.common import DomainModel, ModelUsage
from lets_go_video_agent.domain.qa import (
    Answer,
    AnswerStatus,
    EvidenceCitation,
    GlobalTarget,
    Question,
)


class VerificationOutcome(DomainModel):
    answer: Answer
    passed: bool
    needs_repair: bool
    issues: list[str] = Field(default_factory=list)


class EvidenceVerifier:
    """对草稿的每一条引用做确定性校验。

    生产版本还会使用轻量模型比较“主张是否被证据语义支持”；P0 基线先保证引用 ID、
    时间锚点、截图来源和视频范围都是真实存在的，验证失败就降级而不是硬答。
    """

    name = "evidence_verifier"
    version = "0.1.0"

    def verify(
        self,
        *,
        question: Question,
        draft: DraftAnswer,
        trace_id: UUID,
        video_duration_ms: int | None,
        usage: ModelUsage,
    ) -> VerificationOutcome:
        evidence_by_id = {item.id: item for item in draft.evidence}
        valid: list[EvidenceCitation] = []
        issues: list[str] = []

        for citation in draft.citations:
            evidence = evidence_by_id.get(citation.evidence_id)
            if evidence is None:
                issues.append(f"引用不存在: {citation.evidence_id}")
                continue
            if video_duration_ms is not None and citation.timestamp_ms > video_duration_ms:
                issues.append(f"时间戳超出视频范围: {citation.timestamp_ms}")
                continue
            if evidence.time_range and not evidence.time_range.contains(citation.timestamp_ms):
                issues.append(f"引用时间不在证据范围内: {citation.evidence_id}")
                continue
            valid.append(citation)

        summary_coverage_failed = False
        if (
            isinstance(question.target, GlobalTarget)
            and video_duration_ms
            and _is_summary_query(question.query)
        ):
            covered_thirds = {
                min(2, citation.timestamp_ms * 3 // max(1, video_duration_ms))
                for citation in valid
            }
            if len(covered_thirds) < 3:
                summary_coverage_failed = True
                issues.append("全片总结的引用没有覆盖开头、中段和后段")

        if not valid:
            status = AnswerStatus.ABSTAINED
            text = "证据验证未通过，因此我暂时不能对这个问题给出可靠结论。"
            confidence = 0.0
        elif issues:
            status = AnswerStatus.PARTIAL
            text = draft.text
            confidence = min(draft.confidence, 0.6)
        else:
            status = AnswerStatus.ANSWERED
            text = draft.text
            confidence = draft.confidence

        answer = Answer(
            question_id=question.id,
            status=status,
            text=text,
            citations=valid,
            evidence=[
                item for item in draft.evidence if any(c.evidence_id == item.id for c in valid)
            ],
            confidence=confidence,
            limitations=[*draft.limitations, *issues],
            trace_id=trace_id,
            usage=usage,
        )
        passed = status is AnswerStatus.ANSWERED
        return VerificationOutcome(
            answer=answer,
            passed=passed,
            needs_repair=status is AnswerStatus.ABSTAINED or summary_coverage_failed,
            issues=issues,
        )


def _is_summary_query(query: str) -> bool:
    normalized = query.lower().replace(" ", "")
    return any(marker in normalized for marker in ("总结", "概括", "主要内容", "讲了什么", "大意"))
