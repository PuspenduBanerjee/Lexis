# Semantica: Architecture Foundation Decision & Initial Scaffold

## Context

Semantica's goal is to be an open, OSI-native semantic-layer platform that stands as a compelling alternative to proprietary offerings like AtScale: author models once in **OSI** (Open Semantic Interchange — Apache-2.0 YAML spec, v1.0 finalized Jan 27 2026, led by Snowflake with AtScale/dbt Labs/Salesforce/Preset as partners), then transpile those models into (a) warehouse-native SQL and (b) formats BI/AI consumers understand.

The open question going in was whether to build this from scratch or build on top of an existing open-source project. Three candidates were investigated in depth this session:

- **Apache Kylin** — researched twice, including a second pass specifically checking whether Spark's warehouse-pushdown connectors rescue it as a lightweight option. Verdict: **ruled out**. Kylin 5.0.2 is a precomputed-cube OLAP engine built on Spark + a Gluten-ClickHouse native compute engine. Its pushdown feature is a narrow query-time fallback wired to Hive/SparkSQL, not to Snowflake/BigQuery/Databricks — and Kylin 5.0 actually *removed* generic JDBC data-source support that earlier versions had. Cube building fundamentally requires materializing data into Kylin's own Parquet/Gluten storage; there's no supported path where Kylin sits purely on top of a customer's warehouse. It remains available as a possible optional runtime backend far down the roadmap for users who want real precomputed OLAP cubes, but it is not a foundation for the core product.
- **Malloy** (google/malloydata) — a genuine embeddable multi-dialect SQL compiler (`@malloydata/malloy` exposes `Runtime.loadModel/loadQuery/.run()`), but its own README states its APIs are "still in beta and subject to change," it's pre-1.0, and using it would mean translating OSI semantics into Malloy's own modeling language — a real impedance-mismatch cost for a benefit (dialect SQL generation) that's a well-scoped, boundable problem on its own (OSI fields/metrics are already scalar/aggregate SQL expression strings with `{dataset}.{column}` refs and explicit join info; only ~5 target dialects).
- **Cube Core** (cube-js/cube) — a mature, Apache-2.0 headless semantic layer, but it is architected as a standalone server (Docker/npm-start, config-driven); there's no documented way to embed its query-compiler as a library. It *does* support generating its YAML schema dynamically (Jinja/Python templating, JS `asyncModule()`), which makes it a great **output target**, not an internal dependency.
- **dbt-core** (dbt Labs) — investigated one level up from MetricFlow, specifically its native `semantic_models:`/`metrics:` YAML (1.8+, restructured again in the "latest spec" as of 1.12+). That native format is *not* embeddable: parsing raw project YAML requires dbt-core's own `ref()`/Jinja/manifest-resolution machinery, not a standalone library (its former standalone schema package, `dbt-semantic-interfaces`, is now deprecated in favor of an internal MetricFlow package). But there's a much bigger finding: **dbt Core v1.12+ natively parses OSI JSON documents directly** — drop OSI-schema JSON into a project's `OSI/` directory (or a configured `osi-paths`) and dbt folds it straight into `manifest.json`/`semantic_manifest.json` alongside a dedicated `osi_document.json` artifact, no bespoke dbt-format conversion needed. dbt Labs has stated native dbt YAML and OSI "coexist for now" while they explore deeper convergence — dbt is moving toward OSI, not the reverse. **Practical effect on this plan**: the "dbt" integration is nearly free — emit (mostly) our native OSI JSON to the right location/config rather than hand-writing an OSI→dbt-YAML converter with its own entity/dimension/measure typing. This is now one of the lowest-effort, highest-leverage targets and should be prioritized alongside Cube.js YAML.

**Conclusion**: don't embed any of the three. Hand-write our own OSI → SQL-dialect emitters (bounded, testable problem) and treat Cube Core, LookML, and (optionally) Malloy source as **transpilation targets** alongside AI-consumer formats — exactly the "hub-and-spoke" pattern OSI's own converters already use (`OSI core spec` as the hub, N vendor spokes). Users who want live serving/caching can run their own Cube Core instance fed by our generated YAML; we don't need to build or host a query runtime ourselves for v1.

