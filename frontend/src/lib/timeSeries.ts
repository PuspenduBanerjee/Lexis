import type { ModelDetailOut } from "../api/types";

export type TimeGrain = "year" | "quarter" | "month" | "week" | "day";

/** Coarsest first - mirrors `SqlDialectEmitter.TIME_GRAINS` in the backend.
 * `week` is an ISO 8601 week (Monday start); drilling month → week → day works
 * because a week bucket's period value is its Monday, a valid `filter_value`. */
export const TIME_GRAINS: TimeGrain[] = ["year", "quarter", "month", "week", "day"];

export function finerGrain(grain: TimeGrain): TimeGrain | null {
  const i = TIME_GRAINS.indexOf(grain);
  return i < TIME_GRAINS.length - 1 ? TIME_GRAINS[i + 1] : null;
}

export function coarserGrain(grain: TimeGrain): TimeGrain | null {
  const i = TIME_GRAINS.indexOf(grain);
  return i > 0 ? TIME_GRAINS[i - 1] : null;
}

export interface TimeFieldRef {
  dataset: string;
  field: string;
}

/** Every field marked `is_time` across a model's datasets - candidates for the
 * time-series drill/roll dimension. */
export function timeFields(model: ModelDetailOut): TimeFieldRef[] {
  return model.datasets.flatMap((d) =>
    d.fields.filter((f) => f.is_time).map((f) => ({ dataset: d.name, field: f.name })),
  );
}
