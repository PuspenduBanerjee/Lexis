import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ModelDetailOut, RunDuckDbOut } from "../api/types";
import { TIME_GRAINS, finerGrain, timeFields, type TimeGrain } from "../lib/timeSeries";

interface Step {
  grain: TimeGrain;
  filterGrain?: TimeGrain;
  filterValue?: string;
}

export function TimeSeriesPanel({
  model,
  mode,
  file,
  fixedMetric,
}: {
  model: ModelDetailOut;
  mode: "demo" | "upload";
  file: File | null;
  /** If set, locks the metric (hides the picker) - used for the Design tab's
   * per-metric preview, where the metric is already implied by which node is selected. */
  fixedMetric?: string;
}) {
  const fields = timeFields(model);
  const [metric, setMetric] = useState(fixedMetric ?? model.metrics[0]?.name ?? "");
  const [fieldKey, setFieldKey] = useState(fields[0] ? `${fields[0].dataset}.${fields[0].field}` : "");
  const [topGrain, setTopGrain] = useState<TimeGrain>("year");
  const [history, setHistory] = useState<Step[]>([{ grain: "year" }]);

  const field = fields.find((f) => `${f.dataset}.${f.field}` === fieldKey);
  const current = history[history.length - 1];

  const mutation = useMutation({
    mutationFn: (step: Step) => {
      if (!field) throw new Error("no time field selected");
      return api.runTimeSeries(model.id, {
        mode,
        file: file ?? undefined,
        metric,
        timeDataset: field.dataset,
        timeField: field.field,
        grain: step.grain,
        filterGrain: step.filterGrain,
        filterValue: step.filterValue,
      });
    },
  });

  const run = (step: Step) => mutation.mutate(step);

  const start = () => {
    const step: Step = { grain: topGrain };
    setHistory([step]);
    run(step);
  };

  // Auto-run once for the fixed-metric preview (Design tab) so opening a metric's
  // panel shows something immediately, without requiring an extra click.
  useEffect(() => {
    if (fixedMetric && field) start();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only
  }, []);

  const drillInto = (periodValue: string) => {
    const next = finerGrain(current.grain);
    if (!next) return;
    const step: Step = { grain: next, filterGrain: current.grain, filterValue: periodValue.slice(0, 10) };
    setHistory((h) => [...h, step]);
    run(step);
  };

  const rollUp = () => {
    if (history.length <= 1) return;
    const popped = history.slice(0, -1);
    setHistory(popped);
    run(popped[popped.length - 1]);
  };

  const canDrill = finerGrain(current.grain) !== null;
  const canRollUp = history.length > 1;

  if (fields.length === 0) {
    return (
      <p className="muted">
        No fields are marked as a time dimension (<code>dimension.is_time: true</code>) in this model, so
        there's no time series to build.
      </p>
    );
  }

  return (
    <div className="stack">
      <div className="row">
        {fixedMetric ? (
          <span className="muted">Metric: {fixedMetric}</span>
        ) : (
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
        )}
        <label>
          Time field{" "}
          <select value={fieldKey} onChange={(e) => setFieldKey(e.target.value)}>
            {fields.map((f) => (
              <option key={`${f.dataset}.${f.field}`} value={`${f.dataset}.${f.field}`}>
                {f.dataset}.{f.field}
              </option>
            ))}
          </select>
        </label>
        <label>
          Starting grain{" "}
          <select value={topGrain} onChange={(e) => setTopGrain(e.target.value as TimeGrain)}>
            {TIME_GRAINS.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </label>
        <button className="primary" disabled={mutation.isPending || !metric || !field} onClick={start}>
          {mutation.isPending ? "Running…" : "Run"}
        </button>
        {canRollUp && (
          <button onClick={rollUp} disabled={mutation.isPending}>
            Roll up
          </button>
        )}
      </div>

      <p className="muted" style={{ margin: 0 }}>
        {canDrill ? "Click a row to drill into the next finer grain. " : ""}
        Grain: {history.map((s) => s.grain).join(" → ")}
      </p>

      {mutation.isError && (
        <p className="error">
          {mutation.error instanceof ApiError ? JSON.stringify(mutation.error.detail) : String(mutation.error)}
        </p>
      )}

      {mutation.data && <TimeSeriesTable result={mutation.data} canDrill={canDrill} onDrill={drillInto} />}
    </div>
  );
}

function TimeSeriesTable({
  result,
  canDrill,
  onDrill,
}: {
  result: RunDuckDbOut;
  canDrill: boolean;
  onDrill: (periodValue: string) => void;
}) {
  return (
    <div className="stack">
      <table>
        <thead>
          <tr>
            {result.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr
              key={i}
              onClick={canDrill ? () => onDrill(String(row[0])) : undefined}
              style={canDrill ? { cursor: "pointer" } : undefined}
              title={canDrill ? "Click to drill down" : undefined}
            >
              {row.map((cell, j) => (
                <td key={j}>{j === 0 ? String(cell).slice(0, 10) : String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">{result.row_count} row(s)</p>
    </div>
  );
}
