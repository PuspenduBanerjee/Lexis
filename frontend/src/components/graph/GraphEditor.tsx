import {
  addEdge,
  Background,
  Controls,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { GraphDatasetIn, GraphRelationshipIn, ModelDetailOut } from "../../api/types";
import { computeLayout, metricNodeId } from "../../lib/layout";
import { DatasetNode, type DatasetNodeData } from "./DatasetNode";
import { DatasetPanel } from "./DatasetPanel";
import { MetricNode, type MetricNodeData } from "./MetricNode";
import { MetricPanel } from "./MetricPanel";

const nodeTypes = { dataset: DatasetNode, metric: MetricNode };

// Metric-reference edges (metric node -> the datasets its expression touches) are
// tagged by id prefix rather than a registered edge `type`, since they render with
// the default edge component (just dashed) and don't need one - this keeps the
// filtering below (save payload, show/hide toggle) a simple id check.
const METRIC_EDGE_PREFIX = "metric-ref:";

type DatasetNodeType = Node<DatasetNodeData, "dataset">;
type MetricNodeType = Node<MetricNodeData, "metric">;
type AnyNodeType = DatasetNodeType | MetricNodeType;

function isDatasetNode(n: AnyNodeType): n is DatasetNodeType {
  return n.type === "dataset";
}

function isMetricNode(n: AnyNodeType): n is MetricNodeType {
  return n.type === "metric";
}

interface RelationshipEdgeData extends Record<string, unknown> {
  from_columns: string[];
  to_columns: string[];
}

function toGraphDataset(d: ModelDetailOut["datasets"][number]): GraphDatasetIn {
  return {
    name: d.name,
    source: d.source,
    fields: d.fields.map((f) => ({ name: f.name, expression: f.expression ?? f.name, description: f.description })),
  };
}

function buildInitialNodes(model: ModelDetailOut): AnyNodeType[] {
  const datasets = model.datasets.map(toGraphDataset);
  const positions = computeLayout(
    datasets.map((d) => d.name),
    model.relationships.map((r) => ({ from: r.from_dataset, to: r.to })),
    model.metrics.map((m) => ({ name: m.name, referencedDatasets: m.referenced_datasets })),
  );
  const datasetNodes: DatasetNodeType[] = datasets.map((dataset) => ({
    id: dataset.name,
    type: "dataset",
    position: positions[dataset.name] ?? { x: 0, y: 0 },
    data: { dataset },
  }));
  const metricNodes: MetricNodeType[] = model.metrics.map((metric) => ({
    id: metricNodeId(metric.name),
    type: "metric",
    position: positions[metricNodeId(metric.name)] ?? { x: 0, y: 0 },
    data: { metric },
    deletable: false,
  }));
  return [...datasetNodes, ...metricNodes];
}

function buildInitialEdges(model: ModelDetailOut): Edge[] {
  const relationshipEdges: Edge<RelationshipEdgeData>[] = model.relationships.map((r) => ({
    id: r.name,
    source: r.from_dataset,
    target: r.to,
    label: `${r.from_columns.join(",")} = ${r.to_columns.join(",")}`,
    data: { from_columns: r.from_columns, to_columns: r.to_columns },
  }));
  const metricEdges: Edge[] = model.metrics.flatMap((metric) =>
    metric.referenced_datasets.map((dataset) => ({
      id: `${METRIC_EDGE_PREFIX}${metric.name}:${dataset}`,
      source: dataset,
      target: metricNodeId(metric.name),
      style: { strokeDasharray: "5 5" },
      selectable: false,
      deletable: false,
    })),
  );
  return [...relationshipEdges, ...metricEdges];
}

export function GraphEditor({ model }: { model: ModelDetailOut }) {
  const queryClient = useQueryClient();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-init when switching models, not on every model refetch
  const initialNodes = useMemo(() => buildInitialNodes(model), [model.id]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const initialEdges = useMemo(() => buildInitialEdges(model), [model.id]);
  const [nodes, setNodes, onNodesChange] = useNodesState<AnyNodeType>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showMetrics, setShowMetrics] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);

  // Fullscreen is a CSS overlay (not the browser Fullscreen API, which can be
  // blocked in embedded/iframed contexts) - so exiting via Escape and locking
  // background scroll are handled here instead of getting them for free.
  useEffect(() => {
    if (!fullscreen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [fullscreen]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const datasets: GraphDatasetIn[] = nodes.filter(isDatasetNode).map((n) => n.data.dataset);
      const relationships: GraphRelationshipIn[] = edges
        .filter((e) => !e.id.startsWith(METRIC_EDGE_PREFIX))
        .map((e) => {
          const data = e.data as RelationshipEdgeData | undefined;
          return {
            name: e.id,
            from_dataset: e.source,
            to: e.target,
            from_columns: data?.from_columns ?? [],
            to_columns: data?.to_columns ?? [],
          };
        });
      return api.updateModelGraph(model.id, { datasets, relationships });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["models", model.id] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null;
  const selectedDataset = selectedNode && isDatasetNode(selectedNode) ? selectedNode.data.dataset : null;
  const selectedMetric = selectedNode && isMetricNode(selectedNode) ? selectedNode.data.metric : null;

  const updateSelectedDataset = (updated: GraphDatasetIn) => {
    setNodes((prev) =>
      prev.map((n) => (n.id === selectedId && isDatasetNode(n) ? { ...n, data: { dataset: updated } } : n)),
    );
  };

  const deleteSelectedDataset = () => {
    if (!selectedId) return;
    setNodes((prev) => prev.filter((n) => n.id !== selectedId));
    setEdges((prev) => prev.filter((e) => e.source !== selectedId && e.target !== selectedId));
    setSelectedId(null);
  };

  const addDataset = () => {
    const name = window.prompt("New dataset name");
    if (!name) return;
    if (nodes.some((n) => n.id === name)) {
      window.alert(`A dataset named "${name}" already exists`);
      return;
    }
    const source = window.prompt("Source (database.schema.table)", `schema.${name}`);
    if (!source) return;
    // Place below the current lowest node so it never lands on top of an existing
    // one (which would make its connection handles unreachable for drag-to-connect).
    const belowY = nodes.length > 0 ? Math.max(...nodes.map((n) => n.position.y)) + 140 : 40;
    const newNode: DatasetNodeType = {
      id: name,
      type: "dataset",
      position: { x: 40, y: belowY },
      data: { dataset: { name, source, fields: [] } },
    };
    setNodes((prev) => [...prev, newNode]);
  };

  const onConnect = (connection: Connection) => {
    const name = window.prompt("Relationship name", `${connection.source}_to_${connection.target}`);
    if (!name) return;
    if (edges.some((e) => e.id === name)) {
      window.alert("A relationship with that name already exists");
      return;
    }
    const fromColumns = window.prompt(`Column(s) on ${connection.source} (comma-separated)`);
    if (!fromColumns) return;
    const toColumns = window.prompt(`Column(s) on ${connection.target} (comma-separated)`);
    if (!toColumns) return;

    const from_columns = fromColumns.split(",").map((s) => s.trim());
    const to_columns = toColumns.split(",").map((s) => s.trim());
    setEdges((prev) =>
      addEdge<Edge<RelationshipEdgeData>>(
        {
          ...connection,
          id: name,
          label: `${from_columns.join(",")} = ${to_columns.join(",")}`,
          data: { from_columns, to_columns },
        },
        prev as Edge<RelationshipEdgeData>[],
      ),
    );
  };

  const visibleNodes = showMetrics ? nodes : nodes.filter((n) => !isMetricNode(n));
  const visibleEdges = showMetrics ? edges : edges.filter((e) => !e.id.startsWith(METRIC_EDGE_PREFIX));

  const isValidConnection = (connection: Connection | Edge) => {
    const source = nodes.find((n) => n.id === connection.source);
    const target = nodes.find((n) => n.id === connection.target);
    return isDatasetNode(source as AnyNodeType) && isDatasetNode(target as AnyNodeType);
  };

  return (
    <div
      className="stack"
      style={
        fullscreen
          ? {
              position: "fixed",
              inset: 0,
              zIndex: 100,
              background: "var(--bg)",
              padding: 16,
              overflow: "auto",
            }
          : undefined
      }
    >
      <div className="row">
        <button onClick={addDataset}>+ Add dataset</button>
        <button className="primary" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
          {saveMutation.isPending ? "Saving…" : "Save graph"}
        </button>
        <label className="row" style={{ gap: 4 }}>
          <input
            type="checkbox"
            checked={showMetrics}
            onChange={(e) => {
              setShowMetrics(e.target.checked);
              if (!e.target.checked && selectedNode && isMetricNode(selectedNode)) setSelectedId(null);
            }}
          />
          Show metrics
        </label>
        <button onClick={() => setFullscreen((prev) => !prev)}>
          {fullscreen ? "Exit fullscreen" : "Fullscreen"}
        </button>
        {saveMutation.isSuccess && <span className="muted">Saved.</span>}
        {saveMutation.isError && (
          <span className="error">
            {saveMutation.error instanceof ApiError
              ? JSON.stringify(saveMutation.error.detail)
              : String(saveMutation.error)}
          </span>
        )}
      </div>

      <p className="muted" style={{ margin: 0 }}>
        Drag between the small dots on the left/right of a dataset box to create a relationship. Dashed
        edges point from a metric to every dataset its expression references (read-only — click a metric
        for details). Node positions aren't saved yet (auto-arranged on every load) — see TODO.md.
        {fullscreen && " Press Escape or “Exit fullscreen” to leave fullscreen."}
      </p>

      <div
        style={
          fullscreen
            ? { flex: 1, minHeight: 0, border: "1px solid var(--border)", borderRadius: 6 }
            : { height: 480, border: "1px solid var(--border)", borderRadius: 6 }
        }
      >
        <ReactFlow
          nodes={visibleNodes}
          edges={visibleEdges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onNodesDelete={(deleted) =>
            setEdges((prev) =>
              prev.filter((e) => !deleted.some((n) => n.id === e.source || n.id === e.target)),
            )
          }
          onNodeClick={(_, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId(null)}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>

      {selectedDataset && (
        <DatasetPanel dataset={selectedDataset} onChange={updateSelectedDataset} onDelete={deleteSelectedDataset} />
      )}
      {selectedMetric && <MetricPanel metric={selectedMetric} model={model} />}
    </div>
  );
}
