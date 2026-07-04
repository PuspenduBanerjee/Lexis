import dagre from "@dagrejs/dagre";

const NODE_WIDTH = 220;
const NODE_HEIGHT = 100;
const METRIC_WIDTH = 170;
const METRIC_HEIGHT = 56;

/** Prefix used for metric node ids in the returned position map, so callers can
 * look up `metricNodeId(metric.name)` without this module needing to know about
 * React Flow's node-id scheme. */
export function metricNodeId(metricName: string): string {
  return `metric:${metricName}`;
}

/** Auto-layout: computes node positions from the relationship graph via dagre.
 * No persistence yet (see TODO.md) - recomputed fresh every time a model loads.
 *
 * Metrics are laid out as extra nodes downstream (to the right, since layout is
 * LR) of every dataset their expression references - a `dataset -> metric` edge
 * per reference is fed into the same dagre graph as the real relationship edges
 * so metric nodes never land on top of a dataset they point to, even though
 * they're rendered/styled completely differently by the caller. */
export function computeLayout(
  datasetNames: string[],
  edges: { from: string; to: string }[],
  metrics: { name: string; referencedDatasets: string[] }[] = [],
): Record<string, { x: number; y: number }> {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 80 });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const name of datasetNames) {
    graph.setNode(name, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    if (datasetNames.includes(edge.from) && datasetNames.includes(edge.to)) {
      graph.setEdge(edge.from, edge.to);
    }
  }
  for (const metric of metrics) {
    const nodeId = metricNodeId(metric.name);
    graph.setNode(nodeId, { width: METRIC_WIDTH, height: METRIC_HEIGHT });
    for (const dataset of metric.referencedDatasets) {
      if (datasetNames.includes(dataset)) {
        graph.setEdge(dataset, nodeId);
      }
    }
  }

  dagre.layout(graph);

  const positions: Record<string, { x: number; y: number }> = {};
  for (const name of datasetNames) {
    const node = graph.node(name);
    positions[name] = { x: node.x - NODE_WIDTH / 2, y: node.y - NODE_HEIGHT / 2 };
  }
  for (const metric of metrics) {
    const nodeId = metricNodeId(metric.name);
    const node = graph.node(nodeId);
    positions[nodeId] = { x: node.x - METRIC_WIDTH / 2, y: node.y - METRIC_HEIGHT / 2 };
  }
  return positions;
}