This also resolves the previously-open language-stack question: since nothing is embedded from the JS/TS ecosystem, there's no pull toward TypeScript. **Python end-to-end**, matching OSI's own reference tooling (`osi-python`, a pydantic package for parsing/validating/serializing OSI YAML) and the `semantica` pyenv virtualenv already created for this project.

## Recommended Architecture

```
OSI YAML (author's model)
    |
    v
[osi-python: parse + validate]  <-- depend on/vendor the official package, don't reimplement
    |
    v
[Resolved Model layer]  -- our code: index datasets/fields/metrics,
    |                        resolve join graph for cross-dataset metrics,
    |                        validate dangling refs, dialect fallback (vendor -> ANSI_SQL)
    |
    +--> SQL dialect emitters (Snowflake / BigQuery / Databricks / DuckDB / Postgres)
    |       -- hand-written, per OSI converters/index.md's documented field/metric/
    |          relationship mapping tables; dialect selection with ANSI_SQL fallback
    |
    +--> dbt OSI-document emitter    -- near-free: dbt-core 1.12+ ingests raw OSI JSON
    |       natively (drop into project's OSI/ dir / osi-paths config); mostly a
    |       matter of packaging our own OSI doc correctly + version/schema checks,
    |       not a bespoke OSI->dbt-YAML converter
    |
    +--> Cube.js YAML emitter        -- external target; user can run their own Cube Core
    +--> LookML emitter (stretch)
    +--> Malloy source emitter (stretch, reference-only use of Malloy, no dependency)
    |
    +--> AI-consumer emitters (the differentiator):
            MCP tool manifests, LLM function-calling schemas grounded in `ai_context`
            (instructions/synonyms/examples) so agents get safe, governed query tools
            instead of hallucinating joins/columns.
```

Kylin, Cube Core (as a running server), and Malloy (as its own tool) are **downstream consumers of Semantica's output**, not build-time dependencies — this can be revisited later if a hosted live-serving runtime becomes a priority (Phase 3+, out of scope now).

## Initial Scaffold

Repo is currently empty (`Notess` placeholder only), pyenv virtualenv `semantica` (Python 3.14.5) already pinned via `.python-version`.

```
semantica/
  pyproject.toml                 # deps: osi-python (or vendored copy), pyyaml, click/typer, pytest
  src/semantica/
    __init__.py
    parser.py                    # thin wrapper around osi.models.OSIDocument
    resolved_model.py            # join-graph resolution, field/metric indexing, dialect fallback
    transpilers/
      base.py                    # Transpiler protocol: emit(resolved_model) -> Artifact(s)
      sql/
        base.py                  # shared dialect-emitter scaffolding (quoting, date-trunc, etc.)
        snowflake.py
        bigquery.py
        databricks.py
        duckdb.py
        postgres.py
      cube.py                    # OSI -> Cube.js YAML
      dbt_osi.py                 # package/validate our OSI doc for dbt-core 1.12+ OSI/ ingestion
      mcp.py                     # OSI -> MCP tool manifest / function-calling schema
    cli.py                       # `semantica transpile <model.yaml> --target duckdb|cube|dbt|mcp`
  tests/
    fixtures/
      tpcds_semantic_model.yaml  # copy from OSI repo (examples/) - canonical real-world test model
      flights.yaml               # OSI's ontology-layer example, for later ontology-mapping support
    test_parser.py
    test_resolved_model.py
    test_sql_emitters.py
    test_cube_emitter.py
```

