import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { MachineNode as MachineNodeType, MachineStatus } from "./types";

const STATUS_LABEL: Record<MachineStatus, string> = {
  pending: "等待",
  ready: "就绪",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  unavailable: "不可用",
};

const CATEGORY_ICON: Record<string, string> = {
  workflow: "WF",
  agent: "AG",
  gate: "GT",
  harness: "HR",
  memory: "MM",
  mcp: "MC",
  search: "SE",
  model: "AI",
  trace: "TR",
  skill: "SK",
  tool: "TL",
  cost: "¥",
  input: "IN",
  output: "OUT",
};

export function MachineNode({ data, selected }: NodeProps<MachineNodeType>) {
  return (
    <div
      className={`machine-node machine-node-${data.status}${selected ? " selected" : ""}`}
      data-status={data.status}
    >
      <Handle className="machine-handle" position={Position.Left} type="target" />
      <div className="machine-node-heading">
        <span className="machine-node-icon">{CATEGORY_ICON[data.category] ?? "·"}</span>
        <div>
          <small>{data.category.toUpperCase()}</small>
          <strong>{data.label}</strong>
        </div>
        <span className="machine-node-status"><i />{STATUS_LABEL[data.status]}</span>
      </div>
      <p>{data.summary}</p>
      <footer>
        {data.badge && <span>{data.badge}</span>}
        {data.occurredAt && <time>{new Date(data.occurredAt).toLocaleTimeString()}</time>}
      </footer>
      <Handle className="machine-handle" position={Position.Right} type="source" />
    </div>
  );
}
