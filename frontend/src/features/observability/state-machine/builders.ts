import { MarkerType } from "@xyflow/react";

import type { SystemObservability, TraceEvent } from "@/lib/api/types";

import type {
  MachineEdge,
  MachineGraph,
  MachineNode,
  MachineStatus,
} from "./types";

interface NodeTemplate {
  id: string;
  label: string;
  category: string;
  x: number;
  y: number;
  summary: string;
  badge?: string;
}

interface EdgeTemplate {
  source: string;
  target: string;
  label?: string;
}

const PROCESSING_NODES: NodeTemplate[] = [
  { id: "video_processing_graph", label: "视频处理工作流", category: "workflow", x: 0, y: 210, summary: "接收媒体任务并驱动完整处理图" },
  { id: "ingestion_agent", label: "A01 小载 · 媒体接入", category: "agent", x: 270, y: 210, summary: "下载、探测并登记媒体元数据" },
  { id: "perception_coordinator", label: "感知协调器", category: "gate", x: 540, y: 210, summary: "分叉音频与视觉感知任务" },
  { id: "audio_perception_agent", label: "A02 小听 · 语音转写", category: "agent", x: 820, y: 40, summary: "语音转写与时间戳对齐", badge: "并行组 A" },
  { id: "visual_sampling_agent", label: "A03 小镜 · 画面采样", category: "agent", x: 820, y: 390, summary: "抽取可访问的候选画面", badge: "并行组 A" },
  { id: "ocr_perception_agent", label: "A04 小字 · 字幕与文字", category: "agent", x: 1100, y: 300, summary: "识别画面中的文字证据", badge: "并行组 B" },
  { id: "vlm_understanding_agent", label: "A05 小观 · 视觉理解", category: "agent", x: 1100, y: 500, summary: "理解人物、动作、界面与场景含义", badge: "并行组 B" },
  { id: "perception_fusion_gate", label: "跨模态汇合门", category: "gate", x: 1390, y: 210, summary: "等待 ASR、OCR 与 VLM 分支汇合" },
  { id: "speaker_analysis_agent", label: "A06 小声 · 说话人分析", category: "agent", x: 1680, y: 70, summary: "融合音色、对话逻辑与画面称呼" },
  { id: "timeline_curator_agent", label: "A07 小编 · 分段与总结", category: "agent", x: 1680, y: 350, summary: "生成章节、片段摘要、字幕与关键帧" },
  { id: "processing_result", label: "视频理解结果", category: "output", x: 1970, y: 210, summary: "发布可问答的视频记忆与时间轴" },
];

const PROCESSING_EDGES: EdgeTemplate[] = [
  { source: "video_processing_graph", target: "ingestion_agent" },
  { source: "ingestion_agent", target: "perception_coordinator" },
  { source: "perception_coordinator", target: "audio_perception_agent", label: "并行" },
  { source: "perception_coordinator", target: "visual_sampling_agent", label: "并行" },
  { source: "visual_sampling_agent", target: "ocr_perception_agent", label: "并行" },
  { source: "visual_sampling_agent", target: "vlm_understanding_agent", label: "并行" },
  { source: "audio_perception_agent", target: "perception_fusion_gate" },
  { source: "ocr_perception_agent", target: "perception_fusion_gate" },
  { source: "vlm_understanding_agent", target: "perception_fusion_gate" },
  { source: "perception_fusion_gate", target: "speaker_analysis_agent" },
  { source: "speaker_analysis_agent", target: "timeline_curator_agent" },
  { source: "timeline_curator_agent", target: "processing_result" },
];

const QA_NODES: NodeTemplate[] = [
  { id: "video_qa_graph", label: "视频问答工作流", category: "workflow", x: 0, y: 210, summary: "接收问题并建立受控 Harness 会话" },
  { id: "qa_investigator", label: "A09 小问 · 问题调查", category: "agent", x: 290, y: 100, summary: "检索视频时间轴、当前帧与上下文" },
  { id: "web_research_agent", label: "A11 小搜 · 联网研究", category: "agent", x: 290, y: 360, summary: "勾选联网后通过 MCP 补充外部证据", badge: "按需" },
  { id: "evidence_verifier", label: "A10 小证 · 证据核验", category: "agent", x: 600, y: 210, summary: "检查引用、时间范围与回答覆盖度" },
  { id: "qa_investigator:supplement", label: "补充调查回路", category: "agent", x: 900, y: 400, summary: "验证未通过时扩大检索范围", badge: "最多一次" },
  { id: "qa_workflow_result", label: "证据化回答", category: "output", x: 940, y: 120, summary: "发布回答、证据截图与 Trace" },
];

