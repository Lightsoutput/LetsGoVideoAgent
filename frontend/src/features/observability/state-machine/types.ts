import type { Edge, Node } from "@xyflow/react";

export type MachineStatus =
  | "pending"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "unavailable";

export interface MachineNodeData extends Record<string, unknown> {
  label: string;
  category: string;
  status: MachineStatus;
  summary: string;
  occurredAt?: string;
  badge?: string;
}

export type MachineNode = Node<MachineNodeData, "machine">;
export type MachineEdge = Edge<Record<string, unknown>>;

export interface MachineGraph {
  nodes: MachineNode[];
  edges: MachineEdge[];
  title: string;
  description: string;
}
