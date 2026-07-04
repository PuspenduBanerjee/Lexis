# Semantica

An open, [OSI](https://github.com/open-semantic-interchange/OSI)-native semantic layer:
author a data model once in OSI YAML, then transpile it to warehouse-native SQL
(Snowflake, BigQuery, Databricks, DuckDB, Postgres) and to formats BI/AI consumers
understand (Cube.js schema, dbt-core OSI documents, MCP tool manifests grounded in
`ai_context`).

Two ways to use it: a `semantica` CLI/library, and a web UI (FastAPI + React) with a
persisted multi-model workspace, role-based access, and live DuckDB query execution.

See [docs/architecture-plan.md](docs/architecture-plan.md) for the full architecture
writeup and design rationale.

## Quickstart: CLI

Requires Python 3.11+.

```bash
pip install -e .
semantica transpile tests/fixtures/tpcds_semantic_model.yaml --target duckdb --metric total_sales
```

```sql
SELECT SUM(store_sales.ss_ext_sales_price) AS "total_sales"
FROM tpcds.public.store_sales AS "store_sales"
```

Other targets: `postgres`, `bigquery`, `databricks`, `snowflake` (all take `--metric`,
and an optional repeatable `--group-by dataset.field`), plus `cube`, `dbt`, and `mcp`
(whole-model outputs, no `--metric` needed):

```bash
semantica transpile tests/fixtures/tpcds_semantic_model.yaml --target mcp
semantica transpile tests/fixtures/tpcds_semantic_model.yaml \
  --target duckdb --metric customer_lifetime_value --group-by item.i_category
```

Add `--out <file>` to write to a file instead of stdout.

The bundled TPC-DS-shaped demo dataset (the same data the web UI's "Demo dataset"
run mode uses in-memory) can be exported to a real `.duckdb` file, handy as a seed
file for the Upload run mode or a `duckdb_file` connection:

```bash
pip install -e ".[dev]"        # or ".[api]" - needs the optional duckdb dependency
semantica export-demo-dataset --out demo.duckdb
```

Pass `--force` to overwrite an existing file at `--out`.

## Quickstart: Web UI

Two servers: a FastAPI backend and a Vite/React frontend.

**Backend** (from the repo root):

```bash
pip install -e ".[dev,api]"
alembic upgrade head        # creates semantica_dev.db and its schema
uvicorn semantica_api.main:app --reload --port 8000
```

Startup automatically seeds 3 demo users (`admin`, `editor1`, `viewer1` — ids 1/2/3,
roles Admin/Editor/Viewer). There's no login screen yet: requests are attributed to a
user via an `X-User-Id` header (defaults to `1`/admin if omitted) — a deliberate stub,
see [docs/architecture-plan.md](docs/architecture-plan.md) for why and what a real
auth swap-in looks like.

**Frontend** (in a second terminal):

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173, proxies /api -> :8000
```

Open `http://localhost:5173`, use the "Acting as" switcher in the header to pick a
role, paste an OSI YAML document (e.g. `tests/fixtures/tpcds_semantic_model.yaml`) to
create a model, then use the **Browse** / **Design** / **Transpile** / **Run DuckDB**
tabs on the model's page (a sample model is preloaded automatically on first run, so
there's already something to open). "Design" is a node-graph canvas (owner/admin only)
for visually adding/editing datasets, fields, and relationships — drag between the
dots on a dataset box to draw a relationship. Metrics appear as their own read-only
node, connected by dashed edges to every dataset their expression references (a
"Show metrics" toggle hides them); click one for its description/expression/
references, but creating or editing a metric still requires the YAML sub-view. A
metric's panel also shows a live **time-series preview** (against the demo dataset)
when the model has any field marked `dimension.is_time: true` — click a row to drill
into the next finer grain (year → quarter → month → day), or "Roll up" to go back.
The canvas preserves anything it has no control for (`ai_context`, `custom_extensions`,
non-ANSI_SQL dialect expressions, metrics themselves) by merging onto the existing
parsed model rather than regenerating YAML from scratch; see
`src/semantica_api/graph_edit.py`. "Run DuckDB" executes the generated SQL for real,
against a bundled TPC-DS demo dataset, an uploaded `.duckdb`/`.db` file, or a saved
connection (see "Connecting to Snowflake or an external DuckDB file" below) — pick
"Time series" there for the full drill-down/roll-up view (with metric, time-field, and
starting-grain pickers), or "Metric query" for the original metric+group-by mode. In
"Demo dataset" mode, an "Export demo dataset (.duckdb)" button downloads that same
data as a real file - the CLI equivalent of `semantica export-demo-dataset` above.

## Quickstart: Docker

Two images: `semantica-api` (FastAPI backend, migrations run automatically on
container start) and `semantica-web` (the built SPA served by nginx, which also
reverse-proxies `/api/*` to the backend - same same-origin-`/api` pattern the Vite
dev proxy uses, just in production).

```bash
docker compose up -d --build
```

Open `http://localhost:8080`. The SQLite database lives on a named volume
(`semantica-data`, mounted at `/data` in the API container), so it survives
`docker compose down`/`up` and container restarts - only `docker compose down -v`
removes it. Override `SEMANTICA_CORS_ORIGINS`/`SEMANTICA_MAX_DUCKDB_UPLOAD_MB`/etc.
(see `src/semantica_api/config.py`) via `environment:` in `docker-compose.yml` if
needed; if you raise the upload cap, also raise nginx's `client_max_body_size` in
`docker/nginx.conf` to match.

To build the images without compose (e.g. for pushing to a registry):

```bash
./scripts/docker-build.sh [tag]   # defaults to "latest"; builds semantica-api and semantica-web
```

Both containers currently run as root and there's no HTTPS/reverse-auth in front of
them - fine for local/trusted-network use, but harden before exposing publicly.

## Connecting to Snowflake or an external DuckDB file

Beyond the demo dataset and one-off `.duckdb`/`.db` uploads, you can register a
named, reusable **connection** and point any model's "Run" at it instead. Two
types are supported: `duckdb_file` (a DuckDB database file already sitting on the
API server's filesystem) and `snowflake`.

Any authenticated user can view/test/run against any connection (same
workspace-wide visibility as models); creating, updating, or deleting one
requires the Editor or Admin role, and only the connection's owner (or an Admin)
can update/delete it. Requests are attributed via the `X-User-Id` header, same as
everywhere else in the API (see Quickstart: Web UI above).

**Create a DuckDB-file connection:**

```bash
curl -X POST http://localhost:8000/api/connections \
  -H "X-User-Id: 2" -H "Content-Type: application/json" \
  -d '{
        "name": "local-warehouse",
        "type": "duckdb_file",
        "config": {"path": "/data/warehouse.duckdb"}
      }'
```

`path` is resolved on the **API server** (or, in Docker, inside the
`semantica-api` container) - it's not a client-side file picker. If you're
running via `docker compose`, mount the directory containing the file into the
container (alongside the existing `semantica-data` volume in
`docker-compose.yml`) so the path is reachable there.

**Create a Snowflake connection:**

```bash
curl -X POST http://localhost:8000/api/connections \
  -H "X-User-Id: 2" -H "Content-Type: application/json" \
  -d '{
        "name": "prod-snowflake",
        "type": "snowflake",
        "config": {
          "account": "xy12345.us-east-1",
          "user": "SEMANTICA_SVC",
          "password_env": "SNOWFLAKE_PASSWORD",
          "warehouse": "COMPUTE_WH",
          "database": "ANALYTICS",
          "schema": "PUBLIC",
          "role": "ANALYST"
        }
      }'
```

`account`/`user`/`password_env` are required; `warehouse`/`database`/`schema`/
`role` are optional. Secrets are never stored in the database: `password_env` is
the *name* of an environment variable, and the API process reads the actual
password from its own environment (`export SNOWFLAKE_PASSWORD=...`, or an
`environment:` entry in `docker-compose.yml`) at connect time - so that variable
must be set wherever the API process runs, not passed in the request body.

**Test connectivity** (opens a real connection, no query run):

```bash
curl -X POST http://localhost:8000/api/connections/1/test -H "X-User-Id: 2"
# {"ok": true, "detail": "connected successfully"}
```

**Run a model's metric against a connection** (`connection_id` is the id from
the create response above; same `/run` endpoint used for demo/upload, with
`mode=connection`):

```bash
curl -X POST http://localhost:8000/api/models/1/run \
  -H "X-User-Id: 2" \
  -F "mode=connection" -F "connection_id=1" \
  -F "metric=total_sales" -F 'group_by_json=["item.i_category"]'
```

The time-series endpoint (`/api/models/{id}/run/timeseries`) takes the same
`mode=connection`/`connection_id` fields alongside its usual `time_dataset`/
`time_field`/`grain`/`filter_grain`/`filter_value` form fields. For a
`duckdb_file` connection, every dataset referenced by the metric/group-by must
share one catalog name (the first `.`-segment of the dataset's `source` in the
OSI model) - the file is attached under that name, mirroring how the demo/upload
modes work. Snowflake has no such restriction: `source` is used as-is, so it can
reference any `database.schema.table` the connection's role can see.

The web UI's **Connections** page (linked from the header) covers all of the above
graphically - create/edit/delete/test a connection, with the same RBAC - and the
model "Run" tab's "Saved connection" mode lets you pick one to run against.

## Running tests

```bash
pip install -e ".[dev]"       # core library + CLI tests only
pytest tests --ignore=tests/api

pip install -e ".[dev,api]"   # everything, including the API test suite
pytest
```

## Project structure

```text
src/semantica/          core library: OSI parsing, join-graph resolution, transpilers, CLI
src/semantica_api/      FastAPI backend (models, RBAC, transpile route, live query execution
                        against demo/upload DuckDB or a persisted connections.py connection)
frontend/                Vite + React + TypeScript SPA
tests/                  core library tests (fixtures under tests/fixtures/)
tests/api/              backend API tests
docs/architecture-plan.md   architecture decisions and design rationale
docker/                 Dockerfiles + nginx config for the two images (see docker-compose.yml)
scripts/docker-build.sh   builds both images directly with `docker build`, no compose needed
```

## License

Apache 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
