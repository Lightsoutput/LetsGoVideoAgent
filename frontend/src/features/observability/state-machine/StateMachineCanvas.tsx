"use client";

import { useEffect, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  useNodesInitialized,
  useReactFlow,
  type NodeTypes,
} from "@xyflow/react";

import { MachineNode } from "./MachineNode";
import type { MachineGraph, MachineNode as MachineNodeType } from "./types";

interface StateMachineCanvasProps {
  graph: MachineGraph;
}

const NODE_TYPES: NodeTypes = { machine: MachineNode };

function GraphAutoFit({ nodes }: { nodes: MachineNodeType[] }) {
  const flow = useReactFlow();
  const nodesInitialized = useNodesInitialized();
  const signature = nodes.map((node) => `${node.id}:${node.data.status}`).join("|");

  useEffect(() => {
    if (!nodesInitialized) return;
    // 观测视图默认展示完整拓扑，不让镜头只追随活动节点而把上下游移出屏幕。
    // 节点状态变化时重新适配全图；用户无需拖动画布才能理解整体协作关系。
    const frame = window.requestAnimationFrame(() => {
      void flow.fitView({
        nodes,
        padding: 0.1,
        minZoom: 0.18,
        maxZoom: 0.9,
        duration: 420,
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [flow, nodes, nodesInitialized, signature]);
  return null;
}

export function StateMachineCanvas({ graph }: StateMachineCanvasProps) {
  const counts = useMemo(
    () => ({
      running: graph.nodes.filter((node) => node.data.status === "running").length,
      completed: graph.nodes.filter((node) => node.data.status === "completed").length,
      failed: graph.nodes.filter((node) => ["failed", "unavailable"].includes(node.data.status)).length,
    }),
    [graph.nodes],
  );

  return (
    <section className="state-machine-shell" aria-label={graph.title}>
      <header className="state-machine-header">
        <div><strong>{graph.title}</strong><span>{graph.description}</span></div>
        <div className="machine-live-summary" aria-live="polite">
          <span className="running"><i />{counts.running} 运行中</span>
          <span className="completed"><i />{counts.completed} 完成</span>
          {counts.failed > 0 && <span className="failed"><i />{counts.failed} 异常</span>}
        </div>
      </header>
      <div className="state-machine-canvas">
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={NODE_TYPES}
          nodesConnectable={false}
          nodesDraggable={false}
          minZoom={0.28}
          maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
        >
          <GraphAutoFit nodes={graph.nodes} />
          <Background color="rgba(120, 157, 183, .16)" gap={22} size={1} variant={BackgroundVariant.Dots} />
          <Controls position="bottom-left" showInteractive={false} />
        </ReactFlow>
      </div>
      <footer className="machine-legend">
        <span className="ready"><i />已就绪</span>
        <span className="running"><i />正在调用</span>
        <span className="completed"><i />本次已完成</span>
        <span className="pending"><i />尚未进入</span>
        <small>默认适配全部节点 · 右下角拖动缩略图已移除 · 此拓扑只用于技术排障</small>
      </footer>
    </section>
  );
}
