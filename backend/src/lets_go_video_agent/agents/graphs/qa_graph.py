from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from lets_go_video_agent.agents.harness.engine import HarnessSession
from lets_go_video_agent.agents.roles.evidence_verifier import (
    EvidenceVerifier,
    VerificationOutcome,
)
from lets_go_video_agent.agents.roles.qa_investigator import DraftAnswer, QAInvestigator
from lets_go_video_agent.domain.qa import Answer, Question


class QAState(TypedDict, total=False):
    """LangGraph 状态与 API DTO、数据库 ORM 分离，避免框架状态污染领域模型。"""

    question: Question
    session: HarnessSession
    video_duration_ms: int | None
    draft: DraftAnswer
    verification: VerificationOutcome
    answer: Answer
    repair_count: int


def build_qa_graph(
    investigator: QAInvestigator,
    verifier: EvidenceVerifier,
) -> Any:
    """构建受控 Agentic RAG 图。

    图最多补充检索一次；更多循环由 Harness 的步骤、工具和时间预算进一步兜底。
    这保留了 ReAct 的“观察后再行动”，但不会演变成 AutoGPT 式无限自治循环。
    """

    async def investigate(state: QAState) -> dict[str, object]:
        draft = await investigator.investigate(
            question=state["question"],
            session=state["session"],
            limit=8,
        )
        return {"draft": draft}

    async def supplement(state: QAState) -> dict[str, object]:
        draft = await investigator.investigate(
            question=state["question"],
            session=state["session"],
            limit=16,
        )
        return {
            "draft": draft,
            "repair_count": state.get("repair_count", 0) + 1,
        }

    async def verify(state: QAState) -> dict[str, object]:
        session = state["session"]
        outcome = verifier.verify(
            question=state["question"],
            draft=state["draft"],
            trace_id=session.run.id,
            video_duration_ms=state.get("video_duration_ms"),
            usage=session.ledger.usage,
        )
        return {"verification": outcome, "answer": outcome.answer}

    def route_after_verification(state: QAState) -> str:
        outcome = state["verification"]
        if outcome.needs_repair and state.get("repair_count", 0) < 1:
            return "supplement"
        return "finish"

    graph = StateGraph(QAState)
    graph.add_node("investigate", investigate)
    graph.add_node("supplement", supplement)
    graph.add_node("verify", verify)
    graph.add_edge(START, "investigate")
    graph.add_edge("investigate", "verify")
    graph.add_conditional_edges(
        "verify",
        route_after_verification,
        {"supplement": "supplement", "finish": END},
    )
    graph.add_edge("supplement", "verify")
    return graph.compile()
