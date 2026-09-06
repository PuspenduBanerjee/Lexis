# Lexis

An open, [Apache Ossie](https://github.com/apache/ossie)-native semantic layer:
author a data model once in Ossie YAML, then transpile it to warehouse-native SQL
(Snowflake, BigQuery, Databricks, DuckDB, Postgres) and to formats BI/AI consumers
understand (Cube.js schema, dbt-core Ossie documents, MCP tool manifests grounded in
`ai_context`).

Two ways to use it: a `lexis` CLI/library, and a web UI (FastAPI + React) with a
persisted multi-model workspace, role-based access, and live DuckDB query execution.

See [docs/architecture-plan.md](docs/architecture-plan.md) for the full architecture
writeup and design rationale.

This repo tracks the upstream [Ossie spec](https://github.com/apache/ossie)
as a git submodule at `third_party/ossie` (schema, converters docs, examples) so our
vendored model classes (`src/lexis/_vendor/ossie/`) can be kept in sync with it -
see "Keeping Ossie in sync" below.

## Quickstart: Install from PyPI

```bash
pip install lexis-cli
```

Save this as `model.yaml`:

```yaml
version: "0.2.0.dev0"
semantic_model:
  - name: shop
    datasets:
      - name: orders
        source: analytics.public.orders
        fields:
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
    metrics:
      - name: total_revenue
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(orders.amount)
```

Then transpile it:

```bash
lexis transpile model.yaml --target duckdb --metric total_revenue
```

```sql
SELECT SUM(orders.amount) AS "total_revenue"
FROM analytics.public.orders AS "orders"
```

Same command works for every target below — see [Quickstart: CLI (from source)](#quickstart-cli-from-source) for the full target list and the repo's own TPC-DS-based example fixture.

## Quickstart: CLI (from source)

Requires Python 3.11+.

```bash
git submodule update --init   # first time only, or after a fresh clone
pip install -e .
lexis transpile tests/fixtures/tpcds_semantic_model.yaml --target duckdb --metric total_sales
```

```sql
SELECT SUM(store_sales.ss_ext_sales_price) AS "total_sales"
FROM tpcds.public.store_sales AS "store_sales"
```

Other targets: `postgres`, `bigquery`, `databricks`, `snowflake` (all take `--metric`,
and an optional repeatable `--group-by dataset.field`), plus `cube`, `dbt`, `mcp`, and
`snowflake_semantic_view` (whole-model outputs, no `--metric` needed):

```bash
lexis transpile tests/fixtures/tpcds_semantic_model.yaml --target mcp
lexis transpile tests/fixtures/tpcds_semantic_model.yaml \
  --target duckdb --metric customer_lifetime_value --group-by item.i_category
```

`snowflake_semantic_view` emits a `CREATE OR REPLACE SEMANTIC VIEW` DDL statement
(Snowflake's native Cortex Analyst semantic view) with `TABLES`/`RELATIONSHIPS`/
`FACTS`/`DIMENSIONS`/`METRICS` clauses built from the model's datasets, relationships,
fields, and metrics — fields with a `dimension` block become `DIMENSIONS`, fields
without one become `FACTS`, and `ai_context` synonyms/descriptions map to `WITH
SYNONYMS`/`COMMENT`:

```bash
lexis transpile tests/fixtures/tpcds_semantic_model.yaml --target snowflake_semantic_view
```

Add `--out <file>` to write to a file instead of stdout.

The bundled TPC-DS-shaped demo dataset (the same data the web UI's "Demo dataset"
run mode uses in-memory) can be exported to a real `.duckdb` file, handy as a seed
file for the Upload run mode or a `duckdb_file` connection:

```bash
pip install -e ".[mcp]"        # needs the optional duckdb dependency
lexis export-demo-dataset --out demo.duckdb
```

Pass `--force` to overwrite an existing file at `--out`.

## Quickstart: Web UI

Two servers: a FastAPI backend and a Vite/React frontend.

**Backend** (from the repo root):

```bash
pip install -e ".[dev,api]"
alembic upgrade head        # creates lexis_dev.db and its schema
uvicorn lexis_api.main:app --reload --port 8000
```

Startup automatically seeds 3 demo users (`admin`, `editor1`, `viewer1` — ids 1/2/3,
roles Admin/Editor/Viewer). There's no login screen yet: requests are attributed to a
user via an `X-Account-Id` header (defaults to `1`/admin if omitted) — a deliberate stub,
see [docs/architecture-plan.md](docs/architecture-plan.md) for why and what a real
auth swap-in looks like.

**Frontend** (in a second terminal):

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173, proxies /api -> :8000
```

Or run both together with one script, from the repo root (needs `uvicorn`/`alembic`
on PATH already, e.g. via the pyenv/venv `pip install -e ".[dev,api]"` above):

```bash
./scripts/dev.sh start      # runs migrations, launches both, backgrounded
./scripts/dev.sh status     # is either running, and which pid
./scripts/dev.sh stop       # stops both (and their child processes)
./scripts/dev.sh restart
```

Logs go to `.dev/api.log` / `.dev/web.log`; override ports with `LEXIS_API_PORT`/
`LEXIS_WEB_PORT` env vars.

Open `http://localhost:5173`, use the "Acting as" switcher in the header to pick a
role, paste an Ossie YAML document (e.g. `tests/fixtures/tpcds_semantic_model.yaml`) to
create a model, then use the **Browse** / **Design** / **Transpile** / **Test Metrics**
tabs on the model's page (a sample model is preloaded automatically on first run, so
there's already something to open). "Design" is a node-graph canvas (owner/admin only)
for visually adding/editing datasets, fields, and relationships — drag between the
dots on a dataset box to draw a relationship. Metrics appear as their own node,
connected by dashed edges to every dataset their expression references (a "Show
metrics" toggle hides them); "+ Add metric" creates one, and clicking a metric opens
a panel to edit its expression/description or delete it (name is fixed after
creation, like a dataset's) — owner/admin only, same as the rest of the Design tab. A
metric's panel also shows a live **time-series preview** (against the demo dataset,
reflecting the last *saved* version) when the model has any field marked
`dimension.is_time: true` — click a row to drill into the next finer grain (year →
quarter → month → day), or "Roll up" to go back.
The canvas preserves anything it has no control for (`ai_context`, `custom_extensions`,
non-ANSI_SQL dialect expressions) by merging onto the existing
parsed model rather than regenerating YAML from scratch; see
`src/lexis_api/graph_edit.py`. "Test Metrics" executes the generated SQL for real,
against a bundled TPC-DS demo dataset, an uploaded `.duckdb`/`.db` file, or a saved
connection (see "Connecting to Snowflake or an external DuckDB file" below) — pick
"Time series" there for the full drill-down/roll-up view (with metric, time-field, and
starting-grain pickers), or "Metric query" for the original metric+group-by mode. In
"Demo dataset" mode, an "Export demo dataset (.duckdb)" button downloads that same
data as a real file - the CLI equivalent of `lexis export-demo-dataset` above.

## Quickstart: Docker

Two images: `lexis-api` (FastAPI backend, migrations run automatically on
container start) and `lexis-web` (the built SPA served by nginx, which also
reverse-proxies `/api/*` to the backend - same same-origin-`/api` pattern the Vite
dev proxy uses, just in production).

```bash
docker compose up -d --build
```

Open `http://localhost:8080`. The SQLite database lives on a named volume
(`lexis-data`, mounted at `/data` in the API container), so it survives
`docker compose down`/`up` and container restarts - only `docker compose down -v`
removes it. Override `LEXIS_CORS_ORIGINS`/`LEXIS_MAX_DUCKDB_UPLOAD_MB`/etc.
(see `src/lexis_api/config.py`) via `environment:` in `docker-compose.yml` if
needed; if you raise the upload cap, also raise nginx's `client_max_body_size` in
`docker/nginx.conf` to match.

To build the images without compose (e.g. for pushing to a registry):

```bash
./scripts/docker-build.sh [tag]   # defaults to "latest"; builds lexis-api and lexis-web
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
can update/delete it. Requests are attributed via the `X-Account-Id` header, same as
everywhere else in the API (see Quickstart: Web UI above).

**Create a DuckDB-file connection:**

```bash
curl -X POST http://localhost:8000/api/connections \
  -H "X-Account-Id: 2" -H "Content-Type: application/json" \
  -d '{
        "name": "local-warehouse",
        "type": "duckdb_file",
        "config": {"path": "/data/warehouse.duckdb"}
      }'
```

`path` is resolved on the **API server** (or, in Docker, inside the
`lexis-api` container) - it's not a client-side file picker. If you're
running via `docker compose`, mount the directory containing the file into the
container (alongside the existing `lexis-data` volume in
`docker-compose.yml`) so the path is reachable there.

**Create a Snowflake connection:**

```bash
curl -X POST http://localhost:8000/api/connections \
  -H "X-Account-Id: 2" -H "Content-Type: application/json" \
  -d '{
        "name": "prod-snowflake",
        "type": "snowflake",
        "config": {
          "account": "xy12345.us-east-1",
          "user": "LEXIS_SVC",
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
curl -X POST http://localhost:8000/api/connections/1/test -H "X-Account-Id: 2"
# {"ok": true, "detail": "connected successfully"}
```

**Run a model's metric against a connection** (`connection_id` is the id from
the create response above; same `/run` endpoint used for demo/upload, with
`mode=connection`):

```bash
curl -X POST http://localhost:8000/api/models/1/run \
  -H "X-Account-Id: 2" \
  -F "mode=connection" -F "connection_id=1" \
  -F "metric=total_sales" -F 'group_by_json=["item.i_category"]'
```

The time-series endpoint (`/api/models/{id}/run/timeseries`) takes the same
`mode=connection`/`connection_id` fields alongside its usual `time_dataset`/
`time_field`/`grain`/`filter_grain`/`filter_value` form fields. For a
`duckdb_file` connection, every dataset referenced by the metric/group-by must
share one catalog name (the first `.`-segment of the dataset's `source` in the
Ossie model) - the file is attached under that name, mirroring how the demo/upload
modes work. Snowflake has no such restriction: `source` is used as-is, so it can
reference any `database.schema.table` the connection's role can see.

The web UI's **Connections** page (linked from the header) covers all of the above
graphically - create/edit/delete/test a connection, with the same RBAC - and the
model "Run" tab's "Saved connection" mode lets you pick one to run against.

## Using the live MCP server

The `--target mcp` transpile output above is schema-only — it describes the tools but
doesn't run anything. For an AI tool to actually call a metric and get real query
results back, Lexis can also serve a model as a **live** MCP server, one
`query_<metric>` tool per metric, resolved against the demo dataset, a local DuckDB
file, or Snowflake.

There are three ways to wire a client up to it, depending on what you're doing:

| # | Approach | Reaches localhost? | Needs public exposure? |
|---|---|---|---|
| 1 | **Local (stdio)** — the client spawns `lexis mcp-serve` itself | n/a (same process tree) | No |
| 2 | **`mcp-remote` bridge** — the client spawns `mcp-remote`, which proxies to `lexis_api` over plain local HTTP | Yes, from the same machine | **No** |
| 3 | **Public tunnel** (cloudflared/ngrok) — for Claude's own *remote connector* UI, which calls from Anthropic's cloud, not your laptop | No — genuinely public | **Yes** |

Approaches 2 and 3 both talk to the same [remote HTTP endpoint](#the-remote-http-endpoint-approaches-2-and-3);
approach 2 is the better choice whenever you just want to exercise that endpoint
yourself, since it never leaves your machine.

### Approach 1: local (stdio) — e.g. Claude Desktop or any MCP client that launches a subprocess

```bash
pip install -e ".[mcp]"
lexis mcp-serve tests/fixtures/tpcds_semantic_model.yaml --demo
# or: --duckdb-file /path/to/warehouse.duckdb
# or: --snowflake-account ... --snowflake-user ... --snowflake-password-env ...
```

Point a client's config at it, e.g. Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "lexis": {
      "command": "lexis",
      "args": ["mcp-serve", "/path/to/model.yaml", "--demo"]
    }
  }
}
```

`--duckdb-file`/`--snowflake-*` requires every dataset the model's metrics touch to
be reachable the same way the corresponding **Connection** run mode already requires
(see "Connecting to Snowflake or an external DuckDB file" above) — a `--duckdb-file`
model's datasets must all share one catalog name. If a metric references a table your
dataset doesn't have (e.g. running `--demo` against a model with a `store` dataset,
which isn't in the bundled demo data), that one tool call fails with the underlying
DB error — other metrics keep working.

### The remote HTTP endpoint (approaches 2 and 3)

Mounted on the API, bound to an existing saved Connection:

```text
POST/GET/DELETE /api/models/{model_id}/mcp?connection_id=<id>
```

Requires the same `X-Account-Id` header as the rest of the API, and a `connection_id`
for a Connection you've already created (see above) — the endpoint has no demo/upload
mode, since a remote MCP client can't provide a file per request. `connection_id` is
**not** the model's id, and there's no connection until you create one — a fresh
install has none, so calling this endpoint before creating a connection fails with
`{"detail":"connection not found"}`. If you just want to try it against the bundled
demo data:

```bash
lexis export-demo-dataset --out /tmp/tpcds-demo.duckdb --force

curl -X POST http://localhost:8000/api/connections \
  -H "X-Account-Id: 2" -H "Content-Type: application/json" \
  -d '{"name":"demo","type":"duckdb_file","config":{"path":"/tmp/tpcds-demo.duckdb"}}'
# -> note the "id" in the response, use it as connection_id below
```

Then point any MCP client that supports a remote HTTP server at the model's `/mcp`
URL; it speaks the standard MCP Streamable HTTP transport, e.g.:

```bash
curl -X POST "http://localhost:8000/api/models/1/mcp?connection_id=<id-from-above>" \
  -H "X-Account-Id: 2" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2025-06-18","capabilities":{},
                  "clientInfo":{"name":"curl","version":"0"}}}'
```

Each tool call opens the connection fresh (same per-request cost model the `/run`
endpoint already has) and returns the metric's real result rows, not just the schema.

#### A workspace-wide alternative: switch models/connections without reconnecting

The endpoint above fixes one model+connection in the URL - reasonable for a client
that only ever cares about one model, but it means picking a different model or
connection means reconnecting to a different URL. `POST/GET/DELETE /api/mcp` (no
`model_id`/`connection_id` in the URL at all) is the alternative: one connection,
four generic tools, `model_id`/`connection_id` supplied as **tool-call arguments**
instead:

- `list_models` - every model in the workspace (id, name, description)
- `list_connections` - every connection (id, name, type)
- `list_metrics(model_id)` - a model's metrics, each with its description and valid
  `group_by` references (the same data the per-model endpoint bakes into each
  `query_<metric>` tool's schema, just returned as data here instead)
- `query_metric(model_id, metric, connection_id, group_by?)` - runs it

The trade-off: the per-model endpoint's one-governed-tool-per-metric design (a
distinct `query_<metric>` tool, `group_by` constrained to a real enum in the JSON
schema itself) becomes one generic `query_metric` tool instead, since the tool
schema can no longer depend on which `model_id` shows up in a given call - an
agent has to call `list_metrics` first to discover what's valid rather than having
it enforced by the schema. Point either the `mcp-remote` bridge (below) or a
tunnel at `http://localhost:8000/api/mcp` instead of the per-model URL to use it.

### Approach 2: `mcp-remote` as a local stdio bridge (no public exposure)

When you add a **custom (remote) connector** in Claude Desktop's Settings → Connectors
or claude.ai, Anthropic's cloud infrastructure — not your local Desktop app — is what
actually opens the HTTP connection to the URL you give it. `localhost` from their
servers' point of view means *their own server*, not your laptop, so that path
genuinely requires a publicly reachable URL (approach 3, below).

If you just want to exercise the remote HTTP endpoint above without any public
exposure, [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) is a small local
bridge: Claude spawns it as an ordinary local (stdio) subprocess — same mechanism as
approach 1 — and *it* makes the HTTP call to `lexis_api` from your own machine, where
`localhost` means exactly what you'd expect. No tunnel, no TLS, no public exposure:

```json
{
  "mcpServers": {
    "lexis-remote": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:8000/api/models/1/mcp?connection_id=1",
        "--allow-http",
        "--header",
        "X-Account-Id: 2"
      ]
    }
  }
}
```

`--allow-http` is required since the endpoint here is plain HTTP (`mcp-remote` refuses
non-HTTPS URLs by default, for good reason on a real network — this one never leaves
your machine). `--header` supplies the same `X-Account-Id` auth the API needs everywhere
else. Verified working end-to-end: `initialize` → `notifications/initialized` →
`tools/call query_total_sales` all round-trip correctly through the bridge.

### Approach 3: exposing the endpoint over HTTPS (for Claude's own remote connector)

If you specifically want to use Claude's built-in remote-connector UI (rather than
`mcp-remote`), you do need a genuinely public HTTPS URL, for the reason above. For
local development, the quickest way to get one is a tunnel that terminates TLS for you
and forwards to your local port, with no cert management needed:

```bash
# install once (see cloudflare's docs for your OS if `brew`/`apt` aren't available)
brew install cloudflared   # or: apt install cloudflared

# with lexis_api already running on :8000 - logging to .dev/ alongside
# scripts/dev.sh's own api.log/web.log, backgrounded so the shell stays free:
nohup cloudflared tunnel --url http://localhost:8000 > .dev/cloudflared.log 2>&1 &
sleep 5 && grep -o 'https://[a-zA-Z0-9.-]*trycloudflare\.com' .dev/cloudflared.log
```

That prints the random `https://<something>.trycloudflare.com` URL straight from the
log. Your full connector URL is then:

```text
https://<something>.trycloudflare.com/api/models/<model_id>/mcp?connection_id=<connection_id>
```

`ngrok http 8000` is an equivalent alternative if you'd rather use that.

**Before you expose it**: `X-Account-Id` is a development-only auth stub in this codebase
(see `lexis_api/deps.py`) — anyone who reaches the tunnel URL can act as *any* user id
just by setting that header themselves, no password or token required. Only run the
tunnel while you're actively testing against your own machine, don't point it at a
database with real data, and kill it (`pkill cloudflared`, since the command above
backgrounds it) as soon as you're done — the hostname is random and will change on
every restart anyway, so there's no persistent URL to protect.

### Connecting Claude's remote connector to it (approach 3 only)

1. Claude Desktop: `Ctrl+,` (or the top-left menu → File → Settings) → **Connectors**
   in the sidebar → **Add custom connector**.
2. Paste in the tunnel URL from above, including the `/api/models/<model_id>/mcp?connection_id=<connection_id>` path.
3. Look for a **Request headers** section in that same dialog and add `X-Account-Id` →
   your user id (e.g. `2`). Claude stores it as the connector's credential and sends it
   on every request — this is what satisfies the endpoint's auth requirement.

Request-header support for custom connectors is currently a **beta feature limited to
some organizations** — if you don't see that section, the dialog will only offer OAuth,
which this endpoint doesn't implement, and you won't be able to connect this
particular remote endpoint from Claude's UI without a small proxy in front of it that
injects the header for you. Approaches 1 and 2 above have no such limitation — neither
goes through this connector-UI auth path at all, since both configure the header (or
skip auth entirely) directly in `claude_desktop_config.json`.

### Sample questions to ask

Once connected (any of the three approaches), the model's `ai_context` synonyms let
you ask in plain language instead of naming the metric exactly — try these against the
bundled demo data:

- "How's revenue breaking down by product category?"
- "What's our customer lifetime value?"
- "Break total sales down by brand."
- "Show me sales by year."
- "How productive are our stores?" (exercises `store_productivity`, a ratio metric)

Two things worth knowing about the bundled `--demo` data specifically, so unexpected
answers don't read as bugs: it's only 2 items/2 customers, so per-item attributes like
brand and category are perfectly correlated (slicing by either gives the same split);
and a handful of `store_sales` rows deliberately reference an item/customer id that
doesn't exist, so an item- or customer-sliced metric will show a smaller total than one
sliced by date alone — that's correct `INNER JOIN` behavior on intentionally
incomplete sample data, not a data-completeness gap in the model.

## Running tests

```bash
pip install -e ".[dev]"       # core library + CLI tests only
pytest tests --ignore=tests/api

pip install -e ".[dev,api]"   # everything, including the API test suite
pytest
```

## Project structure

```text
src/lexis/          core library: Ossie parsing, join-graph resolution, transpilers, CLI
src/lexis_api/      FastAPI backend (models, RBAC, transpile route, live query execution
                        against demo/upload DuckDB or a persisted connections.py connection)
frontend/                Vite + React + TypeScript SPA
tests/                  core library tests (fixtures under tests/fixtures/)
tests/api/              backend API tests
docs/architecture-plan.md   architecture decisions and design rationale
docker/                 Dockerfiles + nginx config for the two images (see docker-compose.yml)
scripts/docker-build.sh   builds both images directly with `docker build`, no compose needed
third_party/ossie/      git submodule: upstream Ossie spec/schema/converters docs/examples
```

## Keeping Ossie in sync

`src/lexis/_vendor/ossie/models.py` is a vendored (not pip-installed - `apache-ossie`
isn't on PyPI yet) copy of upstream's pydantic model classes, and `tests/fixtures/*.yaml`
are meant to conform to upstream's JSON Schema. Both are checked against the
`third_party/ossie` submodule by `tests/test_ossie_spec_conformance.py`, so a submodule bump
that changes either will fail loudly instead of silently drifting.

To pick up an upstream Ossie change:

```bash
git submodule update --remote third_party/ossie   # bump the submodule to upstream's latest main
scripts/sync_ossie_vendor.sh                        # re-vendor models.py + refresh NOTICE.md's commit pin
pytest tests/test_ossie_spec_conformance.py tests/test_parser.py tests/test_resolved_model.py
```

`scripts/sync_ossie_vendor.sh` only overwrites `models.py` verbatim; `__init__.py` is
hand-adapted (relative import, own docstring) and the script just warns if a new
upstream class/name isn't re-exported yet, so it needs a manual one-line addition in
that case.

`third_party/ossie` is upstream's repo, not ours - never edit files inside it directly,
and never commit local changes to it (we have no push access, and a submodule pointer
referencing a commit we made locally but never pushed would break for everyone else
who clones this repo). Its `.gitmodules` entry sets `ignore = dirty`, so `git status`/
`git diff` won't even show local edits inside it; the only supported way to move it
forward is `git submodule update --remote third_party/ossie` followed by
`scripts/sync_ossie_vendor.sh`.

This is also enforced by two automated checks, both running
`scripts/check_ossie_submodule_pin.sh` (fails if `third_party/ossie` is pinned to a commit
that isn't reachable from any of its remote branches - i.e. a local-only commit made by
accidentally `cd`-ing into the submodule and committing there):

- **CI** (`.github/workflows/check-ossie-submodule.yml`) runs it on every push/PR - the
  real backstop, since it can't be skipped.
- **A local pre-commit hook** (`.githooks/pre-commit`) runs it before any commit that
  touches the submodule pin, so you find out before pushing rather than after CI fails.
  Opt in once per clone (git doesn't version `.git/hooks`, so this isn't automatic):

  ```bash
  git config core.hooksPath .githooks
  ```

## License

Apache 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
