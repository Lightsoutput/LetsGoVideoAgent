"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";

import { getTimelineSnapshotUrl } from "@/lib/api/client";
import type { TimelineArtifact, TimelineKind } from "@/lib/api/types";
import { formatTimestamp } from "@/lib/format";

interface TimelineProps {
  videoId: string;
  durationMs: number;
  currentTimeMs: number;
  items: TimelineArtifact[];
  onSeek(timestampMs: number): void;
}

interface TrackDefinition {
  id: string;
  label: string;
  hint: string;
  tone: string;
  kinds?: TimelineKind[];
  snapshots?: boolean;
}

const LABEL_WIDTH = 116;
const LANE_HEIGHT = 32;
const TRACKS: TrackDefinition[] = [
  { id: "chapter", label: "章节", hint: "Agent 分段", kinds: ["chapter", "segment"], tone: "chapter" },
  { id: "speech", label: "语音", hint: "Whisper 字幕", kinds: ["transcript", "speaker_turn"], tone: "speech" },
  { id: "visual", label: "画面 / OCR", hint: "关键帧与画面文字", snapshots: true, tone: "visual" },
  { id: "signal", label: "事件", hint: "视觉事件", kinds: ["event"], tone: "signal" },
];

function assignLanes(items: TimelineArtifact[], pixelsPerMs: number, minWidth: number) {
  const laneEnds: number[] = [];
  return [...items]
    .sort((a, b) => a.time_range.start_ms - b.time_range.start_ms)
    .map((item) => {
      const left = item.time_range.start_ms * pixelsPerMs;
      const naturalWidth = (item.time_range.end_ms - item.time_range.start_ms) * pixelsPerMs;
      const width = Math.max(minWidth, naturalWidth);
      let lane = laneEnds.findIndex((end) => end <= left);
      if (lane < 0) lane = laneEnds.length;
      laneEnds[lane] = left + width;
      return { item, left, width, lane };
    });
}

