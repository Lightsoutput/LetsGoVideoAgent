"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  addSkillProjectVideos,
  attachProjectSkill,
  createSkillProject,
  deleteSkills,
  generateSkill,
  getSkill,
  getSkillProject,
  listSkillProjects,
  listSkills,
  publishSkill,
  refineSkill,
  retrySkillProjectItem,
} from "@/lib/api/client";
import { API_BASE } from "@/lib/api/client";
import type {
  Skill,
  SkillDetail,
  SkillProject,
  SkillProjectItem,
  SkillProjectWorkspace,
  SkillVersion,
  Video,
} from "@/lib/api/types";
import { agentLabel } from "@/features/observability/agentCatalog";

interface Props {
  currentVideoId: string | null;
  onClose: () => void;
  onOpenTrace: (traceId: string) => void;
  open: boolean;
  videos: Video[];
}

const STATUS_TEXT = {
  active: "待添加样本",
  processing: "团队工作中",
  ready: "样本已就绪",
  attention: "需要处理",
  queued: "等待分配",
  importing: "正在导入",
  failed: "处理失败",
} as const;

function projectStatusText(status: string) {
  return STATUS_TEXT[status as keyof typeof STATUS_TEXT] ?? status;
}

function compactAgentName(agentId: string | null) {
  return agentLabel(agentId);
}

