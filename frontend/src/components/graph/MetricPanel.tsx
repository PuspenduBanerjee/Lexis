import type { GraphMetricIn, ModelDetailOut } from "../../api/types";
import { timeFields } from "../../lib/timeSeries";
import { TimeSeriesPanel } from "../TimeSeriesPanel";

interface Props {
  metric: GraphMetricIn;
  model: ModelDetailOut;
  onChange: (updated: GraphMetricIn) => void;
  onDelete: () => void;
}

export function MetricPanel({ metric, model, onChange, onDelete }: Props) {
  // The time-series preview queries this metric by name against the live API, so
  // it only works once the metric (and any expression edits) has actually been
  // saved - not for a brand-new node still sitting unsaved in the canvas.
  const isSaved = model.metrics.some((m) => m.name === metric.name);

  return (
    <div className="card stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{metric.name}</strong>
        <button onClick={onDelete}>Delete metric</button>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        Name can't be changed after creation.
      </p>

      <div className="field-row">
        <label>
          Expression (ANSI_SQL)
          <textarea
            rows={2}
            value={metric.expression}
            onChange={(e) => onChange({ ...metric, expression: e.target.value })}
          />
        </label>
      </div>

      <div className="field-row">
        <label>
          Description
          <input
            type="text"
            value={metric.description ?? ""}
            onChange={(e) => onChange({ ...metric, description: e.target.value || null })}
          />
        </label>
      </div>

      {timeFields(model).length > 0 &&
        (isSaved ? (
          <div className="field-row">
            <label>Time-series preview (bundled demo dataset, reflects the last saved version)</label>
            <TimeSeriesPanel model={model} mode="demo" file={null} fixedMetric={metric.name} />
          </div>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            Save the graph to see this metric's time-series preview.
          </p>
        ))}
    </div>
  );
}