const QA_EDGES: EdgeTemplate[] = [
  { source: "video_qa_graph", target: "qa_investigator" },
  { source: "video_qa_graph", target: "web_research_agent", label: "勾选联网" },
  { source: "qa_investigator", target: "evidence_verifier" },
  { source: "web_research_agent", target: "evidence_verifier" },
  { source: "evidence_verifier", target: "qa_workflow_result" },
  { source: "evidence_verifier", target: "qa_investigator:supplement", label: "需修复" },
  { source: "qa_investigator:supplement", target: "evidence_verifier", label: "重验" },
];

const SKILL_NODES: NodeTemplate[] = [
  { id: "skill_builder_graph", label: "Skill 生成工作流", category: "workflow", x: 0, y: 190, summary: "接收样本视频与用户领域目标" },
  { id: "sample_analysis_agent", label: "样本分析 Agent", category: "agent", x: 280, y: 70, summary: "抽取视频格式、主题、叙事目的与章节共性" },
  { id: "skill_builder_agent", label: "A08 小策 · 类别规律提炼", category: "agent", x: 280, y: 310, summary: "把共性提炼为可复用领域规则" },
  { id: "skill_policy_validator", label: "权限与静态检查", category: "gate", x: 580, y: 190, summary: "检查内容完整性、工具白名单与提示注入风险" },
  { id: "human_approval", label: "人工审核发布", category: "human", x: 870, y: 80, summary: "草案必须由用户明确确认后才能启用" },
  { id: "skill_rollback", label: "版本与回滚", category: "gate", x: 870, y: 300, summary: "保留历史发布版本并安全切换运行时" },
  { id: "skill_draft_ready", label: "Skill 版本产物", category: "output", x: 1160, y: 190, summary: "生成草案或已发布的 SKILL.md" },
];

const SKILL_EDGES: EdgeTemplate[] = [
  { source: "skill_builder_graph", target: "sample_analysis_agent" },
  { source: "skill_builder_graph", target: "skill_builder_agent" },
  { source: "sample_analysis_agent", target: "skill_policy_validator" },
  { source: "skill_builder_agent", target: "skill_policy_validator" },
  { source: "skill_policy_validator", target: "human_approval", label: "通过" },
  { source: "skill_policy_validator", target: "skill_rollback", label: "版本化" },
  { source: "human_approval", target: "skill_draft_ready" },
  { source: "skill_rollback", target: "skill_draft_ready" },
];

function nodeId(event: TraceEvent) {
  return typeof event.attributes.node_id === "string" ? event.attributes.node_id : event.name;
}

function statusFromEvents(events: TraceEvent[]): MachineStatus {
  let status: MachineStatus = "pending";
  for (const event of events.slice().sort((left, right) => left.sequence - right.sequence)) {
    const action = event.event_type.split(".")[1];
    if (action === "failed" || event.status === "failed") status = "failed";
    else if (["completed", "returned", "validated", "approved", "rejected"].includes(action)) status = "completed";
    else if (["started", "requested", "called", "loaded"].includes(action)) status = "running";
  }
  return status;
}

function edgeStatus(source: MachineStatus, target: MachineStatus): MachineStatus {
  if ([source, target].some((status) => ["failed", "unavailable"].includes(status))) return "failed";
  if (target === "running") return "running";
  if (source === "completed" && target === "completed") return "completed";
  return "pending";
}

