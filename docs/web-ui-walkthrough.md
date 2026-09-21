# Web UI walkthrough

Three GIFs of the web UI's core loop: edit a model visually, convert it to another
semantic layer format, and run a real query against it. All three are recorded
against the `retail_analytics` sample model that's seeded automatically on first run
(see "Quickstart: Web UI" in the [README](../README.md)).

## Model editor (Design tab)

Click a metric node on the graph canvas to open its panel (expression, description,
delete). Any metric on a field marked `dimension.is_time: true` also gets a live
time-series preview against the demo dataset — click a row to drill into the next
finer grain, "Roll up" to go back.

![Model editor: clicking a metric node, then drilling down and rolling up its time-series preview](media/model-editor-design.gif)

## Semantic model conversion (Transpile tab)

Transpiles the same Ossie model to a chosen target: warehouse SQL (DuckDB, Postgres,
BigQuery, Databricks, Snowflake) or another semantic layer's own format (Cube, dbt,
MCP tool manifests, Snowflake Semantic View, AtScale SML). Non-SQL targets return
multiple files, browsable in the file tree.

![Semantic model conversion: transpiling to DuckDB SQL, then to SML, then to a Snowflake Semantic View](media/semantic-model-conversion.gif)

## Semantic query execution (Test Metrics tab)

Executes the generated SQL for real — against the bundled demo dataset here, or an
uploaded `.duckdb` file, or a saved connection. "Metric query" runs a single
metric/group-by query; "Time series" gives the same drill-down/roll-up view as the
Design tab's preview, with its own metric/time-field/starting-grain pickers.

![Semantic query execution: running a metric+group-by query, then a time-series query with drill-down](media/semantic-query-execution.gif)

## Regenerating these clips

`frontend/scripts/record-demo.mjs` drives a headless Chromium via Playwright and
converts the recording to GIF with `ffmpeg` (must be on `PATH`). Needs the dev
servers running with the demo data seeded first:

```bash
LEXIS_DEV_SETUP_DEMO=1 ./scripts/dev.sh start
cd frontend && npm run record-demo
```

Output goes to `docs/media/*.gif`, overwriting the files linked above.
