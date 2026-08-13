"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getAgentRun,
  getAgentTrace,
  getSystemObservability,
  getUsageSummary,
} from "@/lib/api/client";
import type {
  AgentRun,
  ProcessingRun,
  SystemObservability,
  TraceEvent,
  UsageSummary,
} from "@/lib/api/types";
import { formatCny } from "@/lib/format";

import { buildAgentGraph, buildRuntimeGraph } from "./state-machine/builders";
import { StateMachineCanvas } from "./state-machine/StateMachineCanvas";
import { agentLabel } from "./agentCatalog";

type Tab = "system" | "cost" | "trace";
type GraphView = "agents" | "runtime";

interface ObservabilityPanelProps {
  open: boolean;
  videoId: string | null;
  traceId: string | null;
  processing: ProcessingRun | null;
  onClose(): void;
}

const EMPTY_USAGE: UsageSummary = {
  items: [],
  call_count: 0,
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_cost_cny: "0",
  cost_by_provider: {},
  cost_by_model: {},
};

function statusLabel(status: string) {
  return {
    ready: "可用",
    unavailable: "不可用",
    disabled: "未启用",
    completed: "完成",
    running: "运行中",
    reserved: "已预留",
    failed: "失败",
  }[status] ?? status;
}

function eventLabel(type: TraceEvent["event_type"]) {
  const [group, action] = type.split(".");
  const groupLabel = {
    agent: "Agent",
    model: "模型",
    tool: "工具",
    mcp: "MCP",
    skill: "Skill",
    budget: "预算",
    human: "人工介入",
    workflow: "工作流",
  }[group] ?? group;
  const actionLabel = {
    started: "启动",
    completed: "完成",
    failed: "失败",
    requested: "请求",
    called: "调用",
    returned: "返回",
    loaded: "加载",
    validated: "校验",
    updated: "更新",
    approved: "批准",
    rejected: "拒绝",
  }[action] ?? action;
  return `${groupLabel} · ${actionLabel}`;
}

