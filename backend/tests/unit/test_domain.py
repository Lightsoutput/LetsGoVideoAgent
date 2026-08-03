from uuid import uuid4

import pytest
from pydantic import ValidationError

from lets_go_video_agent.domain.common import Provenance, TimeRange
from lets_go_video_agent.domain.qa import Answer, AnswerStatus
from lets_go_video_agent.domain.timeline import Evidence, EvidenceKind


def test_time_range_rejects_invalid_bounds() -> None:
    with pytest.raises(ValidationError):
        TimeRange(start_ms=1_000, end_ms=1_000)


def test_evidence_requires_temporal_anchor() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            video_id=uuid4(),
            kind=EvidenceKind.VISUAL,
            description="没有时间锚点的证据",
            provenance=Provenance(producer="test"),
        )


def test_answered_answer_requires_citation() -> None:
    with pytest.raises(ValidationError):
        Answer(
            question_id=uuid4(),
            status=AnswerStatus.ANSWERED,
            text="不应被接受的无证据回答",
            trace_id=uuid4(),
        )
