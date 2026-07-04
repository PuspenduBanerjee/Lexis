import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import { ALL_TARGETS, SQL_TARGETS, type ModelDetailOut, type Target } from "../api/types";
import { fieldRefs } from "../lib/fieldRefs";

export function TranspileView({ model }: { model: ModelDetailOut }) {
  const [target, setTarget] = useState<Target>("duckdb");
  const [metric, setMetric] = useState(model.metrics[0]?.name ?? "");
  const [groupBy, setGroupBy] = useState<string[]>([]);
  const isSql = (SQL_TARGETS as string[]).includes(target);
  const refs = fieldRefs(model);

  const mutation = useMutation({
    mutationFn: () =>
      api.transpile(model.id, {
        target,
        metric: isSql ? metric : undefined,
        group_by: isSql && groupBy.length > 0 ? groupBy : undefined,
      }),
  });

  return (
    <div className="stack">
      <div className="row">
        <label>
          Target{" "}
          <select value={target} onChange={(e) => setTarget(e.target.value as Target)}>
            {ALL_TARGETS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>

        {isSql && (
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

        <button className="primary" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
          {mutation.isPending ? "Transpiling…" : "Transpile"}
        </button>
      </div>

      {isSql && (
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
      )}

      {mutation.isError && (
        <p className="error">
          {mutation.error instanceof ApiError ? JSON.stringify(mutation.error.detail) : String(mutation.error)}
        </p>
      )}

      {mutation.data && (
        <div className="stack">
          {mutation.data.warnings.map((w, i) => (
            <p key={i} className="error">
              warning: {w}
            </p>
          ))}
          <pre>{mutation.data.content}</pre>
        </div>
      )}
    </div>
  );
}