export function Timeline({
  videoId,
  durationMs,
  currentTimeMs,
  items,
  onSeek,
}: TimelineProps) {
  const [pixelsPerSecond, setPixelsPerSecond] = useState(14);
  const [selected, setSelected] = useState<TimelineArtifact | null>(null);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [maxScrollLeft, setMaxScrollLeft] = useState(0);
  const [viewportWidth, setViewportWidth] = useState(900);
  const [focusedTrack, setFocusedTrack] = useState<string | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const safeDuration = Math.max(1, durationMs);
  const pixelsPerMs = pixelsPerSecond / 1000;
  const contentWidth = Math.max(
    320,
    viewportWidth - LABEL_WIDTH,
    safeDuration * pixelsPerMs,
  );
  const playheadLeft = LABEL_WIDTH + currentTimeMs * pixelsPerMs;
  const rawFitPixelsPerSecond = (viewportWidth - LABEL_WIDTH) / (safeDuration / 1000);
  const fitPixelsPerSecond = Math.max(
    0.5,
    Math.min(36, Math.floor(rawFitPixelsPerSecond * 2) / 2),
  );

  const layouts = useMemo(
    () =>
      TRACKS.map((track) => {
        const chapterItems = items.filter((item) => item.kind === "chapter");
        const trackItems = track.snapshots
          ? items.filter(
              (item) =>
                Boolean(item.snapshot_key) &&
                ["visual", "keyframe", "shot"].includes(item.kind),
            )
          : track.id === "chapter" && chapterItems.length > 0
            ? chapterItems
            : items.filter((item) => track.kinds?.includes(item.kind));
        // 字幕本身按时间连续，使用很小的最小宽度即可保持单层；悬停时再放大阅读。
        const minWidth = track.snapshots
          ? pixelsPerSecond < 2
            ? 8
            : Math.min(120, Math.max(24, pixelsPerSecond * 8))
          : track.id === "chapter"
            ? pixelsPerSecond < 2
              ? 2
              : Math.min(72, Math.max(24, pixelsPerSecond * 5))
            : track.id === "speech"
              ? 2
              : 28;
        const clips =
          track.id === "speech" || track.id === "chapter"
            ? [...trackItems]
                .sort((a, b) => a.time_range.start_ms - b.time_range.start_ms)
                .map((item) => ({
                  item,
                  left: item.time_range.start_ms * pixelsPerMs,
                  width: Math.max(
                    track.id === "speech" ? (pixelsPerSecond < 2 ? 1 : 2) : minWidth,
                    (item.time_range.end_ms - item.time_range.start_ms) * pixelsPerMs,
                  ),
                  lane: 0,
                }))
            : assignLanes(trackItems, pixelsPerMs, minWidth);
        const lanes = Math.max(1, ...clips.map((clip) => clip.lane + 1));
        const laneHeight = track.snapshots ? 82 : LANE_HEIGHT;
        return { track, clips, height: lanes * laneHeight + 10, laneHeight };
      }).filter(({ clips }) => clips.length > 0),
    [items, pixelsPerMs, pixelsPerSecond],
  );

  // 播放时只在游标离开可视区后跟随，不抢夺用户正常拖动滚动条。
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const localX = playheadLeft - scroller.scrollLeft;
    if (localX < LABEL_WIDTH + 40 || localX > scroller.clientWidth - 80) {
      scroller.scrollTo({ left: Math.max(0, playheadLeft - scroller.clientWidth * 0.42) });
    }
  }, [playheadLeft]);

  // 原生滚动条在部分浏览器中会自动隐藏；额外维护一个始终可见的水平浏览滑杆。
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const updateRange = () => {
      setViewportWidth(scroller.clientWidth);
      setMaxScrollLeft(Math.max(0, scroller.scrollWidth - scroller.clientWidth));
      setScrollLeft(scroller.scrollLeft);
    };
    updateRange();
    window.addEventListener("resize", updateRange);
    return () => window.removeEventListener("resize", updateRange);
  }, [contentWidth]);

  function seekFromTrack(event: React.MouseEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const timestamp = ((event.clientX - rect.left) / contentWidth) * safeDuration;
    onSeek(Math.max(0, Math.min(safeDuration, timestamp)));
  }

  function seekFromCanvasPointer(clientX: number) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const localX = clientX - rect.left - LABEL_WIDTH;
    onSeek(Math.max(0, Math.min(safeDuration, localX / pixelsPerMs)));
  }

  const selectedSnapshot = selected
    ? getTimelineSnapshotUrl(videoId, selected.snapshot_key)
    : null;

  return (
    <section className="timeline-panel" aria-label="交互式多轨视频时间轴">
      <div className="timeline-header">
        <div>
          <span className="eyebrow">SPATIOTEMPORAL INDEX</span>
          <h2>交互式多轨时间轴</h2>
        </div>
        <div className="timeline-tools">
          <button
            onClick={() => {
              setPixelsPerSecond(fitPixelsPerSecond);
              scrollerRef.current?.scrollTo({ left: 0, behavior: "smooth" });
            }}
            type="button"
          >
            适应窗口
          </button>
          <label>
            缩放
            <input
              aria-label="时间轴缩放"
              max={36}
              min={0.5}
              onChange={(event) => setPixelsPerSecond(Number(event.target.value))}
              step={0.5}
              type="range"
              value={pixelsPerSecond}
            />
            <b>{pixelsPerSecond < 1 ? pixelsPerSecond.toFixed(1) : Math.round(pixelsPerSecond)}px/s</b>
          </label>
        </div>
      </div>

      <label className="timeline-pan-control">
        <span>水平浏览</span>
        <input
          aria-label="水平浏览完整时间轴"
          disabled={maxScrollLeft === 0}
          max={Math.max(1, maxScrollLeft)}
          min={0}
          onChange={(event) => {
            const nextLeft = Number(event.target.value);
            setScrollLeft(nextLeft);
            scrollerRef.current?.scrollTo({ left: nextLeft });
          }}
          type="range"
          value={Math.min(scrollLeft, Math.max(1, maxScrollLeft))}
        />
        <b>{maxScrollLeft ? Math.round((scrollLeft / maxScrollLeft) * 100) : 0}%</b>
      </label>

      <div
        className={focusedTrack ? "timeline-scroll has-track-focus" : "timeline-scroll"}
        onMouseLeave={() => setFocusedTrack(null)}
        onScroll={(event) => setScrollLeft(event.currentTarget.scrollLeft)}
        ref={scrollerRef}
      >
        <div
          className="timeline-canvas"
          ref={canvasRef}
          style={{ width: LABEL_WIDTH + contentWidth }}
        >
          <div className="timeline-ruler-row">
            <div className="timeline-corner">轨道</div>
            <div className="timeline-ruler-wide" style={{ width: contentWidth }}>
              {Array.from({ length: Math.ceil(safeDuration / 60_000) + 1 }, (_, index) => {
                const timestamp = Math.min(safeDuration, index * 60_000);
                return (
                  <span key={timestamp} style={{ left: timestamp * pixelsPerMs }}>
                    {formatTimestamp(timestamp)}
                  </span>
                );
              })}
            </div>
          </div>

          <div
            aria-label="拖动播放头选择精确时间"
            aria-valuemax={safeDuration}
            aria-valuemin={0}
            aria-valuenow={Math.round(currentTimeMs)}
            className="timeline-playhead-wide"
            onKeyDown={(event) => {
              const step = event.shiftKey ? 10_000 : 1_000;
              if (event.key === "ArrowLeft") onSeek(Math.max(0, currentTimeMs - step));
              if (event.key === "ArrowRight") {
                onSeek(Math.min(safeDuration, currentTimeMs + step));
              }
            }}
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              seekFromCanvasPointer(event.clientX);
            }}
            onPointerMove={(event) => {
              if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                seekFromCanvasPointer(event.clientX);
              }
            }}
            onPointerUp={(event) => event.currentTarget.releasePointerCapture(event.pointerId)}
            role="slider"
            style={{ left: playheadLeft }}
            tabIndex={0}
          >
            <span>{formatTimestamp(currentTimeMs)}</span>
          </div>

          {layouts.map(({ track, clips, height, laneHeight }) => (
            <div
              className={focusedTrack === track.id ? "timeline-row-wide is-focused" : "timeline-row-wide"}
              key={track.id}
              onMouseEnter={() => setFocusedTrack(track.id)}
              style={{ height }}
            >
              <div className="timeline-label-wide">
                <strong>{track.label}</strong>
                <small>{track.hint}</small>
                <b>{clips.length}</b>
              </div>
              <div
                className="timeline-track-wide"
                onClick={seekFromTrack}
                style={{ width: contentWidth }}
              >
                {clips.map(({ item, left, width, lane }) => {
                  const active =
                    currentTimeMs >= item.time_range.start_ms &&
                    currentTimeMs <= item.time_range.end_ms;
                  const imageUrl = track.snapshots
                    ? getTimelineSnapshotUrl(videoId, item.snapshot_key)
                    : null;
                  return (
                    <button
                      aria-label={`${item.title ?? item.kind}，${formatTimestamp(item.time_range.start_ms)}`}
                      className={[
                        "timeline-clip-wide",
                        `tone-${track.tone}`,
                        imageUrl ? "with-thumbnail" : "",
                        item.observation_type === "inference" ? "inferred" : "",
                        active ? "active" : "",
                        selected?.id === item.id ? "selected" : "",
                      ].filter(Boolean).join(" ")}
                      data-start-ms={item.time_range.start_ms}
                      key={`${track.id}-${item.id}`}
                      onClick={() => {
                        setSelected(item);
                        onSeek(item.time_range.start_ms);
                      }}
                      style={{
                        left,
                        top: lane * laneHeight + 5,
                        width,
                        backgroundImage: imageUrl ? `linear-gradient(90deg, rgba(3,8,13,.18), rgba(3,8,13,.75)), url("${imageUrl}")` : undefined,
                      }}
                      title={`${formatTimestamp(item.time_range.start_ms)} · ${item.title ?? item.text}`}
                      type="button"
                    >
                      <span>{item.title ?? item.text}</span>
                      {width >= 90 && <small>{formatTimestamp(item.time_range.start_ms)}</small>}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="timeline-hint">横向滚动浏览完整视频 · 滚轮纵向浏览轨道 · 点击片段同步播放器</div>
      {selected && (
        <aside className="timeline-inspector">
          {selectedSnapshot && (
            <div className="timeline-inspector-image">
              <Image alt="所选时间轴画面" fill sizes="280px" src={selectedSnapshot} unoptimized />
            </div>
          )}
          <div>
            <span>{selected.kind.toUpperCase()} · {formatTimestamp(selected.time_range.start_ms)} – {formatTimestamp(selected.time_range.end_ms)}</span>
            <h3>{selected.title ?? "时间轴证据"}</h3>
            <p>{selected.text}</p>
          </div>
          <button onClick={() => setSelected(null)} type="button" aria-label="关闭详情">×</button>
        </aside>
      )}
    </section>
  );
}
