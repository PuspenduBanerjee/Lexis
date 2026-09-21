// Hand-written TS interfaces mirroring lexis_api/schemas.py. No codegen for v1 -
// keep these in sync manually when the backend schemas change.

export type Role = "admin" | "editor" | "viewer";

export interface UserOut {
  id: number;
  username: string;
  role: Role;
  // Set only for a Google-authenticated user (see lexis_api/deps.py); null for the
  // seeded dev-stub users. Its presence on `/api/users/me` is what UserContext uses
  // to tell a real signed-in identity apart from the local dev "Acting as" switcher.
  email: string | null;
}

export interface FieldOut {
  name: string;
  description: string | null;
  expression: string | null;
  is_time: boolean;
  datatype: string | null;
}

export interface DatasetOut {
  name: string;
  source: string;
  fields: FieldOut[];
}

export interface RelationshipOut {
  name: string;
  from_dataset: string;
  to: string;
  from_columns: string[];
  to_columns: string[];
}

export interface MetricOut {
  name: string;
  description: string | null;
  expression: string | null;
  referenced_datasets: string[];
  datatype: string | null;
  // `description` composed with ai_context (synonyms as "Also known as: ...",
  // examples as "Example questions: ..."), falling back to "Query the X metric."
  // when there's nothing to compose - the exact text a query_<metric> tool shows.
  // Use this (not the bare `description` above) wherever a description is shown
  // to an agent, so WebMCP and the MCP servers show identical text.
  tool_description: string;
  // `dataset.field` refs this specific metric may legally be grouped by - its
  // home fact's own fields plus the dimensions *that fact* reaches, not every
  // field in the model. Grouping a sales metric by a returns-only field (or
  // vice versa) fan-traps through a shared dimension join and is rejected
  // server-side; use this (not fieldRefs(model)) to avoid offering it at all.
  group_by: string[];
}

export interface ModelSummaryOut {
  id: number;
  name: string;
  owner_id: number;
  owner_username: string;
  dataset_count: number;
  metric_count: number;
  created_at: string;
  updated_at: string;
  // The model's plain (non-ai_context) description - see ModelDetailOut.instructions
  // for the richer ai_context text. Null when the model declares neither.
  description: string | null;
}

export interface ModelDetailOut extends ModelSummaryOut {
  raw_yaml: string;
  datasets: DatasetOut[];
  relationships: RelationshipOut[];
  metrics: MetricOut[];
  // Model-level ai_context (instructions/synonyms/examples) - e.g. "keep sales
  // and returns in separate queries". Null when the model declares none.
  instructions: string | null;
  // `dataset.field` refs usable as a time_grain query's time axis - prefer this
  // over scanning `datasets[].fields[].is_time` yourself (see lib/timeSeries.ts's
  // `timeFields`), which can't tell a real date column from e.g. a `d_year`
  // INTEGER field also marked is_time, and so can list fields that don't actually
  // work as a time_grain axis.
  time_fields: string[];
}

export interface CreateModelIn {
  name?: string | null;
  yaml_text: string;
}

export interface UpdateModelIn {
  yaml_text: string;
}

export interface ImportSmlOut {
  model: ModelDetailOut;
  warnings: string[];
}

export type Target =
  | "duckdb"
  | "postgres"
  | "bigquery"
  | "databricks"
  | "snowflake"
  | "cube"
  | "dbt"
  | "mcp"
  | "snowflake_semantic_view"
  | "sml";

export const SQL_TARGETS: Target[] = ["duckdb", "postgres", "bigquery", "databricks", "snowflake"];
export const ALL_TARGETS: Target[] = [...SQL_TARGETS, "cube", "dbt", "mcp", "snowflake_semantic_view", "sml"];

export interface TranspileIn {
  target: Target;
  metric?: string | null;
  group_by?: string[] | null;
}

export interface TranspileOut {
  // `sml` is the one multi-file target - one YAML file per SML object - so
  // `content` is a `Record<string, string>` (relative filename -> content) there;
  // every other target still returns a single `string`.
  content: string | Record<string, string>;
  warnings: string[];
}

export interface RunDuckDbOut {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  sql: string;
  // True when there were more rows than the server's cap and `rows` was cut off
  // there - narrow the query (e.g. a coarser time_grain or fewer group_by refs)
  // rather than assume this is the complete result.
  truncated: boolean;
}

export interface GraphFieldIn {
  name: string;
  expression: string;
  description?: string | null;
}

export interface GraphDatasetIn {
  name: string;
  source: string;
  fields: GraphFieldIn[];
}

export interface GraphRelationshipIn {
  name: string;
  from_dataset: string;
  to: string;
  from_columns: string[];
  to_columns: string[];
}

export interface GraphMetricIn {
  name: string;
  expression: string;
  description?: string | null;
}

export interface GraphEditIn {
  datasets: GraphDatasetIn[];
  relationships: GraphRelationshipIn[];
  metrics: GraphMetricIn[];
}

export type ConnectionType = "duckdb_file" | "snowflake";

export interface ConnectionOut {
  id: number;
  name: string;
  type: ConnectionType;
  owner_id: number;
  owner_username: string;
  config: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export interface ConnectionIn {
  name: string;
  type: ConnectionType;
  config: Record<string, string>;
}

export interface ConnectionTestOut {
  ok: boolean;
  detail: string;
}
