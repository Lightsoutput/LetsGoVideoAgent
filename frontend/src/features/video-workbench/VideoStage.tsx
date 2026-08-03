"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { getVideoMediaUrl } from "@/lib/api/client";
import type { TimelineArtifact, Video } from "@/lib/api/types";
import { formatDuration, formatTimestamp } from "@/lib/format";

interface VideoStageProps {
  video: Video;
  timeline: TimelineArtifact[];
  currentTimeMs: number;
  onTimeChange(value: number): void;
}

interface SpeakerStyle {
  name?: string;
  color?: string;
}

const SPEAKER_COLORS = ["#ffffff", "#6fffd2", "#ffd166", "#8ec5ff", "#ff9eb5"];

export function VideoStage({
  video,
  timeline,
  currentTimeMs,
  onTimeChange,
}: VideoStageProps) {
  const mediaRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  const [showSubtitleSettings, setShowSubtitleSettings] = useState(false);
  const [speakerStyles, setSpeakerStyles] = useState<Record<string, SpeakerStyle>>({});
  const lastTick = useRef<number | null>(null);
  const duration = video.duration_ms ?? 1;
  const activeChapter =
    timeline.find(
      (item) =>
        item.kind === "chapter" &&
        currentTimeMs >= item.time_range.start_ms &&
        currentTimeMs <= item.time_range.end_ms,
    ) ?? timeline.find((item) => item.kind === "chapter");
  const transcriptItems = useMemo(
    () => timeline.filter((item) => ["transcript", "speaker_turn"].includes(item.kind)),
    [timeline],
  );
  const speakers = useMemo(
    () => [...new Set(transcriptItems.map((item) => item.speaker ?? "default"))],
    [transcriptItems],
  );
  const activeSubtitles = transcriptItems
    .filter(
      (item) =>
        currentTimeMs >= item.time_range.start_ms && currentTimeMs <= item.time_range.end_ms,
    )
    .slice(-2);

  const hasPlayableMedia = video.source_object_key !== null;

  // 时间轴点击、聊天证据跳转都会反向驱动真实播放器。
  useEffect(() => {
    const media = mediaRef.current;
    if (!media || !Number.isFinite(media.duration)) return;
    const targetSeconds = currentTimeMs / 1000;
    if (Math.abs(media.currentTime - targetSeconds) > 0.35) {
      media.currentTime = Math.min(media.duration || targetSeconds, targetSeconds);
    }
  }, [currentTimeMs]);

  // 合成视频保留可测试的 requestAnimationFrame 播放逻辑。
  useEffect(() => {
    if (!playing || video.source.kind !== "synthetic") {
      lastTick.current = null;
      return;
    }
    let frame = 0;
    function tick(now: number) {
      const previous = lastTick.current ?? now;
      lastTick.current = now;
      const next = Math.min(duration, currentTimeMs + (now - previous));
      onTimeChange(next);
      if (next >= duration) {
        setPlaying(false);
        return;
      }
      frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [currentTimeMs, duration, onTimeChange, playing, video.source.kind]);

  async function togglePlayback() {
    if (video.source.kind === "synthetic") {
      setPlaying((value) => !value);
      return;
    }
    const media = mediaRef.current;
    if (!media) return;
    if (media.paused) await media.play();
    else media.pause();
  }

  return (
    <section className="video-stage">
      <div className="stage-toolbar">
        <div className="stage-title">
          <span className={`status-pulse status-${video.status}`} />
          <div>
            <strong>{video.title}</strong>
            <small>
              {video.width ?? "—"} × {video.height ?? "—"} ·{" "}
              {video.fps ? `${video.fps} FPS` : "FPS —"} ·{" "}
              {formatDuration(video.duration_ms)}
            </small>
          </div>
        </div>
        <div className="stage-chapter">
          <span>{activeChapter?.title ?? "未定位章节"}</span>
          <b className="status-chip">{video.status.replaceAll("_", " ")}</b>
        </div>
      </div>

      <div className="player-canvas">
        {video.source.kind === "synthetic" ? (
          <div className="synthetic-frame">
            <div className="frame-grid" />
            <div className="game-map">
              <span className="map-node node-a">资源</span>
              <span className="map-node node-b">治疗</span>
              <span className="map-node node-c">防御</span>
              <span className="route-line line-a" />
              <span className="route-line line-b" />
            </div>
            <div className="frame-caption">
              <span>SYNTHETIC TEST FRAME</span>
              <h3>{activeChapter?.title ?? "塔防游戏新手关卡讲解"}</h3>
              <p>{activeChapter?.text ?? "等待时间轴证据"}</p>
            </div>
            <span className="frame-timecode">{formatTimestamp(currentTimeMs)}</span>
          </div>
        ) : hasPlayableMedia ? (
          <video
            controls={false}
            key={video.id}
            onCanPlay={() => setMediaError(null)}
            onEnded={() => setPlaying(false)}
            onError={() => setMediaError("浏览器无法解码该媒体；可尝试转码为 H.264/AAC MP4")}
            onPause={() => setPlaying(false)}
            onPlay={() => setPlaying(true)}
            onTimeUpdate={(event) => onTimeChange(event.currentTarget.currentTime * 1000)}
            playsInline
            preload="metadata"
            ref={mediaRef}
            src={getVideoMediaUrl(video.id)}
          />
        ) : (
          <div className="media-pending">
            <span className="media-icon">↗</span>
            <strong>{video.status === "failed" ? "网页视频导入失败" : "正在准备网页视频"}</strong>
            <p>
              {video.error_message ??
                (video.current_stage === "metadata_only_waiting_for_rights_confirmation"
                  ? "尚未确认处理权限，因此没有下载媒体。"
                  : "下载完成后会自动播放并进入字幕、画面和章节分析。")}
            </p>
          </div>
        )}
        {mediaError && <div className="media-error">{mediaError}</div>}
        {subtitlesEnabled && activeSubtitles.length > 0 && (
          <div className="video-subtitle-overlay" aria-live="off">
            {activeSubtitles.map((item) => {
              const speakerKey = item.speaker ?? "default";
              const speakerIndex = Math.max(0, speakers.indexOf(speakerKey));
              const style = speakerStyles[speakerKey] ?? {};
              const speakerName = style.name ?? item.speaker ?? "";
              return (
                <p
                  key={item.id}
                  style={{ color: style.color ?? SPEAKER_COLORS[speakerIndex % SPEAKER_COLORS.length] }}
                >
                  {speakerName && <b>{speakerName}：</b>}
                  {item.text}
                </p>
              );
            })}
          </div>
        )}
        {showSubtitleSettings && (
          <aside className="subtitle-settings" aria-label="字幕与说话人设置">
            <div>
              <strong>字幕样式</strong>
              <button onClick={() => setShowSubtitleSettings(false)} type="button">×</button>
            </div>
            {speakers.map((speaker, index) => (
              <label key={speaker}>
                <input
                  aria-label={`${speaker} 名称`}
                  onChange={(event) =>
                    setSpeakerStyles((current) => ({
                      ...current,
                      [speaker]: { ...current[speaker], name: event.target.value },
                    }))
                  }
                  placeholder={speaker === "default" ? "默认说话人" : speaker}
                  type="text"
                  value={speakerStyles[speaker]?.name ?? ""}
                />
                <input
                  aria-label={`${speaker} 字幕颜色`}
                  onChange={(event) =>
                    setSpeakerStyles((current) => ({
                      ...current,
                      [speaker]: { ...current[speaker], color: event.target.value },
                    }))
                  }
                  type="color"
                  value={speakerStyles[speaker]?.color ?? SPEAKER_COLORS[index % SPEAKER_COLORS.length]}
                />
              </label>
            ))}
            <small>检测到 {speakers.length} 个说话人轨道；设置仅影响当前浏览会话。</small>
          </aside>
        )}
      </div>

      <div className="player-controls">
        <button
          aria-label={playing ? "暂停" : "播放"}
          className="play-button"
          disabled={!hasPlayableMedia && video.source.kind !== "synthetic"}
          onClick={() => void togglePlayback()}
          type="button"
        >
          {playing ? "Ⅱ" : "▶"}
        </button>
        <span className="control-time">{formatTimestamp(currentTimeMs)}</span>
        <input
          aria-label="视频播放进度"
          max={duration}
          min={0}
          onChange={(event) => onTimeChange(Number(event.target.value))}
          type="range"
          value={Math.min(duration, currentTimeMs)}
        />
        <span className="control-time muted">{formatDuration(video.duration_ms)}</span>
        <button
          aria-pressed={subtitlesEnabled}
          className={subtitlesEnabled ? "subtitle-toggle active" : "subtitle-toggle"}
          onClick={() => setSubtitlesEnabled((value) => !value)}
          type="button"
        >
          CC
        </button>
        <button
          aria-label="字幕与说话人设置"
          className="subtitle-settings-button"
          onClick={() => setShowSubtitleSettings((value) => !value)}
          type="button"
        >
          字幕
        </button>
        <span className="evidence-mode">VIDEO · TIMELINE SYNC</span>
      </div>
    </section>
  );
}
