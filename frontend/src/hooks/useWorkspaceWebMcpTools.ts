import { useMemo } from "react";
import { api } from "../api/client";
import { fieldRefs } from "../lib/fieldRefs";
import { MCP_TIME_GRAINS, resolveTimeField, timeFieldRefs } from "../lib/webmcpMetrics";
import { useWebMcpTools, type WebMcpTool } from "../lib/webmcp";

/** Workspace-wide WebMCP tools - `list_models` / `list_connections` /
 * `list_metrics` / `query_metric` - mirroring the tool set the backend's
 * workspace-wide MCP endpoint exposes (`/api/mcp`, see
 * `lexis_api.mcp_workspace.build_workspace_server`), so an in-page AI agent gets
 * the same discover-then-query flow without a separate MCP connection. Executes
 * over the existing REST endpoints (not the MCP wire protocol) since that's what
 * this app already calls from the browser; only the tool names/schemas are kept
 * aligned with the backend's. Meant to be registered once, for the app's
 * lifetime (see `App.tsx`). */
export function useWorkspaceWebMcpTools(): void {
  const tools = useMemo<WebMcpTool[]>(
    () => [
      {
        name: "list_models",
        description: "List every semantic model available in this Lexis workspace.",
        inputSchema: { type: "object", properties: {}, additionalProperties: false },
        execute: async () => {
          const models = await api.listModels();
          return {
            models: models.map((m) => ({
              id: m.id,
              name: m.name,
              dataset_count: m.dataset_count,
              metric_count: m.metric_count,
            })),
          };
        },
      },
      {
        name: "list_connections",
        description: "List every data connection available to run queries against.",
        inputSchema: { type: "object", properties: {}, additionalProperties: false },
        execute: async () => {
          const connections = await api.listConnections();
          return { connections: connections.map((c) => ({ id: c.id, name: c.name, type: c.type })) };
        },
      },
      {
        name: "list_metrics",
        description:
          "List a model's metrics - name, description, and valid group_by references - before " +
          "calling query_metric against it.",
        inputSchema: {
          type: "object",
          properties: { model_id: { type: "integer", description: "a model id from list_models" } },
          required: ["model_id"],
          additionalProperties: false,
        },
        execute: async (input) => {
          const model = await api.getModel(Number(input.model_id));
          return {
            metrics: model.metrics.map((m) => ({
              name: m.name,
              description: m.description,
              group_by: fieldRefs(model),
            })),
            time_grains: MCP_TIME_GRAINS,
            time_fields: timeFieldRefs(model),
          };
        },
      },
      {
        name: "query_metric",
        description:
          "Run a metric query against a specific model and connection: either a single total " +
          "(optionally grouped by dimension references) or, with time_grain, one row per " +
          "consecutive time period. Call list_models, list_connections, and list_metrics first to " +
          "find valid ids/names and valid group_by / time_field values.",
        inputSchema: {
          type: "object",
          properties: {
            model_id: { type: "integer", description: "a model id from list_models" },
            metric: { type: "string", description: "a metric name from list_metrics" },
            connection_id: { type: "integer", description: "a connection id from list_connections" },
            group_by: {
              type: "array",
              items: { type: "string" },
              description: "dataset.field references to group by - see list_metrics for valid ones",
            },
            time_grain: {
              type: "string",
              enum: MCP_TIME_GRAINS,
              description:
                "Bucket the metric into consecutive periods instead of one total (e.g. 'week'). " +
                "Cannot be combined with group_by.",
            },
            time_field: {
              type: "string",
              description: "dataset.field date axis for time_grain - see list_metrics (time_fields)",
            },
          },
          required: ["model_id", "metric", "connection_id"],
          additionalProperties: false,
        },
        execute: async (input) => {
          const modelId = Number(input.model_id);
          const metric = String(input.metric);
          const connectionId = Number(input.connection_id);
          const groupBy = (input.group_by as string[] | undefined) ?? [];
          const timeGrain = input.time_grain as string | undefined;

          const model = await api.getModel(modelId);
          if (!model.metrics.some((m) => m.name === metric)) {
            throw new Error(`unknown metric ${JSON.stringify(metric)} for model ${modelId}`);
          }

          if (timeGrain) {
            if (groupBy.length > 0) {
              throw new Error("time_grain and group_by cannot be combined in one query yet");
            }
            const field = resolveTimeField(model, input.time_field as string | undefined);
            return api.runTimeSeries(modelId, {
              mode: "connection",
              connectionId,
              metric,
              timeDataset: field.dataset,
              timeField: field.field,
              grain: timeGrain,
            });
          }
          return api.runDuckDb(modelId, { mode: "connection", connectionId, metric, groupBy });
        },
      },
    ],
    [],
  );

  useWebMcpTools(tools);
}
