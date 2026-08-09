"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ChatPanel } from "@/features/video-chat/ChatPanel";
import { ImportPanel } from "@/features/video-ingest/ImportPanel";
import { ObservabilityPanel } from "@/features/observability/ObservabilityPanel";
import { Timeline } from "@/features/timeline/Timeline";
import { VideoStage } from "@/features/video-workbench/VideoStage";
import { getProcessing, getTimeline, getVideo, listVideos, startProcessing } from "@/lib/api/client";
import type { ProcessingRun, TimelineArtifact, Video } from "@/lib/api/types";

export function VideoWorkbench() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineArtifact[]>([]);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [processing, setProcessing] = useState<ProcessingRun | null>(null);
  const [showImporter, setShowImporter] = useState(false);
  const [showObservability, setShowObservability] = useState(false);
  const [activeTraceId, setActiveTraceId] = useState<string | null>(null);
  const [runNotice, setRunNotice] = useState<string | null>(null);
  const processingStatusRef = useRef<Record<string, ProcessingRun["status"]>>({});

  const selectedVideo =
    videos.find((video) => video.id === selectedId) ?? videos[0] ?? null;
  const selectedVideoId = selectedVideo?.id ?? null;

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const items = await listVideos();
        if (!active) return;
        setVideos(items);
        setSelectedId((current) => current ?? items[0]?.id ?? null);
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "无法连接 LetsGoVideoAgent API");
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedVideoId) return;
    let active = true;
    getTimeline(selectedVideoId)
      .then((items) => {
        if (active) setTimeline(items);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "时间轴加载失败");
      });
    return () => {
      active = false;
    };
  }, [selectedVideoId]);

  useEffect(() => {
    if (!selectedVideoId || selectedVideo?.status === "ready") return;
    let active = true;
    const refresh = async () => {
      try {
        const [run, video] = await Promise.all([
          getProcessing(selectedVideoId),
          getVideo(selectedVideoId),
        ]);
        if (!active) return;
        const previousStatus = processingStatusRef.current[selectedVideoId];
        processingStatusRef.current[selectedVideoId] = run.status;
        if (previousStatus !== run.status && run.status === "completed") {
          const message = `${video.title} 已完成多模态理解，可以查看章节、摘要和 Agent Trace。`;
          setRunNotice(message);
          window.setTimeout(() => setRunNotice(null), 7_000);
          if ("Notification" in window && Notification.permission === "granted") {
            new Notification("LetsGoVideoAgent 处理完成", { body: message });
          }
        } else if (previousStatus !== run.status && run.status === "failed") {
          setRunNotice(`${video.title} 处理失败，Agent Trace 中已记录失败节点和自动重试过程。`);
          window.setTimeout(() => setRunNotice(null), 9_000);
        }
        setProcessing(run);
        // 视频一进入处理流程就把 processing trace 设为当前 Trace，观测面板无需等待首次问答。
        setActiveTraceId(run.trace_id);
        setVideos((items) => items.map((item) => (item.id === video.id ? video : item)));
        if (run.status === "completed") setTimeline(await getTimeline(selectedVideoId));
      } catch {
        // 演示数据和仅登记 URL 没有处理任务，轮询失败不覆盖主界面连接状态。
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1200);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [selectedVideoId, selectedVideo?.status]);

  const activeChapter = useMemo(
    () =>
      timeline.find(
        (item) =>
          item.kind === "chapter" &&
          currentTimeMs >= item.time_range.start_ms &&
          currentTimeMs <= item.time_range.end_ms,
      ) ?? null,
    [currentTimeMs, timeline],
  );

  function selectVideo(videoId: string) {
    setSelectedId(videoId);
    setCurrentTimeMs(0);
    setTimeline([]);
    setProcessing(null);
    setActiveTraceId(null);
  }

  function handleImported(video: Video) {
    setVideos((items) => [video, ...items.filter((item) => item.id !== video.id)]);
    selectVideo(video.id);
    setShowImporter(false);
  }

  function seek(timestampMs: number) {
    const duration = selectedVideo?.duration_ms ?? Number.POSITIVE_INFINITY;
    setCurrentTimeMs(Math.min(duration, Math.max(0, timestampMs)));
  }

  async function retryProcessing() {
    if (!selectedVideoId) return;
    setError(null);
    try {
      const run = await startProcessing(selectedVideoId);
      setProcessing(run);
      setActiveTraceId(run.trace_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法重新启动处理任务");
    }
  }

  return (
    <div className={`app-shell compact-shell ${showObservability ? "ops-open" : ""}`}>
      <header className="app-header compact-header">
        <div className="brand">
          <div className="brand-mark"><span /></div>
          <div>
            <strong>LetsGoVideoAgent</strong>
            <small>GENERAL VIDEO INTELLIGENCE</small>
          </div>
        </div>
        <div className="header-video-tools">
          <label>
            <span>当前视频</span>
            <select
              disabled={loading || videos.length === 0}
              onChange={(event) => selectVideo(event.target.value)}
              value={selectedVideoId ?? ""}
            >
              {videos.map((video) => (
                <option key={video.id} value={video.id}>
                  {video.title} · {video.status}
                </option>
              ))}
            </select>
          </label>
          <button className="add-video-button" onClick={() => setShowImporter(true)} type="button">
            ＋ 添加视频
          </button>
        </div>
        <div className="header-status">
          <button
            className="observability-button"
            onClick={() => setShowObservability((current) => !current)}
            type="button"
          >
            {showObservability ? "返回对话" : "运行观测"}
          </button>
          <span className="profile-badge">ECONOMY</span>
          <span className="connection-state">
            <i className={error ? "offline" : ""} />
            {error ? "API 离线" : "本地环境"}
          </span>
        </div>
      </header>

      <main className="workspace-main">
        {runNotice && (
          <div className="run-notice" aria-live="assertive">
            <i />
            <span>{runNotice}</span>
            <button aria-label="关闭运行提醒" onClick={() => setRunNotice(null)} type="button">×</button>
          </div>
        )}
        {error && (
          <div className="connection-error">
            <strong>API 尚未连接</strong>
            <span>{error}。请确认 FastAPI 已启动。</span>
          </div>
        )}
        {processing &&
          selectedVideo?.id === processing.video_id &&
          processing.status !== "completed" && (
            <section className="processing-status" aria-live="polite">
              <strong>{processing.stage_label} · {Math.round(processing.progress * 100)}%</strong>
              <span>{processing.message}</span>
              <span>
                已用 {Math.round(processing.elapsed_seconds)} 秒
                {processing.eta_seconds !== null
                  ? ` · 预计剩余 ${Math.round(processing.eta_seconds)} 秒`
                  : ""}
              </span>
              <progress max={1} value={processing.progress} />
              {processing.error && <code>{processing.error}</code>}
              {processing.status === "failed" && (
                <button className="retry-processing" onClick={() => void retryProcessing()} type="button">
                  重试导入与处理
                </button>
              )}
            </section>
          )}
        {selectedVideo ? (
          <>
            <VideoStage
              currentTimeMs={currentTimeMs}
              onTimeChange={setCurrentTimeMs}
              timeline={timeline}
              video={selectedVideo}
            />
            <Timeline
              currentTimeMs={currentTimeMs}
              durationMs={selectedVideo.duration_ms ?? 1}
              items={timeline}
              onSeek={seek}
              videoId={selectedVideo.id}
            />
          </>
        ) : (
          <section className="no-video-state">
            <div className="agent-mark large">L</div>
            <h1>{loading ? "正在读取视频…" : "添加第一个视频"}</h1>
            <p>上传本地文件或导入有权处理的公开网页视频。</p>
            {!loading && <button className="primary-button" onClick={() => setShowImporter(true)} type="button">添加视频</button>}
          </section>
        )}
      </main>

      <div className="side-workspace">
        <div className="side-chat" hidden={showObservability}>
          <ChatPanel
            activeRange={activeChapter?.time_range ?? null}
            currentTimeMs={currentTimeMs}
            onSeek={seek}
            onAnswer={(answer) => {
              setActiveTraceId(answer.trace_id);
            }}
            onOpenTrace={(traceId) => {
              setActiveTraceId(traceId);
              setShowObservability(true);
            }}
            video={selectedVideo}
          />
        </div>

        <ObservabilityPanel
          key={`${showObservability ? "open" : "closed"}:${activeTraceId ?? "system"}`}
          onClose={() => setShowObservability(false)}
          open={showObservability}
          processing={processing}
          traceId={activeTraceId}
          videoId={selectedVideoId}
        />
      </div>

      {showImporter && (
        <div className="import-modal-backdrop" onMouseDown={() => setShowImporter(false)} role="presentation">
          <div className="import-modal" onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="添加视频">
            <button className="modal-close" onClick={() => setShowImporter(false)} type="button" aria-label="关闭">×</button>
            <ImportPanel onImported={handleImported} />
          </div>
        </div>
      )}
    </div>
  );
}
