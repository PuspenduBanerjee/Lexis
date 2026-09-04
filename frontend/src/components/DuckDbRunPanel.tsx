import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { ModelDetailOut } from "../api/types";
import { fieldRefs } from "../lib/fieldRefs";
import { ResultsTable } from "./ResultsTable";
import { TimeSeriesPanel } from "./TimeSeriesPanel";

type QueryType = "metric" | "timeseries";
export type RunMode = "demo" | "upload" | "connection";

export function DuckDbRunPanel({ model }: { model: ModelDetailOut }) {
  const [mode, setMode] = useState<RunMode>("demo");
  const [queryType, setQueryType] = useState<QueryType>("metric");
  const [file, setFile] = useState<File | null>(null);
  const [connectionId, setConnectionId] = useState<number | undefined>(undefined);
  const { data: connections } = useQuery({
    queryKey: ["connections"],
    queryFn: api.listConnections,
    enabled: mode === "connection",
  });
  const exportMutation = useMutation({ mutationFn: api.exportDemoDataset });

  return (
    <div className="stack">
      <p className="muted">
        Executes the generated SQL for real, against a bundled TPC-DS demo dataset, an uploaded{" "}
        <code>.duckdb</code>/<code>.db</code> file, or a saved connection (see the{" "}
        <a href="/connections">Connections</a> page to manage those).
      </p>

      <div className="row">
        <label>
          <input type="radio" checked={mode === "demo"} onChange={() => setMode("demo")} /> Demo dataset
        </label>
        <label>
          <input type="radio" checked={mode === "upload"} onChange={() => setMode("upload")} /> Upload a
          .duckdb file
        </label>
        <label>
          <input
            type="radio"
            checked={mode === "connection"}
            onChange={() => setMode("connection")}
          />{" "}
          Saved connection
        </label>
      </div>

      {mode === "upload" && (
        <input type="file" accept=".duckdb,.db" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      )}

      {mode === "demo" && (
        <div className="row">
          <button onClick={() => exportMutation.mutate()} disabled={exportMutation.isPending}>
            {exportMutation.isPending ? "Exporting…" : "Export demo dataset (.duckdb)"}
          </button>
          <span className="muted">
            Downloads this dataset as a real file - upload it back above, or register it as a duckdb_file
            connection.
          </span>
          {exportMutation.isError && (
            <span className="error">
              {exportMutation.error instanceof ApiError
                ? JSON.stringify(exportMutation.error.detail)
                : String(exportMutation.error)}
            </span>
          )}
        </div>
      )}

      {mode === "connection" && (
        <div className="field-row">
          <label>
            Connection{" "}
            <select
              value={connectionId ?? ""}
              onChange={(e) => setConnectionId(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">Select a connection…</option>
              {connections?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.type})
                </option>
              ))}
            </select>
          </label>
          {connections && connections.length === 0 && (
            <span className="muted">
              No connections yet — create one on the <a href="/connections">Connections</a> page.
            </span>
          )}
        </div>
      )}

      <div className="row">
        <label>
          <input
            type="radio"
            checked={queryType === "metric"}
            onChange={() => setQueryType("metric")}
          />{" "}
          Metric query
        </label>
        <label>
          <input
            type="radio"
            checked={queryType === "timeseries"}
            onChange={() => setQueryType("timeseries")}
          />{" "}
          Time series (drill down / roll up)
        </label>
      </div>

      {queryType === "metric" ? (
        <MetricQueryPanel model={model} mode={mode} file={file} connectionId={connectionId} />
      ) : (
        <TimeSeriesPanel model={model} mode={mode} file={file} connectionId={connectionId} />
      )}
    </div>
  );
}

function MetricQueryPanel({
  model,
  mode,
  file,
  connectionId,
}: {
  model: ModelDetailOut;
  mode: RunMode;
  file: File | null;
  connectionId?: number;
}) {
  const [metric, setMetric] = useState(model.metrics[0]?.name ?? "");
  const [groupBy, setGroupBy] = useState<string[]>([]);
  const refs = fieldRefs(model);

  const mutation = useMutation({
    mutationFn: () =>
      api.runDuckDb(model.id, { mode, metric, groupBy, file: file ?? undefined, connectionId }),
  });

  return (
    <div className="stack">
      <div className="row">
        <label>
          Metric{" "}
          <select value={metric} onChange={(e) => setMetric(e.target.value)}>
            {model.metrics.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
        <button
          className="primary"
          disabled={
            mutation.isPending ||
            (mode === "upload" && !file) ||
            (mode === "connection" && !connectionId) ||
            !metric
          }
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Running…" : "Run"}
        </button>
      </div>

      <div className="field-row">
        <label>Group by (optional)</label>
        <select
          multiple
          size={Math.min(6, refs.length)}
          value={groupBy}
          onChange={(e) => setGroupBy(Array.from(e.target.selectedOptions, (o) => o.value))}
        >
          {refs.map((ref) => (
            <option key={ref} value={ref}>
              {ref}
            </option>
          ))}
        </select>
      </div>

      {mutation.isError && (
        <p className="error">
          {mutation.error instanceof ApiError ? JSON.stringify(mutation.error.detail) : String(mutation.error)}
        </p>
      )}

      {mutation.data && (
        <div className="stack">
          <pre>{mutation.data.sql}</pre>
          <ResultsTable result={mutation.data} />
        </div>
      )}
    </div>
  );
}
