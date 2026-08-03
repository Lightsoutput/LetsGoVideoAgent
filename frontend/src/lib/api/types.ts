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
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  stage_label: string;
  progress: number;
  elapsed_seconds: number;
  eta_seconds: number | null;
  message: string;
  error: string | null;
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
  trace_id: string;
  usage: ModelUsage;
  created_at: string;
}
