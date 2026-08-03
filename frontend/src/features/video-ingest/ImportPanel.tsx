"use client";

import { FormEvent, useRef, useState } from "react";

import { importVideoUrl, uploadVideo } from "@/lib/api/client";
import type { Video } from "@/lib/api/types";

interface ImportPanelProps {
  onImported(video: Video): void;
}

export function ImportPanel({ onImported }: ImportPanelProps) {
  const [mode, setMode] = useState<"url" | "upload">("url");
  const [url, setUrl] = useState("");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submitUrl(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const video = await importVideoUrl({ url, rightsConfirmed });
      onImported(video);
      setUrl("");
      setMessage(
        rightsConfirmed ? "已登记并等待处理" : "已按“仅元数据”模式登记",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "导入失败");
    } finally {
      setBusy(false);
    }
  }

  async function submitFile() {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setMessage("请先选择视频文件");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const video = await uploadVideo(file);
      onImported(video);
      setMessage("上传完成，等待媒体 Worker 处理");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="import-panel" aria-label="导入视频">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">INGEST</span>
          <h2>添加视频</h2>
        </div>
        <div className="segmented-control" aria-label="导入方式">
          <button
            className={mode === "url" ? "active" : ""}
            onClick={() => setMode("url")}
            type="button"
          >
            网页链接
          </button>
          <button
            className={mode === "upload" ? "active" : ""}
            onClick={() => setMode("upload")}
            type="button"
          >
            本地文件
          </button>
        </div>
      </div>

      {mode === "url" ? (
        <form onSubmit={submitUrl}>
          <label className="field-label" htmlFor="video-url">
            公开网页或视频直链
          </label>
          <div className="inline-field">
            <input
              id="video-url"
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://www.bilibili.com/video/..."
              required
              type="url"
              value={url}
            />
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? "登记中…" : "导入"}
            </button>
          </div>
          <label className="rights-check">
            <input
              checked={rightsConfirmed}
              onChange={(event) => setRightsConfirmed(event.target.checked)}
              type="checkbox"
            />
            <span>
              我确认拥有处理该视频的权限。未勾选时只登记元数据，不自动下载。
            </span>
          </label>
        </form>
      ) : (
        <div>
          <label className="field-label" htmlFor="video-file">
            MP4 / MOV / MKV / WebM
          </label>
          <div className="inline-field">
            <input
              accept=".mp4,.mov,.mkv,.webm,video/*"
              id="video-file"
              ref={fileRef}
              type="file"
            />
            <button
              className="primary-button"
              disabled={busy}
              onClick={submitFile}
              type="button"
            >
              {busy ? "上传中…" : "上传"}
            </button>
          </div>
        </div>
      )}
      {message && <p className="form-message">{message}</p>}
    </section>
  );
}
