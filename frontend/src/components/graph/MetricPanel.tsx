import type { MetricOut, ModelDetailOut } from "../../api/types";
import { TimeSeriesPanel } from "../TimeSeriesPanel";
import { timeFields } from "../../lib/timeSeries";

export function MetricPanel({ metric, model }: { metric: MetricOut; model: ModelDetailOut }) {
  return (
    <div className="card stack">
      <strong>{metric.name}</strong>
      <p className="muted" style={{ margin: 0 }}>
        Metrics are read-only on the canvas — edit via the YAML sub-view.
      </p>
      {metric.description && <p style={{ margin: 0 }}>{metric.description}</p>}
      <div className="field-row">
        <label>Expression (ANSI_SQL)</label>
        <pre>{metric.expression ?? "(no expression available)"}</pre>
      </div>
      <div className="field-row">
        <label>References</label>
        <div>{metric.referenced_datasets.join(", ") || "(none detected)"}</div>
      </div>
      {timeFields(model).length > 0 && (
        <div className="field-row">
          <label>Time-series preview (bundled demo dataset)</label>
          <TimeSeriesPanel model={model} mode="demo" file={null} fixedMetric={metric.name} />
        </div>
      )}
    </div>
  );
}
