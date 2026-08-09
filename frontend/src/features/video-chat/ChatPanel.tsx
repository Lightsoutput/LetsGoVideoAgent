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
  onAnswer?(answer: Answer): void;
  onOpenTrace?(traceId: string): void;
}

interface ConversationTurn {
  id: string;
  question: string;
  answer?: Answer;
  status: "pending" | "completed" | "failed";
  error?: string;
  useWebSearch: boolean;
}

const QUICK_QUESTIONS = [
  "这个视频大致讲了什么？",
  "自动分段后，每个章节的重点是什么？",
  "当前画面中能看到哪些信息？",
];

interface PreparedQuestion {
  question: string;
  answer: string;
  start_ms: number;
}

function preparedOverview(video: Video | null) {
  const summary = typeof video?.metadata.summary === "string" ? video.metadata.summary : "";
  const rawQuestions = Array.isArray(video?.metadata.quick_questions)
    ? video.metadata.quick_questions
    : [];
  const questions = rawQuestions.filter(
    (item): item is PreparedQuestion =>
      typeof item === "object" &&
      item !== null &&
      typeof item.question === "string" &&
      typeof item.answer === "string" &&
      typeof item.start_ms === "number",
  );
  return { summary, questions };
}

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
  onAnswer,
  onOpenTrace,
}: ChatPanelProps) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<ScopeMode>("global");
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [useWebSearch, setUseWebSearch] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const overview = preparedOverview(video);

  function buildTarget(): QuestionTarget {
    const timestampMs = Math.max(0, Math.round(currentTimeMs));
    if (scope === "frame") return { kind: "frame", timestamp_ms: timestampMs };
    if (scope === "moment") {
      return {
        kind: "moment",
        timestamp_ms: timestampMs,
        context_window_ms: 8_000,
      };
    }
    if (scope === "range") {
      return {
        kind: "range",
        time_range:
          activeRange ?? {
            start_ms: Math.max(0, Math.round(currentTimeMs - 30_000)),
            end_ms: Math.round(currentTimeMs + 30_000),
          },
      };
    }
    return { kind: "global" };
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!video || !query.trim() || busy) return;
    const submittedQuery = query.trim();
    const submittedUseWebSearch = useWebSearch;
    const turnId = crypto.randomUUID();
    setQuery("");
    setBusy(true);
    setError(null);
    // 先把用户消息放进对话区；网络请求在其后进行，长时间思考时用户也能确认已发送。
    setTurns((items) => [
      ...items,
      {
        id: turnId,
        question: submittedQuery,
        status: "pending",
        useWebSearch: submittedUseWebSearch,
      },
    ]);
    try {
      const answer = await askVideo(
        video.id,
        submittedQuery,
        buildTarget(),
        submittedUseWebSearch,
      );
      onAnswer?.(answer);
      setTurns((items) =>
        items.map((item) =>
          item.id === turnId ? { ...item, answer, status: "completed" } : item,
        ),
      );
    } catch (reason) {
      const message =
        reason instanceof Error
          ? reason.message
          : typeof reason === "string"
            ? reason
            : JSON.stringify(reason);
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
            {overview.summary && (
              <section className="prepared-overview">
                <strong>视频速览</strong>
                <p>{overview.summary}</p>
                {overview.questions.map((item) => (
                  <details key={item.question}>
                    <summary>{item.question}</summary>
                    <p>{item.answer}</p>
                    <button onClick={() => onSeek(item.start_ms)} type="button">
                      跳到 {formatTimestamp(item.start_ms)}
                    </button>
                  </details>
                ))}
              </section>
            )}
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

        {turns.map(({ id, question, answer, status, error: turnError, useWebSearch: turnUsesWeb }) => {
          if (!answer) {
            return (
              <div className="conversation-turn" key={id}>
                <div className="user-message">
                  {turnUsesWeb && <small>🌐 强制联网</small>}
                  {question}
                </div>
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
            <div className="user-message">
              {turnUsesWeb && <small>🌐 已联网补充</small>}
              {question}
            </div>
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
              {answer.web_search_performed && (
                <details className="web-sources" open={answer.web_sources.length > 0}>
                  <summary>联网补充来源 · {answer.web_sources.length}</summary>
                  {answer.web_sources.map((source) => (
                    <a href={source.url} key={source.url} rel="noreferrer" target="_blank">
                      <strong>{source.title}</strong>
                      <span>{source.content || source.url}</span>
                    </a>
                  ))}
                  {answer.web_sources.length === 0 && <p>已执行搜索，但没有返回可用来源。</p>}
                </details>
              )}
              <div className="answer-meta">
                <span>{answer.usage.tool_calls} 次工具调用</span>
                <span>{answer.usage.elapsed_ms} ms</span>
                <span>{formatCost(answer.usage.estimated_cost_usd)}</span>
                <button
                  className="answer-trace-button"
                  onClick={() => onOpenTrace?.(answer.trace_id)}
                  title={answer.trace_id}
                  type="button"
                >
                  查看 Trace {answer.trace_id.slice(0, 8)}
                </button>
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
        <label className={`web-search-toggle ${useWebSearch ? "active" : ""}`}>
          <input
            checked={useWebSearch}
            disabled={!video || busy}
            onChange={(event) => setUseWebSearch(event.target.checked)}
            type="checkbox"
          />
          <span>联网补充回答</span>
          <small>勾选后本次问答一定调用 Search MCP，并展示来源</small>
        </label>
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
