// Shared building blocks for this app's `query_<metric>`-shaped WebMCP tools -
// used by both `useWorkspaceWebMcpTools` and `useModelWebMcpTools`, the same way
// `lexis.transpilers.mcp` is shared by the backend's per-model and workspace MCP
// servers (`lexis.mcp_server` / `lexis_api.mcp_workspace`).
import type { ModelDetailOut } from "../api/types";
import { timeFields, type TimeFieldRef } from "./timeSeries";

// Fine -> coarse, matching `lexis.transpilers.mcp.TIME_GRAINS` (the schema this
// module's tool specs mirror) - the opposite order from `timeSeries.ts`'s
// drill-down UI, which lists coarse -> fine on purpose for that separate use case.
export const MCP_TIME_GRAINS = ["day", "week", "month", "quarter", "year"] as const;

export function timeFieldRefs(model: ModelDetailOut): string[] {
  return timeFields(model).map((f) => `${f.dataset}.${f.field}`);
}

/** `time_field` tool argument -> `{dataset, field}`, mirroring the backend's
 * `lexis.transpilers.mcp.resolve_time_axis`: use the ref given (validated
 * against `timeFields`), or the model's sole time field when there's exactly one
 * and none was given. Throws (as a clean tool-call error) otherwise. */
export function resolveTimeField(model: ModelDetailOut, timeField: string | undefined): TimeFieldRef {
  const refs = timeFields(model);
  if (refs.length === 0) {
    throw new Error("this model has no date field to bucket by, so time_grain is not supported");
  }
  if (timeField == null) {
    if (refs.length > 1) {
      throw new Error(
        `time_field is required when time_grain is set; choose one of ${timeFieldRefs(model).join(", ")}`,
      );
    }
    return refs[0];
  }
  const match = refs.find((f) => `${f.dataset}.${f.field}` === timeField);
  if (!match) {
    throw new Error(`unknown time_field ${JSON.stringify(timeField)}; choose one of ${timeFieldRefs(model).join(", ")}`);
  }
  return match;
}

/** `{time_grain, time_field}` input-schema properties, added to a `query_<metric>`
 * tool only when the model has at least one usable time field - mirrors
 * `lexis.transpilers.mcp._time_bucketing_properties`. */
export function timeBucketingProperties(model: ModelDetailOut): Record<string, unknown> {
  const refs = timeFieldRefs(model);
  if (refs.length === 0) return {};
  const defaultHint =
    refs.length === 1
      ? ` Defaults to ${JSON.stringify(refs[0])}.`
      : " Required when time_grain is set (the model has more than one time field).";
  return {
    time_grain: {
      type: "string",
      enum: MCP_TIME_GRAINS,
      description:
        "Return one row per consecutive time period instead of a single total - e.g. 'week' for a " +
        "week-by-week trend. Cannot be combined with group_by.",
    },
    time_field: {
      type: "string",
      enum: refs,
      description: "Which date field to bucket by when time_grain is set." + defaultHint,
    },
  };
}
