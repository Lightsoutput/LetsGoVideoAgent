"use client";

import { useEffect, useMemo, useState } from "react";

import {
  bindSkill,
  generateSkill,
  getSkill,
  listSkills,
  publishSkill,
  refineSkill,
  rollbackSkill,
} from "@/lib/api/client";
import type { Skill, SkillDetail, SkillVersion, Video } from "@/lib/api/types";

interface Props {
  currentVideoId: string | null;
  onClose: () => void;
  onOpenTrace: (traceId: string) => void;
  open: boolean;
  videos: Video[];
}

function RuleList({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="skill-empty">尚未生成</p>;
  return <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>;
}

export function SkillStudio({ currentVideoId, onClose, onOpenTrace, open, videos }: Props) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [sampleIds, setSampleIds] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("更准确地理解这类视频的结构、画面语义和专业术语");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const version = useMemo(
    () => detail?.versions.find((item) => item.version === selectedVersion)
      ?? detail?.versions[0]
      ?? null,
    [detail, selectedVersion],
  );

  useEffect(() => {
    if (!open) return;
    void listSkills().then((items) => {
      setSkills(items);
      setSampleIds((current) => current.length > 0
        ? current
        : (currentVideoId ? [currentVideoId] : []));
    }).catch((reason: unknown) => {
      setMessage(reason instanceof Error ? reason.message : "Skill 列表加载失败");
    });
  }, [currentVideoId, open]);

  async function selectSkill(skillId: string) {
    setBusy(true);
    setMessage(null);
    try {
      const next = await getSkill(skillId);
      setDetail(next);
      setSelectedVersion(next.versions[0]?.version ?? null);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Skill 加载失败");
    } finally {
      setBusy(false);
    }
  }

  async function createDraft() {
    if (sampleIds.length === 0 || goal.trim().length < 4) return;
    setBusy(true);
    setMessage("样本分析 Agent 正在提炼共性规则…");
    try {
      const next = await generateSkill({ videoIds: sampleIds, goal, displayName: name });
      setDetail(next);
      setSelectedVersion(next.versions[0]?.version ?? null);
      setSkills(await listSkills());
      setMessage("草案已生成。请检查规则与权限，确认后再发布。 ");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Skill 生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function refineDraft() {
    if (!detail || !version || instruction.trim().length < 2) return;
    setBusy(true);
    setMessage("Skill Builder 正在根据你的要求生成新版本…");
    try {
      const next = await refineSkill(detail.skill.id, instruction, version.version);
      setDetail(next);
      setSelectedVersion(next.versions[0]?.version ?? null);
      setInstruction("");
      setMessage("修改已形成新草案，旧版本仍可回滚。 ");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "修改失败");
    } finally {
      setBusy(false);
    }
  }

  async function publishCurrent() {
    if (!detail || !version) return;
    setBusy(true);
    try {
      const next = await publishSkill(detail.skill.id, version.version);
      setDetail(next);
      setSkills(await listSkills());
      setMessage(`v${version.version} 已发布，现在可以绑定视频并注入问答运行时。`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "发布失败");
    } finally {
      setBusy(false);
    }
  }

  async function bindCurrentVideo() {
    if (!detail || !currentVideoId) return;
    setBusy(true);
    try {
      const next = await bindSkill(detail.skill.id, [currentVideoId]);
      setDetail(next);
      setMessage("已绑定当前视频；下一次问答会显示 skill.loaded Trace。 ");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "绑定失败");
    } finally {
      setBusy(false);
    }
  }

  async function rollback(target: SkillVersion) {
    if (!detail) return;
    setBusy(true);
    try {
      const next = await rollbackSkill(detail.skill.id, target.version);
      setDetail(next);
      setMessage(`运行时已回滚到 v${target.version}。`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "回滚失败");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  return (
    <section className="skill-studio" aria-label="Skill Studio">
      <aside className="skill-catalog">
        <button className="skill-back-button" onClick={onClose} type="button">
          ← 返回视频工作台
        </button>
        <div className="skill-panel-title">
          <div><small>DOMAIN SKILL WORKSPACE</small><h2>Skill Studio</h2></div>
        </div>
        <p className="skill-lead">为同类视频建立可审核、可回滚的理解规范。</p>
        <button className="skill-new" onClick={() => { setDetail(null); setName(""); }} type="button">
          ＋ 新建草案
        </button>
        <div className="skill-catalog-list">
          {skills.map((skill) => (
            <button
              className={detail?.skill.id === skill.id ? "active" : ""}
              key={skill.id}
              onClick={() => void selectSkill(skill.id)}
              type="button"
            >
              <strong>{skill.display_name}</strong>
              <span>{skill.status === "published" ? `已发布 v${skill.active_version}` : "草案"}</span>
              <small>{skill.description}</small>
            </button>
          ))}
          {skills.length === 0 && <p className="skill-empty">还没有 Skill，从当前视频开始创建。</p>}
        </div>
      </aside>

      <div className="skill-editor">
        {!detail ? (
          <div className="skill-create-card">
            <small>SAMPLES & GOAL</small>
            <h1>这类视频，Agent 应该怎样理解？</h1>
            <p>可选一个视频快速起步，也可选择多个同类视频，让 Agent 提炼共性而非记住个例。</p>
            <label>Skill 名称（可选）<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：游戏攻略理解" /></label>
            <label>你希望它重点学会什么？<textarea value={goal} onChange={(event) => setGoal(event.target.value)} rows={4} /></label>
            <fieldset>
              <legend>样本视频 · {sampleIds.length}/8</legend>
              <div className="skill-video-grid">
                {videos.map((video) => {
                  const checked = sampleIds.includes(video.id);
                  return <label className={checked ? "selected" : ""} key={video.id}>
                    <input
                      checked={checked}
                      disabled={!checked && sampleIds.length >= 8}
                      onChange={() => setSampleIds((current) => checked
                        ? current.filter((id) => id !== video.id)
                        : [...current, video.id])}
                      type="checkbox"
                    />
                    <span><strong>{video.title}</strong><small>{video.status}</small></span>
                  </label>;
                })}
              </div>
            </fieldset>
            <button className="primary-button" disabled={busy || sampleIds.length === 0} onClick={() => void createDraft()} type="button">
              {busy ? "正在生成…" : "生成可审核草案"}
            </button>
          </div>
        ) : version ? (
          <>
            <header className="skill-editor-header">
              <div><small>{detail.skill.slug}</small><h1>{detail.skill.display_name}</h1><p>{detail.skill.description}</p></div>
              <div className="skill-status-group">
                <span className={`skill-status ${version.status}`}>{version.status === "published" ? "已发布" : "草案"}</span>
                <select value={version.version} onChange={(event) => setSelectedVersion(Number(event.target.value))}>
                  {detail.versions.map((item) => <option key={item.id} value={item.version}>v{item.version} · {item.status}</option>)}
                </select>
              </div>
            </header>
            <div className="skill-rule-grid">
              <article><small>OBJECTIVES</small><h3>理解目标</h3><RuleList items={version.content.objectives} /></article>
              <article><small>SEGMENTATION</small><h3>分段方法</h3><RuleList items={version.content.segmentation_hints} /></article>
              <article><small>VISION</small><h3>画面理解</h3><RuleList items={version.content.visual_focus} /></article>
              <article><small>QA CONTRACT</small><h3>问答与输出</h3><RuleList items={[...version.content.qa_strategy, ...version.content.output_requirements]} /></article>
              <article className="wide"><small>BOUNDARIES</small><h3>边界、反例与限制</h3><RuleList items={[...version.content.boundary_conditions, ...version.content.negative_examples, ...version.content.known_limitations]} /></article>
            </div>
            <section className="skill-conversation">
              <div><small>CONVERSATIONAL EDITING</small><h3>用自然语言继续修改</h3><p>每次修改都会形成新草案，不覆盖当前已发布版本。</p></div>
              <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="例如：章节边界更重视访谈问题的切换，并加强人物称呼的交叉核验。" rows={3} />
              <button disabled={busy || instruction.trim().length < 2} onClick={() => void refineDraft()} type="button">生成新版本</button>
            </section>
          </>
        ) : null}
      </div>

      <aside className="skill-review">
        <small>REVIEW & RUNTIME</small><h2>审核与运行</h2>
        {version ? <>
          <div className={`skill-validation ${version.validation.valid ? "valid" : "invalid"}`}>
            <strong>{version.validation.valid ? "静态检查通过" : "存在阻止发布的问题"}</strong>
            <RuleList items={version.validation.errors} />
            <RuleList items={version.validation.warnings} />
          </div>
          <div className="skill-permissions">
            <h3>权限契约</h3>
            <p>Skill 只能缩小 Harness 权限。</p>
            <label>Agents</label><div>{version.content.allowed_agents.map((item) => <code key={item}>{item}</code>)}</div>
            <label>Tools / MCP</label><div>{[...version.content.allowed_tools, ...version.content.allowed_mcps.map((item) => `mcp:${item}`)].map((item) => <code key={item}>{item}</code>)}</div>
          </div>
          <div className="skill-review-actions">
            {version.status === "draft" && <button className="primary-button" disabled={busy || !version.validation.valid} onClick={() => void publishCurrent()} type="button">人工确认并发布 v{version.version}</button>}
            <button disabled={busy || detail?.skill.status !== "published" || !currentVideoId} onClick={() => void bindCurrentVideo()} type="button">
              {currentVideoId && detail?.bound_video_ids.includes(currentVideoId) ? "已绑定当前视频" : "绑定当前视频"}
            </button>
            <button onClick={() => onOpenTrace(version.trace_id)} type="button">查看生成 Trace</button>
            {version.status === "published" && detail?.skill.active_version !== version.version && <button disabled={busy} onClick={() => void rollback(version)} type="button">回滚运行时到 v{version.version}</button>}
          </div>
          <div className="skill-basis"><h3>生成依据</h3><RuleList items={version.generation_basis} /></div>
        </> : <p className="skill-empty">选择或生成一个 Skill 后，可在这里完成发布与绑定。</p>}
        {message && <p className="skill-message" aria-live="polite">{message}</p>}
      </aside>
    </section>
  );
}
