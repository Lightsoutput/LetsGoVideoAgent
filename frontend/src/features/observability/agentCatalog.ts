export const AGENT_CATALOG: Record<string, { number: string; name: string; role: string }> = {
  workflow_coordinator: { number: "A00", name: "小航", role: "任务调度" },
  ingestion_agent: { number: "A01", name: "小载", role: "媒体接入" },
  audio_perception_agent: { number: "A02", name: "小听", role: "语音转写" },
  visual_sampling_agent: { number: "A03", name: "小镜", role: "画面采样" },
  ocr_perception_agent: { number: "A04", name: "小字", role: "字幕与文字" },
  vlm_understanding_agent: { number: "A05", name: "小观", role: "视觉理解" },
  speaker_analysis_agent: { number: "A06", name: "小声", role: "说话人分析" },
  timeline_curator_agent: { number: "A07", name: "小编", role: "分段与总结" },
  skill_builder_agent: { number: "A08", name: "小策", role: "类别规律提炼" },
  qa_investigator: { number: "A09", name: "小问", role: "问题调查" },
  evidence_verifier: { number: "A10", name: "小证", role: "证据核验" },
  web_research_agent: { number: "A11", name: "小搜", role: "联网研究" },
  recovery_agent: { number: "A12", name: "小修", role: "异常恢复" },
};

export function agentLabel(agentId: string | null) {
  if (!agentId) return "等待分配";
  const agent = AGENT_CATALOG[agentId];
  return agent ? `${agent.number} ${agent.name} · ${agent.role}` : agentId;
}
