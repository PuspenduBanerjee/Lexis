import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { GraphMetricIn } from "../../api/types";

export type MetricNodeData = { metric: GraphMetricIn };

/** Click to open MetricPanel for editing (name/expression/description) or
 * deletion. Incoming dashed edges (see GraphEditor's `buildMetricEdges`) are
 * recomputed live from this node's own `expression`, so they track edits as
 * they're typed rather than only refreshing after a save. */
export function MetricNode({ data, selected }: NodeProps & { data: MetricNodeData }) {
  const { metric } = data;
  return (
    <div
      style={{
        border: `2px dashed ${selected ? "var(--accent)" : "var(--border)"}`,
        borderRadius: 999,
        background: "var(--bg-alt)",
        minWidth: 150,
        padding: "8px 14px",
        fontSize: 13,
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <span
        aria-hidden="true"
        style={{
          width: 20,
          height: 20,
          flexShrink: 0,
          borderRadius: "50%",
          background: "var(--metric-accent-soft)",
          color: "var(--metric-accent)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 11,
          fontWeight: 700,
        }}
      >
        Σ
      </span>
      <span>
        <div style={{ fontWeight: 600 }}>{metric.name}</div>
        <div className="muted">metric</div>
      </span>
    </div>
  );
}