export function ObservabilityPanel({
  open,
  videoId,
  traceId,
  processing,
  onClose,
}: ObservabilityPanelProps) {
  const [tab, setTab] = useState<Tab>(traceId ? "trace" : "system");
  const [system, setSystem] = useState<SystemObservability | null>(null);
  const [usage, setUsage] = useState<UsageSummary>(EMPTY_USAGE);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphView, setGraphView] = useState<GraphView>("agents");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [systemResult, usageResult, traceResult, agentRunResult] = await Promise.all([
        getSystemObservability(),
        getUsageSummary(traceId ? undefined : videoId ?? undefined, traceId ?? undefined),
        traceId ? getAgentTrace(traceId) : Promise.resolve([]),
        traceId ? getAgentRun(traceId).catch(() => null) : Promise.resolve(null),
      ]);
      setSystem(systemResult);
      setUsage(usageResult);
      setTrace(traceResult);
      setAgentRun(agentRunResult);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "运行观测数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [traceId, videoId]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    const request = Promise.all([
      getSystemObservability(),
      getUsageSummary(traceId ? undefined : videoId ?? undefined, traceId ?? undefined),
      traceId ? getAgentTrace(traceId) : Promise.resolve([]),
      traceId ? getAgentRun(traceId).catch(() => null) : Promise.resolve(null),
    ]);
    void request
      .then(([systemResult, usageResult, traceResult, agentRunResult]) => {
        if (!active) return;
        setSystem(systemResult);
        setUsage(usageResult);
        setTrace(traceResult);
        setAgentRun(agentRunResult);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "运行观测数据加载失败");
        }
      });
    return () => {
      active = false;
    };
  }, [open, traceId, videoId]);

  useEffect(() => {
    if (!open || !traceId) return;
    let active = true;
    // Trace 与成本在处理过程中持续增长；面板打开时自动刷新，用户可以边看视频边看 Agent 工作。
    const poll = () => {
      void Promise.all([
        getAgentTrace(traceId),
        getUsageSummary(traceId ? undefined : videoId ?? undefined, traceId ?? undefined),
        getAgentRun(traceId).catch(() => null),
      ])
        .then(([traceResult, usageResult, agentRunResult]) => {
          if (!active) return;
          setTrace(traceResult);
          setUsage(usageResult);
          setAgentRun(agentRunResult);
          setError(null);
        })
        .catch((reason: unknown) => {
          if (active) {
            setError(reason instanceof Error ? reason.message : "Agent Trace 实时刷新失败");
          }
        });
    };
    const timer = window.setInterval(poll, 1800);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [open, traceId, videoId]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    // 本地搜索进程可能正处于自愈窗口；面板打开时定期刷新分层健康状态，
    // 避免一次瞬时失败永久停留为“不可用”。
    const timer = window.setInterval(() => {
      void getSystemObservability()
        .then((result) => {
          if (active) setSystem(result);
        })
        .catch(() => {
          // Trace 与成本观测不因一次健康探针失败而被清空。
        });
    }, 10_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [open]);

  const maxModelCost = useMemo(
    () => Math.max(0, ...Object.values(usage.cost_by_model).map(Number)),
    [usage.cost_by_model],
  );
  const agentGraph = useMemo(
    () => buildAgentGraph(trace, Boolean(processing && traceId === processing.trace_id)),
    [processing, trace, traceId],
  );
  const runtimeGraph = useMemo(() => buildRuntimeGraph(system, trace), [system, trace]);

  if (!open) return null;

  const tokenUsage = agentRun
    ? agentRun.usage.input_tokens + agentRun.usage.output_tokens
    : 0;
  const harnessMeters = agentRun
    ? [
        ["工作步骤", agentRun.steps.length, agentRun.budget.max_steps],
        ["工具调用", agentRun.usage.tool_calls, agentRun.budget.max_tool_calls],
        ["模型调用", agentRun.usage.model_calls, agentRun.budget.max_model_calls],
        ["Token", tokenUsage, agentRun.budget.max_tokens],
      ] as const
    : [];
  const terminalEvent = trace.findLast(
    (event) =>
      event.event_type === "workflow.completed" ||
      event.event_type === "workflow.failed",
  );
  const runContext = agentRun
    ? `问答 Agent · ${statusLabel(agentRun.status)} · ${agentRun.id.slice(0, 8)}`
    : processing && traceId === processing.trace_id
      ? `视频处理 Agent · ${statusLabel(processing.status)} · ${processing.trace_id.slice(0, 8)}`
      : traceId
        ? `Agent Trace · ${traceId.slice(0, 8)}`
        : "系统运行底座";

  return (
      <aside aria-label="Agent 运行观测" className="ops-panel">
        <header className="ops-header">
          <div>
            <span className="eyebrow">AGENT OPERATIONS</span>
            <h2>运行观测</h2>
            <p className="ops-run-context"><i />{runContext}</p>
          </div>
          <div className="ops-header-actions">
            <button disabled={loading} onClick={() => void refresh()} type="button">
              {loading ? "刷新中" : "刷新"}
            </button>
            <button aria-label="关闭运行观测" onClick={onClose} type="button">×</button>
          </div>
        </header>

        <nav className="ops-tabs" aria-label="观测类型">
          {([
            ["system", "系统与 Harness"],
            ["cost", "成本中心"],
            ["trace", `状态机与 Trace${traceId ? " · 当前" : ""}`],
          ] as const).map(([value, label]) => (
            <button
              className={tab === value ? "active" : ""}
              key={value}
              onClick={() => setTab(value)}
              type="button"
            >
              {label}
            </button>
          ))}
        </nav>

        {error && <p className="ops-error">{error}</p>}

        <div className="ops-content">
          {tab === "system" && (
            <div className="ops-system">
              <section className="ops-card ops-card-wide">
                <div className="ops-card-title">
                  <strong>Agent Harness</strong>
                  <span>运行约束</span>
                </div>
                {system ? (
                  <div className="policy-grid">
                    <span><b>{system.harness.max_steps}</b>最大步骤</span>
                    <span><b>{system.harness.max_tool_calls}</b>工具调用</span>
                    <span><b>{system.harness.max_model_calls}</b>模型调用</span>
                    <span><b>{system.harness.max_tokens.toLocaleString()}</b>Token 预算</span>
                    <span><b>{system.harness.deadline_seconds}s</b>截止时间</span>
                    <span><b>${system.harness.max_cost_usd}</b>单次预算</span>
                  </div>
                ) : <p>正在读取 Harness 策略…</p>}
                {agentRun && (
                  <div className="harness-live">
                    <div className="harness-live-heading">
                      <strong>本次运行 · {statusLabel(agentRun.status)}</strong>
                      <span>{agentRun.agent_name} / {agentRun.agent_version}</span>
                    </div>
                    {harnessMeters.map(([label, value, limit]) => (
                      <div className="harness-meter" key={label}>
                        <span>{label}</span>
                        <div><i style={{ width: `${Math.min(100, limit ? (value / limit) * 100 : 0)}%` }} /></div>
                        <b>{value.toLocaleString()} / {limit.toLocaleString()}</b>
                      </div>
                    ))}
                    <small>Harness 会执行预算截止、工具白名单、参数校验、重复调用限制与超时保护。</small>
                  </div>
                )}
                {!agentRun && processing && traceId === processing.trace_id && (
                  <div className="processing-observer">
                    <div><strong>{processing.stage_label}</strong><span>{Math.round(processing.progress * 100)}%</span></div>
                    <progress max={1} value={processing.progress} />
                    <p>{processing.message}</p>
                    <small>已运行 {Math.round(processing.elapsed_seconds)} 秒 · 第 {processing.attempt_count} 次尝试</small>
                  </div>
                )}
                <div className="tool-chips">
                  {system?.harness.registered_tools.map((tool) => <code key={tool}>{tool}</code>)}
                </div>
              </section>

              <section className="ops-card">
                <div className="ops-card-title"><strong>MCP</strong><span>外部工具协议</span></div>
                <p className={`service-status status-${system?.mcp.status ?? "loading"}`}>
                  <i /> {system ? statusLabel(system.mcp.status) : "检查中"}
                </p>
                <dl>
                  <div><dt>Provider</dt><dd>{system?.mcp.provider ?? "--"}</dd></div>
                  <div><dt>工具</dt><dd>{system?.mcp.tools.length ?? 0}</dd></div>
                </dl>
                <div className="tool-chips">
                  {system?.mcp.tools.map((tool) => <code key={tool}>{tool}</code>)}
                </div>
              </section>

              <section className="ops-card ops-card-wide">
                <div className="ops-card-title"><strong>运行组件分层诊断</strong><span>故障点可直接定位</span></div>
                <div className="runtime-health-grid">
                  {system?.runtime_components.map((component) => (
                    <article className={`runtime-health status-${component.status}`} key={component.id}>
                      <div><i /><strong>{component.name}</strong><span>{statusLabel(component.status)}</span></div>
                      <p>{component.summary}</p>
                      {component.endpoint && <code title={component.endpoint}>{component.endpoint}</code>}
                    </article>
                  ))}
                  {!system && <p>正在检查 Harness、记忆、MCP、模型与 Trace Store…</p>}
                </div>
              </section>

              <section className="ops-card">
                <div className="ops-card-title"><strong>运行底座</strong><span>当前装配</span></div>
                <dl>
                  <div><dt>Repository</dt><dd>{system?.repository ?? "--"}</dd></div>
                  <div><dt>Workflow</dt><dd>{system?.workflow ?? "--"}</dd></div>
                </dl>
              </section>

              {system?.models.map((route) => (
                <section className="ops-card model-route" key={route.capability}>
                  <div className="ops-card-title">
                    <strong>{route.capability === "text_reasoning" ? "文本推理" : "视觉理解"}</strong>
                    <span className={route.configured ? "configured" : "not-configured"}>
                      {route.configured ? "已配置" : "未配置"}
                    </span>
                  </div>
                  <b>{route.model}</b>
                  <small>{route.provider}</small>
                </section>
              ))}
            </div>
          )}

          {tab === "cost" && (
            <div className="ops-cost">
              <section className="cost-metrics">
                <span><small>{traceId ? "当前任务累计" : "当前视频累计"}</small><b>{formatCny(usage.total_cost_cny)}</b></span>
                <span><small>API 调用</small><b>{usage.call_count}</b></span>
                <span><small>输入 Token</small><b>{usage.total_input_tokens.toLocaleString()}</b></span>
                <span><small>输出 Token</small><b>{usage.total_output_tokens.toLocaleString()}</b></span>
              </section>

              <section className="ops-card ops-card-wide">
                <div className="ops-card-title"><strong>模型成本分布</strong><span>人民币</span></div>
                <div className="cost-bars">
                  {Object.entries(usage.cost_by_model)
                    .sort((left, right) => Number(right[1]) - Number(left[1]))
                    .map(([model, cost]) => (
                      <div className="cost-bar-row" key={model}>
                        <span title={model}>{model}</span>
                        <div><i style={{ width: `${maxModelCost ? (Number(cost) / maxModelCost) * 100 : 0}%` }} /></div>
                        <b>{formatCny(cost)}</b>
                      </div>
                    ))}
                  {Object.keys(usage.cost_by_model).length === 0 && <p>当前视频还没有云 API 费用。</p>}
                </div>
              </section>

              <section className="usage-list">
                <div className="ops-card-title"><strong>最近调用</strong><span>最多显示 200 条</span></div>
                {usage.items.slice().reverse().map((item) => (
                  <article key={item.id}>
                    <div><strong>{item.purpose}</strong><small>{agentLabel(item.agent_id)} · {item.provider} / {item.model}</small></div>
                    <span>{item.input_tokens + item.output_tokens} tokens{item.image_count ? ` · ${item.image_count} 图` : ""}</span>
                    <b>{formatCny(item.cost_cny)}</b>
                  </article>
                ))}
              </section>
            </div>
          )}

          {tab === "trace" && (
            <div className="trace-view">
              {terminalEvent && (
                <div className={`trace-terminal status-${terminalEvent.status ?? "completed"}`} role="status">
                  <i />
                  <div><strong>{terminalEvent.event_type === "workflow.failed" ? "运行失败" : "运行已结束"}</strong><span>{terminalEvent.summary}</span></div>
                  <time>{new Date(terminalEvent.occurred_at).toLocaleTimeString()}</time>
                </div>
              )}
              {processing && traceId === processing.trace_id && (
                <section className="trace-now" aria-live="polite">
                  <div><strong>{processing.stage_label}</strong><span>{Math.round(processing.progress * 100)}%</span></div>
                  <progress max={1} value={processing.progress} />
                  <p>{processing.message}</p>
                </section>
              )}
              {processing && traceId === processing.trace_id && processing.agent_tasks.length > 0 && (
                <section className="trace-agent-workboard" aria-label="Agent 实时工作台">
                  <header><div><small>LIVE ASSIGNMENTS</small><h3>这条视频现在由谁处理</h3></div><span>{processing.agent_tasks.filter((task) => task.status === "running").length} 个并行任务</span></header>
                  <div>
                    {processing.agent_tasks.map((task) => (
                      <article className={`status-${task.status}`} key={task.agent_id}>
                        <div><strong>{task.agent_number} {task.display_name}</strong><span>{statusLabel(task.status)}</span></div>
                        <small>{task.role} · {task.phase}</small>
                        <p>{task.message}</p>
                        <progress max={1} value={task.progress} />
                        <footer><span>{task.total_units ? `${task.completed_units}/${task.total_units}` : `${Math.round(task.progress * 100)}%`}</span><code>{task.model ? `${task.model_provider} / ${task.model}` : "本地工具或规则"}</code></footer>
                      </article>
                    ))}
                  </div>
                </section>
              )}
              {!traceId && <div className="ops-empty">上传或选择正在处理的视频后，即可实时查看 Agent Trace；问答 Trace 也会显示在这里。</div>}
              {traceId && trace.length === 0 && !loading && <div className="ops-empty">该运行暂无 Trace 事件。</div>}
              <details className="technical-topology">
                <summary><strong>技术拓扑与状态机</strong><span>排障时展开；日常观察以上方任务工位为准</span></summary>
                <div className="graph-view-switch" role="tablist" aria-label="状态机类型">
                  <button className={graphView === "agents" ? "active" : ""} onClick={() => setGraphView("agents")} role="tab" type="button">多 Agent 工作流</button>
                  <button className={graphView === "runtime" ? "active" : ""} onClick={() => setGraphView("runtime")} role="tab" type="button">Harness · 记忆 · MCP</button>
                </div>
                <StateMachineCanvas graph={graphView === "agents" ? agentGraph : runtimeGraph} />
              </details>
              <details className="trace-event-log">
                <summary><strong>原始 Trace 事件</strong><span>{trace.length} 条 · 用于逐步审计</span></summary>
                <div>
                  {trace.map((event) => (
                    <article className={`trace-event trace-${event.event_type.split(".")[0]}`} key={event.id}>
                      <div className="trace-sequence">{String(event.sequence).padStart(2, "0")}</div>
                      <div className="trace-detail">
                        <div><span>{eventLabel(event.event_type)}</span><time>{new Date(event.occurred_at).toLocaleTimeString()}</time></div>
                        <strong>{event.agent_id ? agentLabel(event.agent_id) : event.name}</strong>
                        <p>{event.summary || "无公开摘要"}</p>
                        {Object.keys(event.attributes).length > 0 && (
                          <details><summary>结构化属性</summary><pre>{JSON.stringify(event.attributes, null, 2)}</pre></details>
                        )}
                      </div>
                      <span className={`trace-status status-${event.status ?? "unknown"}`}>
                        {statusLabel(event.status ?? "--")}
                      </span>
                    </article>
                  ))}
                </div>
              </details>
            </div>
          )}
        </div>
      </aside>
  );
}
