"use client";

import { FormEvent, useState } from "react";

import { EvidenceCard } from "@/features/evidence-panel/EvidenceCard";
import { askVideo } from "@/lib/api/client";
import type {
  Answer,
  QuestionTarget,
  TimeRange,
  Video,
} from "@/lib/api/types";
import { formatCost, formatTimestamp } from "@/lib/format";

type ScopeMode = "global" | "range" | "moment" | "frame";

interface ChatPanelProps {
  video: Video | null;
  currentTimeMs: number;
  activeRange: TimeRange | null;
  onSeek(timestampMs: number): void;
}

interface ConversationTurn {
  id: string;
  question: string;
  answer?: Answer;
  status: "pending" | "completed" | "failed";
  error?: string;
}

const QUICK_QUESTIONS = [
  "这个视频大致讲了什么？",
  "自动分段后，每个章节的重点是什么？",
  "当前画面中能看到哪些信息？",
];

function uniqueCitations(answer: Answer) {
  const seen = new Set<string>();
  return answer.citations.filter((citation) => {
    const key = citation.snapshot_url ?? `${citation.timestamp_ms}:${citation.label}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function ChatPanel({
  video,
  currentTimeMs,
  activeRange,
  onSeek,
}: ChatPanelProps) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<ScopeMode>("global");
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function buildTarget(): QuestionTarget {
    if (scope === "frame") return { kind: "frame", timestamp_ms: currentTimeMs };
    if (scope === "moment") {
      return {
        kind: "moment",
        timestamp_ms: currentTimeMs,
        context_window_ms: 8_000,
      };
    }
    if (scope === "range") {
      return {
        kind: "range",
        time_range:
          activeRange ?? {
            start_ms: Math.max(0, currentTimeMs - 30_000),
            end_ms: currentTimeMs + 30_000,
          },
      };
    }
    return { kind: "global" };
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!video || !query.trim() || busy) return;
    const submittedQuery = query.trim();
    const turnId = crypto.randomUUID();
    setQuery("");
    setBusy(true);
    setError(null);
    // 先把用户消息放进对话区；网络请求在其后进行，长时间思考时用户也能确认已发送。
    setTurns((items) => [
      ...items,
      { id: turnId, question: submittedQuery, status: "pending" },
    ]);
    try {
      const answer = await askVideo(video.id, submittedQuery, buildTarget());
      setTurns((items) =>
        items.map((item) =>
          item.id === turnId ? { ...item, answer, status: "completed" } : item,
        ),
      );
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Agent 调查失败";
      setError(message);
      setTurns((items) =>
        items.map((item) =>
          item.id === turnId ? { ...item, status: "failed", error: message } : item,
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="chat-panel" aria-label="视频 Agent 对话">
      <div className="chat-heading">
        <div>
          <span className="eyebrow">VIDEO QA AGENT</span>
          <h2>和视频对话</h2>
        </div>
        <span className="agent-online">
          <i /> Agent 在线
        </span>
      </div>

      <div className="scope-switcher">
        {(
          [
            ["global", "全视频"],
            ["range", "当前章节"],
            ["moment", "这一刻"],
            ["frame", "当前帧"],
          ] as const
        ).map(([value, label]) => (
          <button
            className={scope === value ? "active" : ""}
            key={value}
            onClick={() => setScope(value)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>

      <div className="scope-context">
        <span>检索范围</span>
        <strong>
          {scope === "global"
            ? "完整时间轴"
            : scope === "range" && activeRange
              ? `${formatTimestamp(activeRange.start_ms)} – ${formatTimestamp(
                  activeRange.end_ms,
                )}`
              : `${formatTimestamp(currentTimeMs)} 附近`}
        </strong>
      </div>

      <div className="conversation">
        {turns.length === 0 && (
          <div className="empty-chat">
            <div className="agent-mark">L</div>
            <h3>我会先找证据，再回答</h3>
            <p>
              你可以问整体内容、某个章节、这一刻发生了什么，或暂停后询问当前帧。
            </p>
            <div className="quick-questions">
              {QUICK_QUESTIONS.map((question) => (
                <button
                  key={question}
                  onClick={() => setQuery(question)}
                  type="button"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map(({ id, question, answer, status, error: turnError }) => {
          if (!answer) {
            return (
              <div className="conversation-turn" key={id}>
                <div className="user-message">{question}</div>
                {status === "pending" ? (
                  <div className="agent-thinking turn-thinking">
                    <i />
                    <span>已收到问题，正在检索全片证据并组织回答…</span>
                  </div>
                ) : (
                  <div className="agent-message failed-message">
                    回答失败：{turnError ?? "未知错误"}
                  </div>
                )}
              </div>
            );
          }
          const citations = uniqueCitations(answer);
          return (
          <div className="conversation-turn" key={id}>
            <div className="user-message">{question}</div>
            <div className="agent-message">
              <div className="answer-header">
                <span className={`answer-status status-${answer.status}`}>
                  {answer.status === "answered"
                    ? "证据验证通过"
                    : answer.status === "partial"
                      ? "部分证据"
                      : "证据不足"}
                </span>
                <span>{Math.round(answer.confidence * 100)}% 置信度</span>
              </div>
              <p className="answer-text">{answer.text}</p>
              {citations.length > 0 && (
                <div className="evidence-list">
                  <h4>可回放证据 · {citations.length}</h4>
                  {citations.map((citation, index) => (
                    <EvidenceCard
                      citation={citation}
                      index={index}
                      key={citation.evidence_id}
                      onSeek={onSeek}
                    />
                  ))}
                </div>
              )}
              {answer.limitations.length > 0 && (
                <details className="limitations">
                  <summary>查看回答限制</summary>
                  <ul>
                    {answer.limitations.map((limitation) => (
                      <li key={limitation}>{limitation}</li>
                    ))}
                  </ul>
                </details>
              )}
              <div className="answer-meta">
                <span>{answer.usage.tool_calls} 次工具调用</span>
                <span>{answer.usage.elapsed_ms} ms</span>
                <span>{formatCost(answer.usage.estimated_cost_usd)}</span>
                <span title={answer.trace_id}>Trace {answer.trace_id.slice(0, 8)}</span>
              </div>
            </div>
          </div>
          );
        })}
      </div>

      <form className="chat-composer" onSubmit={submit}>
        {error && <p className="chat-error">{error}</p>}
        <textarea
          disabled={!video || busy}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder={video ? "针对视频提问，Enter 发送…" : "请先选择视频"}
          rows={3}
          value={query}
        />
        <div className="composer-footer">
          <span>回答将附带时间戳和视频内证据</span>
          <button disabled={!video || !query.trim() || busy} type="submit">
            {busy ? "调查中" : "发送"} <b>↗</b>
          </button>
        </div>
      </form>
    </aside>
  );
}
