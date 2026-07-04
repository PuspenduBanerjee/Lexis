import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { MetricOut } from "../../api/types";

export type MetricNodeData = { metric: MetricOut };

/** Read-only: metrics can't be created/edited/deleted from the canvas (see
 * TODO.md) - this node exists purely to show which datasets a metric's
 * expression spans, via its incoming reference edges. */
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
        textAlign: "center",
      }}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div style={{ fontWeight: 600 }}>{metric.name}</div>
      <div className="muted">metric</div>
    </div>
  );
}