**Reuse points already identified from OSI's own repo** (`open-semantic-interchange/OSI` on GitHub):
- `python/src/osi/models.py` — pydantic `OSIDocument`/`OSISemanticModel`/`OSIDataset`/`OSIField`/`OSIRelationship`/`OSIMetric` classes with `to_osi_yaml()`/`to_osi_json()`. Depend on this directly (check PyPI availability for `osi-python`; vendor a pinned copy if not yet published).
- `core-spec/osi-schema.json` and `validation/validate.py` — for pre-transpile validation.
- `converters/index.md` — the field-by-field mapping table (datasets/fields/relationships/metrics → vendor equivalents, dialect-fallback rules, composite-key handling, custom_extensions round-tripping) is essentially a spec for our SQL emitters; follow it directly rather than re-deriving mapping rules.
- `examples/tpcds_semantic_model.yaml` — realistic fact/dimension model (already fetched to `/tmp/osi_research/tpcds.yaml`), use as the first end-to-end test fixture.
- dbt Labs' `docs.getdbt.com/docs/build/osi-semantic-models` (OSI ingestion in dbt-core 1.12+) — defines the exact `OSI/`-directory / `osi-paths` packaging convention and the OSI schema version dbt currently expects; the `dbt_osi.py` emitter should target this precisely rather than guessing dbt's expectations.
- (Reference only, not a dependency) dbt's now-deprecated `dbt-semantic-interfaces` validation rules (non-additive dimensions, `agg_time_dimension`, primary/foreign entity join inference) — worth skimming for edge cases OSI's spec may not yet address, since it's a mature, battle-tested rule set.

**Update**: the OSI repo is now checked out as a git submodule at `third_party/OSI` (still not depended on as `osi-python` isn't published to PyPI), so the reuse points above are live files, not remote references — `core-spec/osi-schema.json` is used directly by `tests/test_osi_spec_conformance.py` to validate fixtures, and `scripts/sync_osi_vendor.sh` re-vendors `models.py` from the submodule on demand. See README's "Keeping OSI in sync".

## Verification

1. Parse `tpcds_semantic_model.yaml` via `osi-python` into an `OSIDocument`; assert datasets/relationships/metrics counts match the source file.
2. Build the resolved model; assert the join path from `store_sales` to `customer`/`item`/`date_dim` is correctly resolved from the declared `relationships`.
3. Emit DuckDB SQL for the `total_sales` metric (`SUM(store_sales.ss_ext_sales_price)`), load a small TPC-DS sample into a local DuckDB file, run the generated SQL, and confirm it executes and returns a sane aggregate — this is the "does the transpiler actually produce runnable SQL" smoke test, not just string comparison.
4. Emit Cube.js YAML for the same model; validate it's well-formed YAML with the expected `cubes:`/`measures:`/`dimensions:`/`joins:` structure per Cube's schema docs.
5. Package the OSI document per dbt-core 1.12+'s `OSI/`-directory convention and confirm it matches the expected schema version/location (a real dbt-project ingestion test is a stretch goal if a throwaway dbt project is available).
6. Emit an MCP tool manifest / function-calling schema for the `total_sales` metric and confirm the JSON includes the `ai_context` synonyms/instructions as tool descriptions.
7. Run `pytest` for the full suite; all green before considering the scaffold "done."

## Open Follow-ups (not blocking this plan)

- Whether to depend on `osi-python` from PyPI or vendor a pinned copy (check publish status when implementing).
- Whether/when to add a live query-serving runtime (own engine vs. document "run your own Cube Core" as the answer) — deferred, not needed for v1.
- Kylin remains parked as a possible future pluggable OLAP-cube runtime option, not on the current roadmap.

## Status (as of initial scaffold implementation)

All items in the Initial Scaffold and Verification sections above are implemented and passing:
- 27 pytest tests green (parser, resolved-model join-graph resolution, all 5 SQL dialect emitters, Cube YAML, dbt OSI packaging, MCP manifest).
- Generated DuckDB SQL was executed against real tables and produced correct aggregates.
- `dbt_osi.py` and `mcp.py` were added beyond the original file list (not just `cube.py`) to cover the dbt-core 1.12+ OSI ingestion path and the MCP/AI-consumer differentiator.
- `LookML` and `Malloy source` emitters remain stretch goals, not yet implemented.
- No live query-serving runtime has been built (by design, per the "Open Follow-ups" above).
