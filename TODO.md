# TODO

Deferred items, not blocking current functionality.

## Docker packaging (docker-compose.yml, docker/)

- **Both containers run as root** and there's no TLS termination or auth in front
  of nginx - acceptable for local/trusted-network use (matches the app's existing
  stub-auth posture, see `docs/architecture-plan.md`), but real deployment would
  want a non-root user in `docker/backend.Dockerfile` (needs the `/data` volume's
  ownership handled - either `chown` in the entrypoint before dropping privileges,
  or a fixed-UID volume) and a TLS-terminating proxy in front of `web`.
- **SQLite on a single named volume** means this is single-instance-only - it
  doesn't horizontally scale the `api` service (multiple replicas would corrupt/
  contend on the same SQLite file). Swapping `LEXIS_DATABASE_URL` to Postgres
  (already a documented "cheap swap" in the architecture plan) would be the natural
  next step if that's ever needed.
- **No CI-built/pushed images** - `scripts/docker-build.sh` builds locally by tag;
  publishing to a registry (and wiring that into CI) wasn't set up.

## YAML sub-view (Design tab)

- **Comments are lost after any graph-based save.** `apply_graph_edit` re-serializes
  via `OssieDocument.to_ossie_yaml()` (`model_dump` + `yaml.dump`), which only knows about
  the parsed data, not the original file's comments/formatting — so a model authored
  with `# ...` comments (like the bundled TPC-DS fixture) will have them stripped the
  first time it's saved via the Graph sub-view. Editing purely through the YAML
  sub-view without ever touching Graph avoids this (no round-trip through the parsed
  model happens until you actually save from there instead). Preserving comments
  would require a round-trip-preserving YAML library (e.g. `ruamel.yaml`) instead of
  PyYAML — a real change to the vendored `to_ossie_yaml()`, not attempted here.

## Graph canvas (Design tab)

- **Persist node layout positions.** Currently auto-arranged via dagre on every
  load (`frontend/src/lib/layout.ts`) — dragging nodes works within a session but
  resets on reload/re-open. Two viable approaches when this is picked up:
  - Store positions in Ossie's own `custom_extensions` vendor-metadata escape hatch.
    `vendor_name` is a plain `str` as of the Apache Ossie spec (no longer the closed
    `OssieVendor` enum it once was), so this no longer needs a vendored-enum edit —
    just use `vendor_name="LEXIS"` directly.
  - Store positions in a new column/table on `SemanticModelRecord`
    (`src/lexis_api/models.py`), keyed by dataset name, separate from Ossie content.
- **Re-fit the viewport after adding a node.** `fitView` only runs on initial mount;
  a newly added dataset can land outside the visible viewport if the canvas has been
  panned/zoomed. Minor polish, not a functional bug (the node is still there and
  editable, just may need manual panning to see).
- **Metrics render as their own node type** (`MetricNode.tsx`), laid out downstream
  (via dagre) of every dataset their expression references, connected by dashed
  read-only edges (`GraphEditor.tsx`'s `metric-ref:` edges) computed from
  `ResolvedModel.referenced_datasets` server-side (exposed via `MetricOut.expression`
  / `.referenced_datasets`). A "Show metrics" toggle hides them for a cleaner view
  of just the dataset/relationship graph. They remain **read/browse-only** — clicking
  one opens `MetricPanel.tsx` (name/description/expression/references), but creating
  or editing a metric still requires the Design tab's YAML sub-view
  (`YamlEditor.tsx`); a dedicated metrics editor (expression builder + dataset-
  reference picker) would be a nicer next step than hand-editing YAML.
- **Renaming an existing dataset isn't supported** from the canvas (`DatasetPanel.tsx`
  treats `name` as fixed after creation) to avoid cascading rename logic across
  relationships that reference it by name. Deleting and re-adding under a new name
  works, but loses any preserved attributes (ai_context, custom_extensions) the old
  dataset carried.
- **Switching between the Design tab's Graph and YAML sub-views discards unsaved
  changes** in the one you're leaving (each unmounts when hidden). Fine for now since
  it's disclosed in the UI, but a real editor would either warn before discarding
  (dirty-check + `window.confirm`) or keep both views live-synced to the same
  in-progress (unsaved) state — the latter is a bigger lift since it means
  serializing in-progress graph edits to YAML text and parsing YAML edits back into
  graph state on every keystroke, not just on save.

## Time-series drill-down/roll-up (Design tab preview + Test Metrics tab)

- **DATE_TRUNC-based grain grouping** (`SqlDialectEmitter.emit_timeseries_query` in
  `src/lexis/transpilers/sql/base.py`) only covers `year`/`quarter`/`month`/`day`
  and is only ever invoked through the DuckDB live-execution path
  (`duckdb_runtime.run_timeseries_query`, `POST /api/models/{id}/run/timeseries`) - it
  isn't wired into the CLI's `--target` dispatch or the other 4 SQL dialects' actual
  usage, even though the method itself is dialect-generic (shared `DATE_TRUNC('unit',
  expr)` syntax across DuckDB/Postgres/Databricks/Snowflake). BigQuery's different
  `DATE_TRUNC(expr, UNIT)` argument order means this method would silently produce
  wrong SQL for `BigQueryEmitter` - not currently guarded against, since nothing calls
  it that way today.
- **Time field selection is manual and per-request**, not modeled in Ossie itself -
  there's no concept of "the" canonical time dimension for a dataset/metric, so the
  UI just offers every field with `dimension.is_time: true` as a candidate
  (`lib/timeSeries.ts::timeFields`). A model with a well-known primary time field
  could skip that picker if Ossie/`custom_extensions` grew a way to mark one as default.
- **Drill-down navigation is a single-level filter**, not a full multi-column
  breadcrumb WHERE clause - drilling twice (year → quarter → month) filters on the
  *immediately preceding* grain/period only (`filter_grain`/`filter_value`), which is
  correct because each period is a strict sub-range of its parent, but it does mean
  the backend has no visibility into the full breadcrumb path, only the frontend does
  (`TimeSeriesPanel.tsx`'s `history` state).
- **The Design tab's per-metric preview is demo-mode only** (`MetricPanel.tsx` always
  passes `mode="demo"`) - there's no upload-a-.duckdb-file option there, unlike the
  Test Metrics tab's full `TimeSeriesPanel`. If the selected metric/time-field combo
  isn't demo-compatible, the preview just shows the backend's 400 error text.
