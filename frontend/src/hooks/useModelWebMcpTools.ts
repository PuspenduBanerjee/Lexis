import { useMemo } from "react";
import { api } from "../api/client";
import type { ModelDetailOut } from "../api/types";
import { fieldRefs } from "../lib/fieldRefs";
import { resolveTimeField, timeBucketingProperties } from "../lib/webmcpMetrics";
import { useWebMcpTools, type WebMcpTool } from "../lib/webmcp";

/** One `query_<metric>` WebMCP tool per metric in `model`, mirroring the
 * backend's per-model MCP endpoint (`/api/models/{id}/mcp`, see
 * `lexis.mcp_server.build_server` / `lexis.transpilers.mcp.build_metric_tool_specs`).
 * That endpoint fixes model *and* connection at connect time, via a server-held
 * MCP session; a page has no equivalent session, so each tool call here takes
 * `connection_id` as an explicit argument instead - the one deliberate schema
 * difference from the backend's per-model tools. Registered for as long as
 * `model`'s detail page stays mounted (see `ModelDetailPage`); a no-op while
 * `model` hasn't loaded yet. */
export function useModelWebMcpTools(model: ModelDetailOut | undefined): void {
  const tools = useMemo<WebMcpTool[]>(() => {
    if (!model) return [];
    const dimensionRefs = fieldRefs(model);
    const timeProperties = timeBucketingProperties(model);

    return model.metrics.map((metric): WebMcpTool => ({
      name: `query_${metric.name}`,
      description: metric.description || `Query the ${metric.name} metric.`,
      inputSchema: {
        type: "object",
        properties: {
          connection_id: { type: "integer", description: "a connection id from the Connections page" },
          group_by: {
            type: "array",
            items: { type: "string", enum: dimensionRefs },
            description: "Zero or more dataset.field references to group results by.",
          },
          ...timeProperties,
        },
        required: ["connection_id"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const connectionId = Number(input.connection_id);
        const groupBy = (input.group_by as string[] | undefined) ?? [];
        const timeGrain = input.time_grain as string | undefined;

        if (timeGrain) {
          if (groupBy.length > 0) {
            throw new Error("time_grain and group_by cannot be combined in one query yet");
          }
          const field = resolveTimeField(model, input.time_field as string | undefined);
          return api.runTimeSeries(model.id, {
            mode: "connection",
            connectionId,
            metric: metric.name,
            timeDataset: field.dataset,
            timeField: field.field,
            grain: timeGrain,
          });
        }
        return api.runDuckDb(model.id, {
          mode: "connection",
          connectionId,
          metric: metric.name,
          groupBy,
        });
      },
    }));
  }, [model]);

  useWebMcpTools(tools);
}
