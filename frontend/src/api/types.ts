// Hand-written TS interfaces mirroring semantica_api/schemas.py. No codegen for v1 -
// keep these in sync manually when the backend schemas change.

export type Role = "admin" | "editor" | "viewer";

export interface UserOut {
  id: number;
  username: string;
  role: Role;
}

export interface FieldOut {
  name: string;
  description: string | null;
  expression: string | null;
  is_time: boolean;
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
}

export interface ModelDetailOut extends ModelSummaryOut {
  raw_yaml: string;
  datasets: DatasetOut[];
  relationships: RelationshipOut[];
  metrics: MetricOut[];
}

export interface CreateModelIn {
  name?: string | null;
  yaml_text: string;
}

export interface UpdateModelIn {
  yaml_text: string;
}

export type Target =
  | "duckdb"
  | "postgres"
  | "bigquery"
  | "databricks"
  | "snowflake"
  | "cube"
  | "dbt"
  | "mcp";

export const SQL_TARGETS: Target[] = ["duckdb", "postgres", "bigquery", "databricks", "snowflake"];
export const ALL_TARGETS: Target[] = [...SQL_TARGETS, "cube", "dbt", "mcp"];

export interface TranspileIn {
  target: Target;
  metric?: string | null;
  group_by?: string[] | null;
}

export interface TranspileOut {
  content: string;
  warnings: string[];
}

export interface RunDuckDbOut {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  sql: string;
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

export interface GraphEditIn {
  datasets: GraphDatasetIn[];
  relationships: GraphRelationshipIn[];
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
