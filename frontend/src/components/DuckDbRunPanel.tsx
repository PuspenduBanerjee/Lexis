import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { ModelDetailOut } from "../api/types";
import { fieldRefs } from "../lib/fieldRefs";
import { ResultsTable } from "./ResultsTable";
import { TimeSeriesPanel } from "./TimeSeriesPanel";

type QueryType = "metric" | "timeseries";

export function DuckDbRunPanel({ model }: { model: ModelDetailOut }) {
  const [mode, setMode] = useState<"demo" | "upload">("demo");
  const [queryType, setQueryType] = useState<QueryType>("metric");
  const [file, setFile] = useState<File | null>(null);

  return (
    <div className="stack">
      <p className="muted">
        Executes the generated DuckDB SQL for real, either against a bundled TPC-DS demo dataset or an
        uploaded <code>.duckdb</code>/<code>.db</code> file.
      </p>

      <div className="row">
        <label>
          <input type="radio" checked={mode === "demo"} onChange={() => setMode("demo")} /> Demo dataset
        </label>
        <label>
          <input type="radio" checked={mode === "upload"} onChange={() => setMode("upload")} /> Upload a
          .duckdb file
        </label>
      </div>

      {mode === "upload" && (
        <input type="file" accept=".duckdb,.db" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
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
        <MetricQueryPanel model={model} mode={mode} file={file} />
      ) : (
        <TimeSeriesPanel model={model} mode={mode} file={file} />
      )}
    </div>
  );
}

function MetricQueryPanel({
  model,
  mode,
  file,
}: {
  model: ModelDetailOut;
  mode: "demo" | "upload";
  file: File | null;
}) {
  const [metric, setMetric] = useState(model.metrics[0]?.name ?? "");
  const [groupBy, setGroupBy] = useState<string[]>([]);
  const refs = fieldRefs(model);

  const mutation = useMutation({
    mutationFn: () =>
      api.runDuckDb(model.id, { mode, metric, groupBy, file: file ?? undefined }),
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
          disabled={mutation.isPending || (mode === "upload" && !file) || !metric}
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
