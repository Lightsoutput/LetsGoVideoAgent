from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """全系统唯一的 Agent 身份。

    UI、Trace、成本事件与 Skill 项目都只使用这里的编号和名称，避免同一位
    Agent 在不同页面出现不同叫法。
    """

    id: str
    number: str
    name: str
    role: str
    avatar: str
    model_capability: str | None = None

    @property
    def display_name(self) -> str:
        return f"{self.number} · {self.name}"


AGENT_CATALOG: tuple[AgentDefinition, ...] = (
    AgentDefinition("workflow_coordinator", "A00", "小航", "任务调度", "🧭"),
    AgentDefinition("ingestion_agent", "A01", "小载", "媒体接入", "📥"),
    AgentDefinition(
        "audio_perception_agent", "A02", "小听", "语音转写", "🎧", "local_asr"
    ),
    AgentDefinition("visual_sampling_agent", "A03", "小镜", "画面采样", "🎬"),
    AgentDefinition("ocr_perception_agent", "A04", "小字", "字幕与文字", "🔎", "local_ocr"),
    AgentDefinition(
        "vlm_understanding_agent", "A05", "小观", "视觉理解", "👁", "vision"
    ),
    AgentDefinition("speaker_analysis_agent", "A06", "小声", "说话人分析", "🎙"),
    AgentDefinition(
        "timeline_curator_agent", "A07", "小编", "分段与总结", "🧩", "reasoning"
    ),
    AgentDefinition(
        "skill_builder_agent", "A08", "小策", "类别规律提炼", "✨", "reasoning"
    ),
    AgentDefinition("qa_investigator", "A09", "小问", "问题调查", "💬", "reasoning"),
    AgentDefinition("evidence_verifier", "A10", "小证", "证据核验", "🛡", "reasoning"),
    AgentDefinition("web_research_agent", "A11", "小搜", "联网研究", "🌐", "reasoning"),
    AgentDefinition("recovery_agent", "A12", "小修", "异常恢复", "🧰"),
)

_BY_ID = {agent.id: agent for agent in AGENT_CATALOG}


def get_agent(agent_id: str | None) -> AgentDefinition:
    """返回稳定身份；未知扩展 Agent 也得到可读的兼容编号。"""

    if agent_id and agent_id in _BY_ID:
        return _BY_ID[agent_id]
    fallback_id = agent_id or "unknown_agent"
    return AgentDefinition(fallback_id, "EXT", fallback_id, "扩展任务", "⚙")


def agent_trace_attributes(agent_id: str) -> dict[str, str]:
    agent = get_agent(agent_id)
    return {
        "agent_number": agent.number,
        "agent_name": agent.name,
        "agent_role": agent.role,
        "agent_display_name": agent.display_name,
    }
