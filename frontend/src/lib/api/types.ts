export type VideoStatus =
  | "created"
  | "importing"
  | "validating"
  | "processing"
  | "partially_ready"
  | "ready"
  | "failed"
  | "cancelled";

export type VideoSource =
  | {
      kind: "upload";
      original_filename: string;
      content_type: string;
      size_bytes: number;
      sha256: string | null;
    }
  | {
      kind: "web";
      original_url: string;
      canonical_url: string | null;
      extractor: string | null;
      rights_confirmed: boolean;
    }
  | {
      kind: "synthetic";
      fixture_name: string;
    };

export interface Video {
  id: string;
  title: string;
  source: VideoSource;
  status: VideoStatus;
  duration_ms: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  source_object_key: string | null;
  progress: number;
  current_stage: string | null;
  error_code: string | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProcessingRun {
  id: string;
  video_id: string;
  trace_id: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  stage_label: string;
  progress: number;
  elapsed_seconds: number;
  eta_seconds: number | null;
  message: string;
  error: string | null;
  attempt_count: number;
  agent_tasks: ProcessingAgentTask[];
}

export interface ProcessingAgentTask {
  agent_id: string;
  agent_number: string;
  display_name: string;
  role: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  phase: string;
  task: string;
  message: string;
  progress: number;
  completed_units: number;
  total_units: number | null;
  model_provider: string | null;
  model: string | null;
  parallel_group: string | null;
  started_at: string | null;
  updated_at: string;
  finished_at: string | null;
}

export type TimelineKind =
  | "chapter"
  | "segment"
  | "transcript"
  | "speaker_turn"
  | "ocr"
  | "visual"
  | "event"
  | "shot"
  | "keyframe";

export interface TimeRange {
  start_ms: number;
  end_ms: number;
}

export interface TimelineArtifact {
  id: string;
  video_id: string;
  kind: TimelineKind;
  time_range: TimeRange;
  title: string | null;
  text: string;
  speaker: string | null;
  confidence: number;
  observation_type: "direct" | "inference" | "user_annotation";
  snapshot_key: string | null;
  tags: string[];
}

export type QuestionTarget =
  | { kind: "global" }
  | { kind: "range"; time_range: TimeRange }
  | { kind: "moment"; timestamp_ms: number; context_window_ms: number }
  | { kind: "frame"; timestamp_ms: number };

export interface Evidence {
  id: string;
  video_id: string;
  kind: "transcript" | "visual" | "ocr" | "audio" | "timeline" | "frame";
  time_range: TimeRange | null;
  timestamp_ms: number | null;
  quote: string | null;
  description: string;
  confidence: number;
  snapshot_url: string | null;
}

export interface EvidenceCitation {
  evidence_id: string;
  timestamp_ms: number;
  label: string;
  snapshot_url: string | null;
}

export interface ModelUsage {
  model_calls: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: string;
  elapsed_ms: number;
}

export interface Answer {
  id: string;
  question_id: string;
  status: "answered" | "partial" | "abstained";
  text: string;
  citations: EvidenceCitation[];
  evidence: Evidence[];
  confidence: number;
  limitations: string[];
  web_search_performed: boolean;
  web_sources: Array<{
    title: string;
    url: string;
    content: string;
  }>;
  trace_id: string;
  usage: ModelUsage;
  skill_id: string | null;
  skill_version: number | null;
  skill_name: string | null;
  created_at: string;
}

export interface SkillTerm {
  term: string;
  meaning: string;
  aliases: string[];
  verification: string;
}

export interface SkillContent {
  applicable_video_types: string[];
  category_essence: {
    extraction_status: "sample-derived" | "insufficient";
    one_sentence_essence: string;
    content_core: string[];
    visual_signature: string[];
    narration_copywriting: string[];
    storytelling_engine: string[];
    pacing_editing: string[];
    recurring_devices: string[];
    viewer_value: string[];
    evidence: Array<{
      insight: string;
      supporting_video_ids: string[];
      observations: string[];
    }>;
    confidence_notes: string[];
  };
  category_profile: {
    category_name: string;
    style_summary: string;
    common_formats: string[];
    typical_content: string[];
    narrative_patterns: string[];
    visual_language: string[];
    audience_expectations: string[];
    stable_signals: string[];
    variable_signals: string[];
  };
  runtime_targets: Array<{
    target_id: string;
    target_name: string;
    provider: string;
    model: string;
    stages: string[];
    instructions: string[];
  }>;
  objectives: string[];
  terminology: SkillTerm[];
  segmentation_hints: string[];
  visual_focus: string[];
  qa_strategy: string[];
  output_requirements: string[];
  allowed_agents: string[];
  allowed_tools: string[];
  allowed_mcps: string[];
  model_guidance: string;
  positive_examples: string[];
  negative_examples: string[];
  boundary_conditions: string[];
  known_limitations: string[];
  default_questions: Array<{ question: string; purpose: string; answer_structure: string[] }>;
  output_templates: Array<{ name: string; use_when: string; fields: string[] }>;
}

export interface SkillValidation {
  valid: boolean;
  errors: string[];
  warnings: string[];
  checked_at: string;
}

export interface Skill {
  id: string;
  slug: string;
  display_name: string;
  description: string;
  author: string;
  status: "draft" | "published" | "retired";
  active_version: number | null;
  created_at: string;
  updated_at: string;
}

export interface SkillVersion {
  id: string;
  skill_id: string;
  version: number;
  status: "draft" | "published" | "retired";
  content: SkillContent;
  sample_video_ids: string[];
  user_goal: string;
  generation_basis: string[];
  validation: SkillValidation;
  trace_id: string;
  parent_version: number | null;
  change_summary: string;
  artifact_path: string | null;
  created_at: string;
  published_at: string | null;
}

export interface SkillDetail {
  skill: Skill;
  versions: SkillVersion[];
  bound_video_ids: string[];
}

export interface SkillProject {
  id: string;
  name: string;
  description: string;
  goal: string;
  status: "active" | "processing" | "ready" | "attention";
  skill_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface SkillProjectItem {
  id: string;
  project_id: string;
  source_url: string;
  video_id: string | null;
  title: string;
  status: "queued" | "importing" | "processing" | "ready" | "failed";
  trace_id: string | null;
  stage: string;
  stage_label: string;
  progress: number;
  current_agent: string | null;
  message: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  agent_tasks: ProcessingAgentTask[];
  insight: {
    video_format: string;
    purpose: string;
    summary: string;
    themes: string[];
    chapters: Array<{
      title: string;
      summary: string;
      start_ms: number;
      end_ms: number;
    }>;
    representative_frames: Array<{
      title: string;
      description: string;
      timestamp_ms: number;
      snapshot_filename: string | null;
    }>;
  } | null;
}

export interface SkillProjectAgent {
  id: string;
  display_name: string;
  role: string;
  avatar: string;
  status: "idle" | "working" | "attention";
  video_id: string | null;
  video_title: string | null;
  task: string;
  progress: number;
  trace_id: string | null;
  active_tasks: number;
  message: string;
  completed_units: number;
  total_units: number | null;
  model_provider: string | null;
  model: string | null;
  assignments: Array<{
    video_id: string;
    video_title: string;
    trace_id: string | null;
    task: string;
    message: string;
    progress: number;
    completed_units: number;
    total_units: number | null;
  }>;
}

export interface SkillProjectWorkspace {
  project: SkillProject;
  items: SkillProjectItem[];
  agents: SkillProjectAgent[];
  recent_logs: TraceEvent[];
  cost_summary: {
    total_cost_cny: string;
    call_count: number;
    input_tokens: number;
    output_tokens: number;
    image_count: number;
    by_model: Record<string, string>;
    by_agent: Record<string, string>;
    by_video: Record<string, string>;
    by_purpose: Record<string, string>;
  };
  model_routes: Array<{
    target: string;
    provider: string;
    model: string;
    agent_id: string;
    agent_display_name: string;
    stages: string[];
    configured: boolean;
  }>;
}

export interface TraceEvent {
  id: string;
  trace_id: string;
  sequence: number;
  event_type:
    | "agent.started"
    | "agent.completed"
    | "agent.failed"
    | "model.requested"
    | "model.completed"
    | "tool.called"
    | "tool.returned"
    | "mcp.called"
    | "mcp.returned"
    | "skill.loaded"
    | "skill.validated"
    | "budget.updated"
    | "human.approved"
    | "human.rejected"
    | "workflow.started"
    | "workflow.completed"
    | "workflow.failed";
  name: string;
  status: string | null;
  summary: string;
  video_id: string | null;
  task_id: string | null;
  agent_id: string | null;
  parent_event_id: string | null;
  attributes: Record<string, unknown>;
  occurred_at: string;
}

export interface UsageEvent {
  id: string;
  provider: string;
  model: string;
  purpose: string;
  input_tokens: number;
  output_tokens: number;
  image_count: number;
  request_count: number;
  original_currency: string;
  original_cost: string;
  cost_cny: string;
  cache_hit: boolean;
  retry: boolean;
  status: string;
  pricing_version: string | null;
  trace_id: string | null;
  task_id: string | null;
  video_id: string | null;
  agent_id: string | null;
  occurred_at: string;
}

export interface UsageSummary {
  items: UsageEvent[];
  call_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_cny: string;
  cost_by_provider: Record<string, string>;
  cost_by_model: Record<string, string>;
}

export interface HarnessPolicy {
  max_steps: number;
  max_model_calls: number;
  max_tool_calls: number;
  max_tokens: number;
  max_cost_usd: string;
  deadline_seconds: number;
  max_repeated_tool_call: number;
  registered_tools: string[];
}

export interface AgentStep {
  index: number;
  kind: string;
  name: string;
  status: string;
  summary: string;
  elapsed_ms: number;
  created_at: string;
}

export interface AgentRun {
  id: string;
  agent_name: string;
  agent_version: string;
  video_id: string;
  conversation_id: string;
  status: string;
  budget: Omit<HarnessPolicy, "registered_tools">;
  usage: ModelUsage;
  steps: AgentStep[];
  stop_reason: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface SystemObservability {
  harness: HarnessPolicy;
  mcp: {
    provider: string;
    status: string;
    endpoint: string | null;
    tools: string[];
  };
  models: Array<{
    capability: string;
    provider: string;
    model: string;
    configured: boolean;
  }>;
  repository: string;
  workflow: string;
  runtime_components: Array<{
    id: string;
    name: string;
    kind: string;
    status: string;
    summary: string;
    endpoint: string | null;
    depends_on: string[];
  }>;
}
