import type {
  Answer,
  QuestionTarget,
  TimelineArtifact,
  Video,
  ProcessingRun,
  AgentRun,
  SystemObservability,
  TraceEvent,
  UsageSummary,
  Skill,
  SkillDetail,
  SkillProject,
  SkillProjectWorkspace,
} from "@/lib/api/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "未知网络错误";
    throw new ApiError(
      `无法连接视频 Agent 后端，请检查 8000 端口和后端日志（${detail}）`,
      0,
      "network_error",
    );
  }
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as
      | { detail?: unknown; code?: string }
      | null;
    const detail =
      typeof problem?.detail === "string"
        ? problem.detail
        : problem?.detail && typeof problem.detail === "object"
          ? JSON.stringify(problem.detail)
          : `请求失败（HTTP ${response.status}）`;
    throw new ApiError(
      detail,
      response.status,
      problem?.code,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function listVideos(): Promise<Video[]> {
  const data = await request<{ items: Video[] }>("/videos");
  return data.items;
}

export async function getTimeline(videoId: string): Promise<TimelineArtifact[]> {
  const data = await request<{ items: TimelineArtifact[] }>(
    `/videos/${videoId}/timeline`,
  );
  return data.items;
}

export async function askVideo(
  videoId: string,
  query: string,
  target: QuestionTarget,
  useWebSearch = false,
  traceId?: string,
): Promise<Answer> {
  return request<Answer>(`/videos/${videoId}/questions`, {
    method: "POST",
    body: JSON.stringify({
      query,
      target,
      use_web_search: useWebSearch,
      trace_id: traceId,
    }),
  });
}

export async function importVideoUrl(input: {
  url: string;
  title?: string;
  rightsConfirmed: boolean;
}): Promise<Video> {
  return request<Video>("/videos/imports", {
    method: "POST",
    body: JSON.stringify({
      url: input.url,
      title: input.title || null,
      rights_confirmed: input.rightsConfirmed,
    }),
  });
}

export async function uploadVideo(file: File): Promise<Video> {
  const body = new FormData();
  body.append("file", file);
  return request<Video>("/videos/uploads", { method: "POST", body });
}

export async function getVideo(videoId: string): Promise<Video> {
  return request<Video>(`/videos/${videoId}`);
}

export async function getProcessing(videoId: string): Promise<ProcessingRun> {
  return request<ProcessingRun>(`/videos/${videoId}/processing`);
}

export async function startProcessing(videoId: string): Promise<ProcessingRun> {
  return request<ProcessingRun>(`/videos/${videoId}/processing`, { method: "POST" });
}

export async function getAgentTrace(traceId: string): Promise<TraceEvent[]> {
  // 统一 Trace 端点同时支持问答 AgentRun 与上传后的视频处理工作流。
  const data = await request<{ items: TraceEvent[] }>(`/traces/${traceId}`);
  return data.items;
}

export async function getAgentRun(traceId: string): Promise<AgentRun> {
  return request<AgentRun>(`/agent-runs/${traceId}`);
}

export async function getUsageSummary(videoId?: string, traceId?: string): Promise<UsageSummary> {
  const params = new URLSearchParams();
  if (videoId) params.set("video_id", videoId);
  if (traceId) params.set("trace_id", traceId);
  const query = params.size ? `?${params.toString()}` : "";
  return request<UsageSummary>(`/observability/usage${query}`);
}

export async function getSystemObservability(): Promise<SystemObservability> {
  return request<SystemObservability>("/observability/system");
}

export async function listSkills(): Promise<Skill[]> {
  const data = await request<{ items: Skill[] }>("/skills");
  return data.items;
}

export async function deleteSkills(skillIds: string[]): Promise<void> {
  return request<void>("/skills/batch-delete", {
    method: "POST",
    body: JSON.stringify({ skill_ids: skillIds }),
  });
}

export async function listSkillProjects(): Promise<SkillProject[]> {
  const data = await request<{ items: SkillProject[] }>("/skill-projects");
  return data.items;
}

export async function createSkillProject(input: {
  name: string;
  goal: string;
  description?: string;
}): Promise<SkillProjectWorkspace> {
  return request<SkillProjectWorkspace>("/skill-projects", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getSkillProject(projectId: string): Promise<SkillProjectWorkspace> {
  return request<SkillProjectWorkspace>(`/skill-projects/${projectId}`);
}

export async function addSkillProjectVideos(
  projectId: string,
  urls: string[],
): Promise<SkillProjectWorkspace> {
  return request<SkillProjectWorkspace>(`/skill-projects/${projectId}/videos`, {
    method: "POST",
    body: JSON.stringify({ urls, rights_confirmed: true }),
  });
}

export async function retrySkillProjectItem(
  projectId: string,
  itemId: string,
): Promise<SkillProjectWorkspace> {
  return request<SkillProjectWorkspace>(
    `/skill-projects/${projectId}/items/${itemId}/retry`,
    { method: "POST" },
  );
}

export async function attachProjectSkill(
  projectId: string,
  skillId: string,
): Promise<SkillProjectWorkspace> {
  return request<SkillProjectWorkspace>(`/skill-projects/${projectId}/skill`, {
    method: "POST",
    body: JSON.stringify({ skill_id: skillId }),
  });
}

export async function getSkill(skillId: string): Promise<SkillDetail> {
  return request<SkillDetail>(`/skills/${skillId}`);
}

export async function generateSkill(input: {
  videoIds: string[];
  goal: string;
  displayName?: string;
}): Promise<SkillDetail> {
  return request<SkillDetail>("/skills/generate", {
    method: "POST",
    body: JSON.stringify({
      video_ids: input.videoIds,
      goal: input.goal,
      display_name: input.displayName || null,
    }),
  });
}

export async function regenerateSkill(
  skillId: string,
  videoIds: string[],
  goal?: string,
): Promise<SkillDetail> {
  return request<SkillDetail>(`/skills/${skillId}/regenerate`, {
    method: "POST",
    body: JSON.stringify({ video_ids: videoIds, goal: goal || null }),
  });
}

export async function refineSkill(
  skillId: string,
  instruction: string,
  baseVersion?: number,
): Promise<SkillDetail> {
  return request<SkillDetail>(`/skills/${skillId}/refine`, {
    method: "POST",
    body: JSON.stringify({ instruction, base_version: baseVersion ?? null }),
  });
}

export async function publishSkill(skillId: string, version: number): Promise<SkillDetail> {
  return request<SkillDetail>(`/skills/${skillId}/versions/${version}/publish`, {
    method: "POST",
  });
}

export async function rollbackSkill(skillId: string, version: number): Promise<SkillDetail> {
  return request<SkillDetail>(`/skills/${skillId}/rollback`, {
    method: "POST",
    body: JSON.stringify({ version }),
  });
}

export async function bindSkill(skillId: string, videoIds: string[]): Promise<SkillDetail> {
  return request<SkillDetail>(`/skills/${skillId}/bindings`, {
    method: "POST",
    body: JSON.stringify({ video_ids: videoIds }),
  });
}

export function resolveAssetUrl(url: string | null): string | null {
  if (!url) return null;
  if (/^https?:\/\//.test(url)) return url;
  const apiUrl = new URL(API_BASE);
  return `${apiUrl.origin}${url.startsWith("/") ? "" : "/"}${url}`;
}

export function getVideoMediaUrl(videoId: string): string {
  return `${API_BASE}/videos/${videoId}/media`;
}

export function getFrameAtUrl(videoId: string, timestampMs: number): string {
  return `${API_BASE}/videos/${videoId}/frame-at/${Math.max(0, Math.round(timestampMs))}.jpg`;
}

export function getTimelineSnapshotUrl(
  videoId: string,
  snapshotKey: string | null,
): string | null {
  if (!snapshotKey?.startsWith("frames/")) return null;
  const filename = snapshotKey.split("/").at(-1);
  return filename ? `${API_BASE}/videos/${videoId}/frames/${filename}` : null;
}