function formatTimestamp(timestampMs: number) {
  const seconds = Math.max(0, Math.floor(timestampMs / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function ProjectItemCard({
  item,
  onOpenTrace,
  onRetry,
}: {
  item: SkillProjectItem;
  onOpenTrace: (traceId: string) => void;
  onRetry: (itemId: string) => void;
}) {
  return (
    <article className={`project-video-card ${item.status}`}>
      <div className="project-video-head">
        <span className="project-video-state">{projectStatusText(item.status)}</span>
        <strong>{Math.round(item.progress * 100)}%</strong>
      </div>
      <h4>{item.title}</h4>
      <p>{item.message}</p>
      {item.status === "ready" && item.insight && (
        <div className="project-video-result">
          <div className="project-video-tags">
            <span>{item.insight.video_format}</span>
            {item.insight.themes.slice(0, 2).map((theme) => <span key={theme}>{theme}</span>)}
          </div>
          <p className="project-video-summary">{item.insight.summary || item.insight.purpose || "已有结构化结果，尚缺少总体总结。"}</p>
          <details>
            <summary>理解结果 · {item.insight.chapters.length} 章 · {item.insight.representative_frames.length} 个代表画面</summary>
            {item.insight.purpose && <p><strong>内容目的：</strong>{item.insight.purpose}</p>}
            <ol className="project-chapter-preview">
              {item.insight.chapters.slice(0, 8).map((chapter) => (
                <li key={`${chapter.start_ms}-${chapter.title}`}>
                  <time>{formatTimestamp(chapter.start_ms)}</time>
                  <span><strong>{chapter.title}</strong><small>{chapter.summary}</small></span>
                </li>
              ))}
            </ol>
            <div className="project-frame-preview">
              {item.insight.representative_frames.slice(0, 4).map((frame) => (
                <article key={`${frame.timestamp_ms}-${frame.title}`}>
                  {frame.snapshot_filename && item.video_id && (
                    <img alt={frame.title} src={`${API_BASE}/videos/${item.video_id}/frames/${frame.snapshot_filename}`} />
                  )}
                  <span><time>{formatTimestamp(frame.timestamp_ms)}</time><strong>{frame.title}</strong></span>
                </article>
              ))}
            </div>
          </details>
        </div>
      )}
      <div className="project-progress" aria-label={`${item.title} 处理进度`}>
        <span style={{ width: `${Math.max(2, item.progress * 100)}%` }} />
      </div>
      <footer>
        <span>{compactAgentName(item.current_agent)} · {item.stage_label}</span>
        {item.trace_id && (
          <button onClick={() => onOpenTrace(item.trace_id as string)} type="button">日志</button>
        )}
        {item.status === "failed" && (
          <button onClick={() => onRetry(item.id)} type="button">重试</button>
        )}
      </footer>
      {item.agent_tasks.some((task) => task.status === "running") && (
        <div className="project-active-agents">
          {item.agent_tasks.filter((task) => task.status === "running").map((task) => (
            <div key={task.agent_id}>
              <span><b>{task.agent_number} {task.display_name}</b>{task.model ? `${task.model_provider} / ${task.model}` : "本地处理"}</span>
              <small>{task.message}</small>
              <progress max={1} value={task.progress} />
            </div>
          ))}
        </div>
      )}
    </article>
  );
}


function SkillReview({
  detail,
  version,
  instruction,
  busy,
  attached,
  onInstruction,
  onPublish,
  onRefine,
  onTrace,
}: {
  detail: SkillDetail;
  version: SkillVersion;
  instruction: string;
  busy: boolean;
  attached: boolean;
  onInstruction: (value: string) => void;
  onPublish: () => void;
  onRefine: () => void;
  onTrace: () => void;
}) {
  const essenceDimensions = (() => {
    const claimed = new Set<string>();
    const takeDistinct = (items: string[]) => items.filter((item) => {
      const normalized = item.trim();
      if (!normalized || claimed.has(normalized)) return false;
      claimed.add(normalized);
      return true;
    });
    return [
      ["01", "内容内核", takeDistinct(version.content.category_essence.content_core)],
      ["02", "画面表达", takeDistinct(version.content.category_essence.visual_signature)],
      ["03", "文案与口播", takeDistinct(version.content.category_essence.narration_copywriting)],
      ["04", "叙事与节奏", takeDistinct([
        ...version.content.category_essence.storytelling_engine,
        ...version.content.category_essence.pacing_editing,
      ])],
    ] as const;
  })();

  return (
    <div className="project-skill-review">
      <div className="project-skill-title">
        <span className={`skill-status ${version.status}`}>{version.status === "published" ? "已发布" : "待审核"}</span>
        <h3>{detail.skill.display_name}</h3>
        <p>{detail.skill.description}</p>
      </div>
      <div className="project-skill-facts">
        <span className={version.content.category_essence.extraction_status === "sample-derived" ? "essence-ready" : "essence-insufficient"}>
          {version.content.category_essence.extraction_status === "sample-derived" ? "样本证据已提炼" : "样本提炼不足"}
        </span>
        <span>{version.content.objectives.length} 项理解目标</span>
        <span>{version.content.segmentation_hints.length} 条分段规则</span>
        <span>{version.content.terminology.length} 个领域术语</span>
      </div>
      <div className={`skill-validation ${version.validation.valid ? "valid" : "invalid"}`}>
        <strong>{version.validation.valid ? "安全与结构检查通过" : "存在阻止发布的问题"}</strong>
        {version.validation.errors.map((item) => <p key={item}>{item}</p>)}
      </div>
      <section className="skill-essence-panel">
        <small>从样本真正学到的内容</small>
        <h4>{version.content.category_essence.one_sentence_essence || "尚未形成可验证的类别精髓"}</h4>
        <div className="skill-essence-grid">
          {essenceDimensions.map(([number, label, items]) => (
            <div key={number}>
              <strong><span>{number}</span>{label}</strong>
              {items.length > 0
                ? <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
                : <p className="skill-dimension-empty">该维度尚未形成独立结论</p>}
            </div>
          ))}
        </div>
        <details>
          <summary>查看 {version.content.category_essence.evidence.length} 条样本依据</summary>
          {version.content.category_essence.evidence.map((evidence) => (
            <article className="skill-evidence-card" key={evidence.insight}>
              <strong>{evidence.insight}</strong>
              <small>{evidence.supporting_video_ids.length} 个样本支持</small>
              <ul>{evidence.observations.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
          ))}
        </details>
      </section>
      <details>
        <summary>通用运行规则与模型装载位置</summary>
        <p className="skill-layer-note">这里规定 Agent 怎样使用上述类别知识，不是对样本内容的总结。</p>
        <h4>辅助类别画像</h4>
        <p><strong>{version.content.category_profile.category_name}</strong> · {version.content.category_profile.style_summary}</p>
        <ul>{version.content.category_profile.narrative_patterns.map((item) => <li key={item}>{item}</li>)}</ul>
        <h4>装给哪些模型</h4>
        {version.content.runtime_targets.map((target) => (
          <div className="skill-runtime-target" key={target.target_id}>
            <strong>{target.target_name}</strong><code>{target.provider} / {target.model}</code>
            <small>{target.stages.join(" · ")}</small>
            <ul>{target.instructions.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        ))}
        <h4>理解目标</h4>
        <ul>{version.content.objectives.map((item) => <li key={item}>{item}</li>)}</ul>
        <h4>分段方法</h4>
        <ul>{version.content.segmentation_hints.map((item) => <li key={item}>{item}</li>)}</ul>
        <h4>视觉关注</h4>
        <ul>{version.content.visual_focus.map((item) => <li key={item}>{item}</li>)}</ul>
        <h4>预设问题与答案结构</h4>
        <ul>{version.content.default_questions.map((item) => <li key={item.question}><strong>{item.question}</strong>：{item.answer_structure.join(" / ")}</li>)}</ul>
        <h4>格式化输出</h4>
        <ul>{version.content.output_templates.map((item) => <li key={item.name}><strong>{item.name}</strong>：{item.fields.join(" / ")}</li>)}</ul>
      </details>
      {version.status === "draft" && (
        <>
          <textarea
            onChange={(event) => onInstruction(event.target.value)}
            placeholder="告诉小策哪里还需要改进……"
            rows={3}
            value={instruction}
          />
          <div className="project-skill-actions">
            <button className="secondary-button skill-refine-button" disabled={busy || instruction.trim().length < 2} onClick={onRefine} type="button">继续修改 · 生成 v{Math.max(...detail.versions.map((item) => item.version)) + 1}</button>
            <button className="primary-button" disabled={busy || !version.validation.valid} onClick={onPublish} type="button">审核通过并发布</button>
          </div>
        </>
      )}
      {version.status === "published" && <p className="project-skill-attached">{attached ? "✓ 已用于这个项目" : "发布后将自动用于这个项目"}</p>}
      <button className="text-button" onClick={onTrace} type="button">查看生成记录</button>
    </div>
  );
}

export function SkillStudio({ onClose, onOpenTrace, open }: Props) {
  const [projects, setProjects] = useState<SkillProject[]>([]);
  const [workspace, setWorkspace] = useState<SkillProjectWorkspace | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectGoal, setProjectGoal] = useState("理解这一类视频的叙事逻辑、画面意义、专有名词和稳定分段方式");
  const [urls, setUrls] = useState("");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedSampleIds, setSelectedSampleIds] = useState<string[]>([]);
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);

  const version = detail?.versions.find((item) => item.version === previewVersion) ?? detail?.versions[0] ?? null;
  const readyItems = workspace?.items.filter((item) => item.status === "ready" && item.video_id) ?? [];
  const orderedSkills = useMemo(
    // 保持编号与创建顺序绑定；新增 Skill 不会让旧编号整体漂移。
    () => [...skills].sort((left, right) => left.created_at.localeCompare(right.created_at)),
    [skills],
  );
  const lanes = useMemo(() => ({
    intake: workspace?.items.filter((item) => ["queued", "importing"].includes(item.status)) ?? [],
    working: workspace?.items.filter((item) => item.status === "processing") ?? [],
    complete: workspace?.items.filter((item) => ["ready", "failed"].includes(item.status)) ?? [],
  }), [workspace]);

  function toggleSample(videoId: string) {
    setSelectedSampleIds((current) => {
      if (current.includes(videoId)) return current.filter((id) => id !== videoId);
      if (current.length >= 8) return current;
      return [...current, videoId];
    });
  }

  function selectAllSamples() {
    setSelectedSampleIds(readyItems.slice(0, 8).map((item) => item.video_id as string));
  }

  function clearSelectedSamples() {
    setSelectedSampleIds([]);
  }

  function toggleSkillSelection(skillId: string) {
    setSelectedSkillIds((current) => current.includes(skillId)
      ? current.filter((id) => id !== skillId)
      : [...current, skillId]);
  }

  async function openSkill(skillId: string) {
    try {
      const next = await getSkill(skillId);
      setDetail(next);
      setPreviewVersion(next.versions[0]?.version ?? null);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Skill 加载失败");
    }
  }

  const refreshProject = useCallback(async (projectId: string, loadAttachedSkill = false) => {
    const next = await getSkillProject(projectId);
    setWorkspace(next);
    if (loadAttachedSkill && next.project.skill_id) {
      const attached = await getSkill(next.project.skill_id);
      setDetail(attached);
      setPreviewVersion(attached.versions[0]?.version ?? null);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void Promise.all([listSkillProjects(), listSkills()]).then(([nextProjects, nextSkills]) => {
      setProjects(nextProjects);
      setSkills(nextSkills);
      if (!workspace && nextProjects[0]) void refreshProject(nextProjects[0].id, true);
    }).catch((reason: unknown) => setMessage(reason instanceof Error ? reason.message : "工作区加载失败"));
  }, [open, refreshProject, workspace]);

  useEffect(() => {
    if (!open || !workspace) return;
    const timer = window.setInterval(() => {
      void refreshProject(workspace.project.id).catch(() => undefined);
    }, workspace.project.status === "processing" ? 1_500 : 5_000);
    return () => window.clearInterval(timer);
  }, [open, refreshProject, workspace]);

  useEffect(() => {
    if (!open || !detail) return;
    document
      .querySelector(`[data-skill-id="${detail.skill.id}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [detail, open]);

  async function createProject() {
    if (projectName.trim().length < 1 || projectGoal.trim().length < 4) return;
    setBusy(true);
    try {
      const next = await createSkillProject({ name: projectName.trim(), goal: projectGoal.trim() });
      setWorkspace(next);
      setProjects(await listSkillProjects());
      setShowCreate(false);
      setProjectName("");
      setDetail(null);
      setMessage("项目已创建，可以一次粘贴多条同类视频链接。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "项目创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function selectProject(projectId: string) {
    setDetail(null);
    setPreviewVersion(null);
    setInstruction("");
    setSelectedSampleIds([]);
    await refreshProject(projectId, true);
  }

  async function importUrls() {
    if (!workspace) return;
    const values = [...new Set(urls.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))];
    if (values.length === 0) return;
    setBusy(true);
    setMessage(`正在把 ${values.length} 条视频分配给 Agent 团队…`);
    try {
      setWorkspace(await addSkillProjectVideos(workspace.project.id, values));
      setUrls("");
      setProjects(await listSkillProjects());
      setMessage("视频已进入并行流水线；下方工位和日志会持续更新。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "批量导入失败");
    } finally {
      setBusy(false);
    }
  }

  async function buildProjectSkill() {
    if (!workspace || selectedSampleIds.length === 0) return;
    setBusy(true);
    setMessage("小策正在比较样本共性并整理可审核规则…");
    try {
      const next = await generateSkill({
        videoIds: selectedSampleIds.slice(0, 8),
        goal: workspace.project.goal,
        displayName: `${workspace.project.name}理解`,
      });
      setDetail(next);
      setPreviewVersion(next.versions[0]?.version ?? null);
      const refreshedSkills = await listSkills();
      setSkills(refreshedSkills);
      setMessage("新的 Skill 草案已经形成并自动打开；它与左侧已有 Skill 相互独立。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Skill 生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function refineProjectSkill() {
    if (!detail || !version || instruction.trim().length < 2) return;
    setBusy(true);
    try {
      const next = await refineSkill(detail.skill.id, instruction, version.version);
      setDetail(next);
      setPreviewVersion(next.versions[0]?.version ?? null);
      setInstruction("");
      setMessage("小策已生成新草案，之前的版本仍然保留。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "修改失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeSkills(skillIds: string[]) {
    if (!workspace || skillIds.length === 0) return;
    const names = skills.filter((skill) => skillIds.includes(skill.id)).map((skill) => skill.display_name);
    const label = skillIds.length === 1 ? `“${names[0] ?? "这个 Skill"}”` : `选中的 ${skillIds.length} 个 Skill`;
    if (!window.confirm(`确定永久删除${label}吗？其全部版本、绑定和已发布脚本都会一并删除，无法撤销。`)) return;
    setBusy(true);
    setMessage(`正在删除${label}…`);
    try {
      await deleteSkills(skillIds);
      const remaining = await listSkills();
      setSkills(remaining);
      setSelectedSkillIds((current) => current.filter((id) => !skillIds.includes(id)));
      if (detail && skillIds.includes(detail.skill.id)) {
        const nextSkill = remaining[0];
        if (nextSkill) await openSkill(nextSkill.id);
        else {
          setDetail(null);
          setPreviewVersion(null);
        }
      }
      await refreshProject(workspace.project.id);
      setMessage(`${label}已删除。`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Skill 删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function publishProjectSkill() {
    if (!workspace || !detail || !version) return;
    setBusy(true);
    try {
      const next = await publishSkill(detail.skill.id, version.version);
      setDetail(next);
      setPreviewVersion(next.versions[0]?.version ?? null);
      setWorkspace(await attachProjectSkill(workspace.project.id, detail.skill.id));
      setProjects(await listSkillProjects());
      setMessage("Skill 已发布并关联项目；项目仍可继续积累新样本与新版本。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "发布失败");
    } finally {
      setBusy(false);
    }
  }

  async function retryItem(itemId: string) {
    if (!workspace) return;
    setWorkspace(await retrySkillProjectItem(workspace.project.id, itemId));
  }

  if (!open) return null;
  return (
    <section className="skill-studio skill-project-studio" aria-label="Skill Studio">
      <aside className="skill-project-rail">
        <button className="skill-back-button" onClick={onClose} type="button">← 返回视频工作台</button>
        <div className="skill-panel-title"><div><small>DOMAIN WORKSPACE</small><h2>Skill Studio</h2></div></div>
        <p className="skill-lead">按视频类型建立项目，让样本、Agent 运行和 Skill 版本长期沉淀。</p>
        <button className="skill-new" onClick={() => setShowCreate((value) => !value)} type="button">＋ 新建垂类项目</button>
        {showCreate && (
          <div className="project-create-popover">
            <label>项目名称<input onChange={(event) => setProjectName(event.target.value)} placeholder="例如：Zc故事" value={projectName} /></label>
            <label>希望 Agent 学会什么<textarea onChange={(event) => setProjectGoal(event.target.value)} rows={4} value={projectGoal} /></label>
            <button className="primary-button" disabled={busy} onClick={() => void createProject()} type="button">创建项目</button>
          </div>
        )}
        <nav className="skill-project-list" aria-label="垂类项目">
          {projects.map((project) => (
            <button className={workspace?.project.id === project.id ? "active" : ""} key={project.id} onClick={() => void selectProject(project.id)} type="button">
              <span className={`project-icon ${project.status}`}>{project.name.slice(0, 1).toUpperCase()}</span>
              <span><strong>{project.name}</strong><small>{projectStatusText(project.status)}</small></span>
              {project.status === "processing" && <i />}
            </button>
          ))}
          {projects.length === 0 && <p className="skill-empty">先创建一个项目，例如“Zc故事”。</p>}
        </nav>
      </aside>

      <main className="skill-project-main">
        {!workspace ? (
          <div className="project-welcome"><span>🧭</span><h1>为一类视频建立长期工作区</h1><p>批量加入样本，观察 Agent 团队处理，再把共性沉淀为可审核 Skill。</p><button className="primary-button" onClick={() => setShowCreate(true)} type="button">创建第一个项目</button></div>
        ) : (
          <>
            <header className="project-header">
              <div><small>垂类视频项目</small><h1>{workspace.project.name}</h1><p>{workspace.project.goal}</p></div>
              <div className={`project-live-status ${workspace.project.status}`}><i /><span>{projectStatusText(workspace.project.status)}</span><strong>{workspace.items.length} 条视频</strong></div>
            </header>

            <section className="workflow-step-card project-import-section">
              <div className="project-section-title workflow-step-head">
                <div><small>01 · SAMPLE INTAKE</small><h2>添加同类视频样本</h2></div>
                <span>每行一个链接 · 已存在的视频直接复用</span>
              </div>
              <div className="project-import-controls workflow-step-body">
                <textarea onChange={(event) => setUrls(event.target.value)} placeholder={"https://www.bilibili.com/video/BV...\nhttps://www.bilibili.com/video/BV..."} rows={3} value={urls} />
                <button className="primary-button" disabled={busy || urls.trim().length === 0} onClick={() => void importUrls()} type="button">加入处理流水线</button>
              </div>
            </section>

            <section className="workflow-step-card project-pipeline-section">
              <div className="project-section-title workflow-step-head"><div><small>02 · VIDEO PIPELINE</small><h2>处理并检查样本</h2></div><span>自动刷新 · 详细 Agent 与成本请在运行观测查看</span></div>
              <div className="project-pipeline workflow-step-body">
                {([
                  ["intake", "待接入", lanes.intake],
                  ["working", "理解中", lanes.working],
                  ["complete", "样本库", lanes.complete],
                ] as const).filter(([, , items]) => items.length > 0).map(([id, label, items]) => (
                  <div className={`pipeline-lane ${id}`} key={id}>
                    <header><span>{label}</span><strong>{items.length}</strong></header>
                    <div>{items.map((item) => <ProjectItemCard item={item} key={item.id} onOpenTrace={onOpenTrace} onRetry={(itemId) => void retryItem(itemId)} />)}</div>
                  </div>
                ))}
              </div>
            </section>

            <section className="workflow-step-card skill-workbench">
              <div className="skill-workbench-head workflow-step-head">
                <div><small>03 · SKILL WORKBENCH</small><h2>选择样本、生成并审核 Skill</h2></div>
                <span>{skills.length} 个 Skill · {detail?.versions.length ?? 0} 个版本</span>
              </div>
              <div className="skill-generation-bar">
                <div className="skill-generation-summary"><strong>{selectedSampleIds.length}</strong><span>已选 / {readyItems.length} 条可用</span></div>
                <div className="skill-generation-samples">
                  <div className="sample-picker-actions"><button className="secondary-button sample-select-button" onClick={selectAllSamples} type="button">选择前 8 条</button><button className="sample-clear-button" onClick={clearSelectedSamples} type="button">清空选择</button></div>
                  <div>{readyItems.map((item, index) => {
                    const videoId = item.video_id as string;
                    const checked = selectedSampleIds.includes(videoId);
                    return <label className={`project-sample-option ${checked ? "selected" : ""}`} key={item.id}>
                      <input checked={checked} disabled={!checked && selectedSampleIds.length >= 8} onChange={() => toggleSample(videoId)} type="checkbox" />
                      <b>{String(index + 1).padStart(2, "0")}</b>
                      <span><strong>{item.title || "未命名视频"}</strong></span>
                    </label>;
                  })}</div>
                </div>
                <button className="primary-button create-independent-skill" disabled={busy || selectedSampleIds.length === 0} onClick={() => void buildProjectSkill()} type="button">{busy ? "正在提炼…" : "生成新的 Skill 草案"}</button>
              </div>
              <div className="skill-workbench-body">
                <aside className="project-skill-library">
                  <header>
                    <div className="skill-library-title"><strong>独立 Skill</strong><small>编号按创建顺序保持稳定</small></div>
                    <div className="skill-library-toolbar">
                      <button disabled={orderedSkills.length === 0} onClick={() => setSelectedSkillIds(orderedSkills.map((skill) => skill.id))} type="button">全选</button>
                      {selectedSkillIds.length > 0 && <button onClick={() => setSelectedSkillIds([])} type="button">取消</button>}
                      {selectedSkillIds.length > 0 && <button className="skill-batch-delete" disabled={busy} onClick={() => void removeSkills(selectedSkillIds)} type="button">删除（{selectedSkillIds.length}）</button>}
                    </div>
                  </header>
                  <div>
                    {orderedSkills.map((skill, index) => (
                      <div className={`skill-library-row ${detail?.skill.id === skill.id ? "active" : ""}`} data-skill-id={skill.id} key={skill.id}>
                        <input aria-label={`选择 ${skill.display_name}`} checked={selectedSkillIds.includes(skill.id)} onChange={() => toggleSkillSelection(skill.id)} type="checkbox" />
                        <button className="skill-library-open" onClick={() => void openSkill(skill.id)} type="button">
                          <b>{String(index + 1).padStart(2, "0")}</b>
                          <span><strong>{skill.display_name}</strong><small>{skill.status === "published" ? `已发布 · v${skill.active_version}` : "独立草案 · 点击预览"}</small></span>
                        </button>
                        <button aria-label={`删除 ${skill.display_name}`} className="skill-library-delete" disabled={busy} onClick={() => void removeSkills([skill.id])} title="删除这个 Skill" type="button">×</button>
                      </div>
                    ))}
                    {orderedSkills.length === 0 && <p className="skill-empty">选择上方样本后生成第一个 Skill。</p>}
                  </div>
                </aside>
                <div className="skill-workbench-preview">
                  {detail && version ? (
                    <>
                      <div className="skill-version-strip">
                        <div><small>当前 Skill · 下方修改会新增内部版本</small><strong>{detail.skill.display_name}</strong></div>
                        <div>{detail.versions.map((item) => <button className={item.version === version.version ? "active" : ""} key={item.version} onClick={() => setPreviewVersion(item.version)} type="button">v{item.version}</button>)}</div>
                      </div>
                      <SkillReview attached={workspace.project.skill_id === detail.skill.id} busy={busy} detail={detail} instruction={instruction} onInstruction={setInstruction} onPublish={() => void publishProjectSkill()} onRefine={() => void refineProjectSkill()} onTrace={() => onOpenTrace(version.trace_id)} version={version} />
                    </>
                  ) : <div className="skill-preview-empty"><span>◇</span><h3>还没有选择 Skill</h3><p>生成后，类别精髓、版本差异和发布操作会集中显示在这里。</p></div>}
                </div>
              </div>
            </section>
          </>
        )}
      </main>

      {message && <p className="skill-message skill-project-toast" aria-live="polite">{message}</p>}
    </section>
  );
}
