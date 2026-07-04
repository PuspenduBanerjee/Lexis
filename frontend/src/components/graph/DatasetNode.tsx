import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { GraphDatasetIn } from "../../api/types";

export type DatasetNodeData = { dataset: GraphDatasetIn };

export function DatasetNode({ data, selected }: NodeProps & { data: DatasetNodeData }) {
  const { dataset } = data;
  return (
    <div
      style={{
        border: `2px solid ${selected ? "var(--accent)" : "var(--border)"}`,
        borderRadius: 6,
        background: "var(--bg)",
        minWidth: 200,
        fontSize: 13,
      }}
    >
      <Handle type="target" position={Position.Left} />
      <div style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>
        {dataset.name}
      </div>
      <div style={{ padding: "6px 10px" }}>
        <div className="muted" style={{ marginBottom: 4 }}>
          {dataset.source}
        </div>
        <div className="muted">{dataset.fields.length} field(s)</div>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