function createEdges(templates: EdgeTemplate[], nodes: MachineNode[]): MachineEdge[] {
  const status = new Map(nodes.map((node) => [node.id, node.data.status]));
  return templates.map((edge, index) => {
    const current = edgeStatus(status.get(edge.source) ?? "pending", status.get(edge.target) ?? "pending");
    const color = current === "failed" ? "#ff6b7a" : current === "completed" ? "#2ee6aa" : current === "running" ? "#f5b654" : "#405363";
    return {
      id: `${edge.source}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      type: "smoothstep",
      animated: current === "running",
      className: `machine-edge machine-edge-${current}`,
      style: { stroke: color, strokeWidth: current === "running" ? 2.5 : 1.6 },
      labelStyle: { fill: "#8fa7b9", fontSize: 9 },
      labelBgStyle: { fill: "#09131f", fillOpacity: 0.9 },
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 15, height: 15 },
    };
  });
}

function graphFromTemplates(
  templates: NodeTemplate[],
  edgeTemplates: EdgeTemplate[],
  trace: TraceEvent[],
  title: string,
  description: string,
): MachineGraph {
  const nodes: MachineNode[] = templates.map((template) => {
    const events = trace.filter((event) => nodeId(event) === template.id || event.name === template.id);
    const latest = events.at(-1);
    return {
      id: template.id,
      type: "machine",
      position: { x: template.x, y: template.y },
      data: {
        label: template.label,
        category: template.category,
        status: statusFromEvents(events),
        summary: latest?.summary || template.summary,
        occurredAt: latest?.occurred_at,
        badge: template.badge,
      },
    };
  });

  // 上游只有 started 事件时，只要下游已经进入，就可安全推断该阶段已经交接完成。
  for (const edge of edgeTemplates) {
    const source = nodes.find((node) => node.id === edge.source);
    const target = nodes.find((node) => node.id === edge.target);
    if (source?.data.status === "running" && target && target.data.status !== "pending") {
      source.data.status = "completed";
    }
  }
  const terminal = trace.findLast((event) => ["workflow.completed", "workflow.failed"].includes(event.event_type));
  const result = nodes.find((node) =>
    ["processing_result", "qa_workflow_result", "skill_draft_ready"].includes(node.id),
  );
  if (terminal && result) {
    result.data.status = terminal.event_type === "workflow.failed" ? "failed" : "completed";
    result.data.summary = terminal.summary;
    result.data.occurredAt = terminal.occurred_at;
  }
  return { nodes, edges: createEdges(edgeTemplates, nodes), title, description };
}

export function buildAgentGraph(trace: TraceEvent[], preferProcessing = false): MachineGraph {
  const skillBuilding = trace.some((event) =>
    ["skill_builder_graph", "sample_analysis_agent", "skill_policy_validator"].includes(nodeId(event)),
  );
  if (skillBuilding) {
    return graphFromTemplates(
      SKILL_NODES,
      SKILL_EDGES,
      trace,
      "Skill Builder 状态机",
      "样本分析、规则生成、静态检查、人工发布与版本回滚",
    );
  }
  const processing = preferProcessing || trace.some((event) =>
    ["video_processing_graph", "audio_perception_agent", "visual_sampling_agent"].includes(nodeId(event)),
  );
  return processing
    ? graphFromTemplates(PROCESSING_NODES, PROCESSING_EDGES, trace, "多 Agent 视频处理状态机", "分支表示真实并行任务，节点状态来自当前 Trace")
    : graphFromTemplates(QA_NODES, QA_EDGES, trace, "视频问答 Agent 状态机", "调查、联网补充、证据验证与修复回路")
}

function runtimeEventStatus(events: TraceEvent[], baseline: MachineStatus): MachineStatus {
  return events.length > 0 ? statusFromEvents(events) : baseline;
}

export function buildRuntimeGraph(
  system: SystemObservability | null,
  trace: TraceEvent[],
): MachineGraph {
  const terminal = trace.findLast((event) => ["workflow.completed", "workflow.failed"].includes(event.event_type));
  const active = trace.length > 0 && !terminal;
  const byId = new Map(system?.runtime_components.map((component) => [component.id, component]) ?? []);
  const baseline = (id: string): MachineStatus => {
    const status = byId.get(id)?.status;
    if (status === "ready") return "ready";
    if (status === "unavailable" || status === "disabled") return "unavailable";
    return "pending";
  };
  const events = (predicate: (event: TraceEvent) => boolean) => trace.filter(predicate);
  const toolEvents = events((event) => event.event_type.startsWith("tool."));
  const memoryEvents = toolEvents.filter((event) => ["search_timeline", "inspect_frame"].includes(event.name));
  const mcpEvents = events((event) => event.event_type.startsWith("mcp."));
  const modelEvents = events((event) => event.event_type.startsWith("model."));
  const visualEvents = events((event) => nodeId(event) === "vlm_understanding_agent");
  const skillEvents = events((event) => event.event_type.startsWith("skill."));
  const ledgerEvents = events((event) => event.event_type === "budget.updated" || event.event_type.startsWith("model."));

  const templates: Array<NodeTemplate & { status: MachineStatus }> = [
    { id: "request", label: "运行输入", category: "input", x: 0, y: 220, summary: "视频任务或用户问题进入系统", status: trace.length ? "completed" : "ready" },
    { id: "harness", label: "Agent Harness", category: "harness", x: 260, y: 220, summary: byId.get("harness")?.summary ?? "执行预算、策略与工具边界", status: trace.length ? (terminal ? "completed" : "running") : baseline("harness") },
    { id: "memory", label: "视频记忆", category: "memory", x: 550, y: 30, summary: byId.get("memory")?.summary ?? "检索时间轴、字幕、章节与帧证据", status: runtimeEventStatus(memoryEvents, baseline("memory")) },
    { id: "tool_registry", label: "工具注册表", category: "tool", x: 550, y: 220, summary: "校验并调度 inspect_frame / search_timeline / search_web", status: runtimeEventStatus(toolEvents, system ? "ready" : "pending") },
    { id: "model_text_reasoning", label: "文本推理模型", category: "model", x: 550, y: 410, summary: byId.get("model_text_reasoning")?.summary ?? "基于证据进行结构化推理", status: runtimeEventStatus(modelEvents, baseline("model_text_reasoning")) },
    { id: "model_visual_understanding", label: "视觉理解模型", category: "model", x: 550, y: 580, summary: byId.get("model_visual_understanding")?.summary ?? "理解具体画面与跨帧语义", status: runtimeEventStatus(visualEvents, baseline("model_visual_understanding")) },
    { id: "skill_runtime", label: "Skill Runtime", category: "skill", x: 850, y: 30, summary: byId.get("skill_runtime")?.summary ?? "按视频垂类装载可复用理解规范", status: runtimeEventStatus(skillEvents, baseline("skill_runtime")) },
    { id: "search_mcp", label: "Search MCP", category: "mcp", x: 850, y: 220, summary: byId.get("search_mcp")?.summary ?? "通过标准协议调用联网搜索", status: runtimeEventStatus(mcpEvents, baseline("search_mcp")) },
    { id: "cost_ledger", label: "成本与预算账本", category: "cost", x: 850, y: 470, summary: "记录模型调用、Token 与人民币成本", status: runtimeEventStatus(ledgerEvents, "ready") },
    { id: "searxng", label: "SearXNG 搜索引擎", category: "search", x: 1140, y: 220, summary: byId.get("searxng")?.summary ?? "聚合公开网络检索结果", status: runtimeEventStatus(mcpEvents, baseline("searxng")) },
    { id: "trace_store", label: "Trace Store", category: "trace", x: 1140, y: 470, summary: byId.get("trace_store")?.summary ?? "持续写入可回放运行事件", status: trace.length ? (active ? "running" : "completed") : baseline("trace_store") },
    { id: "runtime_output", label: "可验证输出", category: "output", x: 1430, y: 220, summary: terminal?.summary ?? "等待工作流生成视频理解或证据化回答", status: terminal ? (terminal.event_type === "workflow.failed" ? "failed" : "completed") : active ? "running" : "pending" },
  ];
  const runtimeEdges: EdgeTemplate[] = [
    { source: "request", target: "harness" },
    { source: "harness", target: "memory" },
    { source: "harness", target: "tool_registry" },
    { source: "harness", target: "model_text_reasoning" },
    { source: "harness", target: "model_visual_understanding" },
    { source: "harness", target: "skill_runtime" },
    { source: "tool_registry", target: "search_mcp" },
    { source: "search_mcp", target: "searxng" },
    { source: "model_text_reasoning", target: "cost_ledger" },
    { source: "model_visual_understanding", target: "cost_ledger" },
    { source: "harness", target: "trace_store" },
    { source: "memory", target: "runtime_output" },
    { source: "searxng", target: "runtime_output" },
    { source: "model_text_reasoning", target: "runtime_output" },
    { source: "model_visual_understanding", target: "runtime_output" },
  ];
  const nodes: MachineNode[] = templates.map((template) => ({
    id: template.id,
    type: "machine",
    position: { x: template.x, y: template.y },
    data: {
      label: template.label,
      category: template.category,
      status: template.status,
      summary: template.summary,
      badge: template.id === "search_mcp" && mcpEvents.length ? `${mcpEvents.length} 个事件` : undefined,
    },
  }));
  return {
    nodes,
    edges: createEdges(runtimeEdges, nodes),
    title: "Agent 运行时状态机",
    description: "Harness、记忆、工具、MCP、模型、成本与 Trace 的真实调用路径",
  };
}
