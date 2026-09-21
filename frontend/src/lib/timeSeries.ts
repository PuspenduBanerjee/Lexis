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

/** Candidates for the time-series drill/roll dimension - from `model.time_fields`
 * (see `ModelDetailOut.time_fields`), not a local scan of every `is_time` field:
 * the backend's `time_axis_refs` prefers fields with a real date/timestamp
 * datatype and only falls back to bare `is_time` fields when the model tags none,
 * so scanning `is_time` fields directly here could offer e.g. a `d_year` INTEGER
 * column that `DATE_TRUNC` can't actually bucket by. */
export function timeFields(model: ModelDetailOut): TimeFieldRef[] {
  return model.time_fields.map((ref) => {
    const [dataset, field] = ref.split(".", 2);
    return { dataset, field };
  });
}
