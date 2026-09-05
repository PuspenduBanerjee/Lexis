# SML ↔ Ossie bidirectional converter

## Context

Lexis transpiles one hub format (Ossie) out to N vendor "spokes" (SQL dialects, Cube.js, dbt, MCP, Snowflake semantic views) — but every existing transpiler is one-directional (Ossie → X) and single-file-out. AtScale's **SML** (Semantic Modeling Language, `github.com/semanticdatalayer/SML`) is a widely-used open semantic-modeling spec — AtScale is in fact one of the founding partners of the Ossie/OSI standard itself — yet no SML↔Ossie converter exists anywhere (not in this repo, not upstream in `apache/ossie`, not in AtScale's own `sml-converters` tooling). This plan builds one, going both directions, following the exact architectural conventions the upstream Ossie project already established for its other bidirectional converters (`omni`, `orionbelt`, `databricks`, vendored under `third_party/ossie/converters/`).

**Decisions locked in:**
- **v1 scope = documented supported subset**, mirroring how OrionBelt (OBML↔Ossie) scoped itself: datasets, flattened dimensions/fields, relationships, simple metrics, and dialect-tagged SQL are fully, correctly convertible both ways with round-trip tests. Everything else SML has that Ossie has no room for (calculation groups, row security, perspectives, drillthroughs, composite models, UDAs, packages, MDX calculated members) is preserved **opaquely** via the `custom_extensions` stash — round-trips losslessly back to SML, but is never functionally interpreted by any Ossie-side consumer (our SQL emitters, MCP manifests, etc.).
- **Ossie → SML ships first** — it fits the existing `transpile` command's direction (Ossie-in, format-out) with a moderate extension (multi-file output). SML → Ossie is net-new architecture (multi-file directory input, no existing precedent) and follows once the shared plumbing (stash protocol, dialect mapping, metric decomposition) is proven by the first direction.
- **Lives inside `src/lexis/`**, not a standalone package — new `src/lexis/sml/` subpackage, wired into the existing `dispatch.py`/`cli.py` machinery like every other target.

---

## Data model mapping reference

### Object/concept mapping

| SML concept | Ossie concept | Fidelity |
|---|---|---|
| `catalog` (repo settings) | none | stash-only, on the merged `OssieSemanticModel.custom_extensions` |
| `connection` + `dataset.table`/`connection_id` | `OssieDataset.source` (`database.schema.table`, matching `dbt_ossie.py`'s existing convention) | full, for table datasets |
| `dataset.sql` (query dataset) | `OssieDataset.source` | **lossy/risky** — no 3-part-name equivalent; see Edge Cases |
| `dataset.columns[]` (physical, exhaustive) | `OssieDataset.fields[]` (logical, typically partial) | **structurally asymmetric** — see Edge Cases |
| `dataset.columns[].sql` + `dialects[]` | `OssieField.expression.dialects[]` | full — both support per-dialect SQL overrides natively |
| `dimension` (hierarchies/levels/secondary_attributes) | flattened `OssieField`s + stash | lossy — see Edge Cases |
| `dimension.type: time` level attribute | `OssieField.dimension.is_time` | full for the leaf mapping; hierarchy order/levels themselves are stash-only |
| `metric` (dataset+column+calculation_method) | `OssieMetric.expression` synthesized as `AGG(dataset.column)` | full via decomposition (see below) |
| `metric_calc` (MDX) | `OssieMetric.expression.dialects=[{dialect: MDX, ...}]` | pass-through only — not executable by any SQL emitter |
| model-level relationship (fact→dim, `to.dimension`+`to.level`) | `OssieRelationship` (`to` resolved to the level's backing dataset) | full, requires two-pass resolution |
| dimension-level relationship (embedded/snowflake) | `OssieRelationship` + stash tag (`kind: embedded|snowflake`) | full structurally, scope-tag is stash-only |
| `role_play` | relationship `name` (best-effort) + stash | lossy — no first-class aliasing in Ossie |
| `m2m: true` | `OssieRelationship` (structurally fine — just column pairs) | cardinality/intent metadata is stash-only |
| `perspectives`, `drillthroughs`, `composite_model`, `row_security`, `aggregates` (UDAs), `partitions`, `packages`, `parallel_periods`, `calculation_group`, `model.overrides` | none | **stash-only, zero functional meaning to any Ossie consumer** |

### Dialect enum mapping

| SML dialect | Ossie dialect | Notes |
|---|---|---|
| (base, unmarked `sql`) | `ANSI_SQL` | |
| `Snowflake` | `SNOWFLAKE` | |
| `DatabricksSQL` | `DATABRICKS` | |
| `BigQuery` | `BIGQUERY` | |
| `Postgresql` | *(none)* | stash-only on export; never emitted on Ossie→SML |
| `Iris` | *(none)* | stash-only on export; never emitted on Ossie→SML |

### Metric decomposition (reuse existing prior art)

`src/lexis/transpilers/cube.py` already has `_SIMPLE_AGGREGATE_RE` detecting `FUNC(dataset.column)`-shaped metric expressions for the Cube.js emitter — **reuse/extend this regex**, don't reinvent it. Add a `calculation_method ↔ SQL aggregate function` table (`sum↔SUM`, `count distinct↔COUNT(DISTINCT ...)`, `average↔AVG`, `maximum↔MAX`, `minimum↔MIN`, `stddev_pop↔STDDEV_POP`, `stddev_samp↔STDDEV_SAMP`, `var_pop↔VAR_POP`, `var_samp↔VAR_SAMP`, `percentile↔PERCENTILE_CONT`, `count_if↔COUNT_IF`; `sum distinct` and `estimated count distinct` have no single ANSI function — approximate or stash).

- **Ossie → SML**: expression matches the simple-aggregate shape → emit a plain SML `metric`. Expression is a ratio of two such aggregates (`AGG(a.b) / AGG(c.d)`, optionally with a `NULLIF(..., 0)` divide-by-zero guard on the denominator) → emit an SML `metric_calc` with a synthesized MDX division expression (`"[Measures].[x]/[Measures].[y]"`) referencing two plain `metric` operands — this is the exact shape SML's own docs use for ratio metrics (`calculation.md`'s `Average Catalog Unit Net Profit` example), so it isn't "fabricating" MDX, it's the documented pattern applied mechanically. An operand reuses an existing metric with the same aggregate shape (e.g. `total_sales`) instead of duplicating it as a helper metric when one already exists; the `NULLIF(..., 0)` guard itself has no MDX equivalent (MDX division already returns blank/error on divide-by-zero) and is dropped with a warning, not silently. Anything else (3+ terms, non-ratio combinations, arbitrary expressions) → **do not fabricate MDX**. Emit a `LOSSY:`-prefixed warning and exclude it from emitted SML metrics (documented: "complex metrics require manual SML authoring").
- **SML → Ossie**: `metric` → synthesize `SUM(dataset.column)`-shaped ANSI_SQL expression directly. `metric_calc` → store raw MDX under the `MDX` dialect slot (never translated to SQL), *except* the specific `[Measures].[a]/[Measures].[b]` two-operand-division shape the Ossie → SML direction itself produces, which Phase 2 should decompose back into an ANSI_SQL ratio expression for round-trip fidelity.

---

## Architecture

```
src/lexis/sml/
  __init__.py
  models.py     # hand-written pydantic models for the supported SML object subset
                # (no public SML JSON Schema exists — see Edge Cases)
  _common.py    # ConversionError, require/require_str, stash read/write
                # (custom_extensions, vendor_name="SML"), dialect mapping tables,
                # YAML 1.2 loader/dumper — mirror third_party/ossie/converters/*/  _common.py
  emit.py       # Ossie -> SML:  emit_sml_files(document: OssieDocument) -> dict[str, str]
  parse.py      # SML -> Ossie:  parse_sml_repo(directory: Path) -> OssieDocument
                # (two-pass: build unique_name registry across every *.yml file
                #  by object_type, then resolve all cross-references)
```

**`TranspileResult` needs widening**: every existing target returns one string; SML emits one file per object. Change `dispatch.py`'s `TranspileResult.content` to `str | dict[str, str]`. In `dispatch.py`, add `"sml"` to `TARGETS` and an `elif target == "sml": return TranspileResult(content=emit_sml_files(document), warnings=...)` branch (`emit_sml_files` needs the whole `document`, like `emit_dbt_ossie_document`, not just the resolved model — SML's `catalog`/`connection` objects are document-scoped).

**`cli.py`'s `transpile` command** needs a small extension: when `result.content` is a `dict`, treat `--out` as a **directory** (create if missing, write each `{filename: content}` entry inside it); with no `--out`, print each file as a `# --- <filename> ---` header + content block to stdout.

**New CLI verb for SML → Ossie** (phase 2): doesn't fit `transpile`'s Ossie-in/format-out contract at all — add `lexis import sml <repo-dir> --out model.yaml`, taking a **directory** argument (every other command takes a file), calling `parse_sml_repo()` and writing one merged `OssieDocument` as Ossie YAML.

No new hard dependency — PyYAML and pydantic are already core deps of `lexis-cli`. No new `pyproject.toml` extras group needed for v1.

---

## Implementation phases

**Phase 1 — shared plumbing + Ossie → SML (ship first)** — ✅ **done**
- [x] `src/lexis/sml/_common.py`: stash protocol, `ConversionError`, dialect mapping, calculation_method↔SQL-aggregate table — adapted from `third_party/ossie/converters/databricks/src/ossie_databricks/_common.py`'s shape (operating on the vendored pydantic `OssieDocument` types directly rather than raw dicts, since Lexis's other transpilers already do that).
- [x] `src/lexis/sml/models.py`: pydantic models for `catalog`, `connection`, `dataset` (+ columns), `dimension` (+ `hierarchies`/`levels`/`level_attributes`), `metric`, `metric_calc`, `model` (+ relationships), all with `extra="allow"` since there's no canonical schema to validate against.
- [x] `src/lexis/sml/emit.py`: `emit_sml_files(document) -> SmlEmitResult(files, warnings)`. Built in the planned order: connections (grouped by unique `database.schema` pairs) → datasets → a synthesized single-level dimension for every relationship target → metrics (decomposition via `_common.decompose_simple_aggregate`, reusing/extending `transpilers/cube.py`'s `_SIMPLE_AGGREGATE_RE` pattern) → model (relationships resolved to their synthesized dimension) → catalog.
- [x] Wired into `dispatch.py` (`TARGETS` gains `"sml"`, `TranspileResult.content` widened to `str | dict[str, str]`) and `cli.py` (`--out` now accepts a directory for dict-content targets, writes one file per entry; no-`--out` stdout mode prints a `# --- <filename> ---` header per file).
- [x] Tests: `tests/test_sml_emitter.py` (10 tests) using the existing shared `tpcds_document` fixture rather than a new hand-authored SML-side fixture repo — Phase 1 only *emits* SML, so the existing Ossie fixture is the right input; a dedicated `tests/fixtures/sml/` repo becomes necessary once Phase 2 needs SML *input* to parse. Full suite green (152 passed) after landing.
- [x] Verified manually: `lexis transpile tests/fixtures/tpcds_semantic_model.yaml --target sml --out /tmp/sml_out/` — produced the correct SML repo.
- [x] Extended metric decomposition to also handle a ratio of two simple aggregates (`AGG(a.b) / AGG(c.d)`, optionally `NULLIF(..., 0)`-guarded on the denominator): `_common.decompose_ratio_aggregate` + `emit.py`'s two-pass metrics loop (pass 1 resolves every metric and indexes which ones are plain aggregates; pass 2 emits plain `metric`s, then ratio metrics as `metric_calc` with a synthesized `"[Measures].[x]/[Measures].[y]"` MDX expression, reusing an existing metric with a matching aggregate shape as an operand - e.g. `total_sales` - rather than duplicating it, synthesizing a small helper `metric` only when no match exists). `customer_lifetime_value` and `store_productivity` in the TPC-DS fixture now convert instead of being excluded; the `NULLIF` guard is dropped with a warning since MDX division has no equivalent. Anything beyond a clean two-term ratio still excludes with `LOSSY:` + warns, never guesses. Tests: `tests/test_sml_emitter.py` updated/added (`test_ratio_metric_becomes_metric_calc_reusing_existing_numerator`, `test_ratio_metric_drops_nullif_guard_with_a_warning`, `test_unsupported_metric_expression_is_excluded_with_lossy_warning` for the still-unsupported 3-term case). Full suite green (156 passed).
- [x] Wired `"sml"` into `lexis_api`'s web API and the frontend Transpile tab: `schemas.TARGET` gains `"sml"`, `TranspileOut.content` widened to `str | dict[str, str]` (mirrors `dispatch.TranspileResult`); frontend `Target`/`ALL_TARGETS`/`TranspileOut.content` types updated to match; `TranspileView.tsx` renders multi-file output as a file-tab strip (reusing the existing `.tabs` CSS pattern from `ModelDetailPage.tsx`) with a `<pre>` panel for the selected file, defaulting to the first file on a successful transpile. New test `test_sml_target_returns_a_file_map` in `tests/api/test_transpile_routes.py`. Full suite green (154 passed).

**Phase 2 — SML → Ossie** — ✅ **done**
- [x] Schema correction found while designing Phase 2 and fixed first: `SmlLevel.secondary_attributes` (models.py) was modeled as a list of name strings; SML's actual `dimension.md` spec has these as fully inlined attribute objects ("Only level attributes can be used to define relationships between datasets and other dimensions" - i.e. only `dimension.level_attributes` is name-referenceable, not a level's own `secondary_attributes`). Fixed `SmlLevel.secondary_attributes: Optional[list[SmlLevelAttribute]]` and `emit.py`'s `_emit_dimension` to match: dimension-level `level_attributes` now holds only the one joinable key attribute per level, every other field is inlined directly under its level. `tests/test_sml_emitter.py` updated accordingly.
- [x] `src/lexis/sml/parse.py`: `parse_sml_repo(directory) -> SmlParseResult(document, warnings)`. Two-pass: `_load_objects` walks every `*.yml`, discriminates by `object_type`, builds a `object_type -> unique_name -> raw dict` registry (raises on a duplicate `unique_name` within a type); the main pass resolves `connection_id`, every dimension's `level_attributes`/`hierarchy.levels[].secondary_attributes` (flattened onto whichever dataset *each attribute itself* names - what makes snowflaking fall out for free), `model.relationships[]` and every `dimension.relationships[]` (identical `{from, to}` shape, resolved through the same routine), and metrics (`metric` → `AGG(dataset.column)`, `metric_calc` → the `"[Measures].[a]/[Measures].[b]"` ratio shape decomposed back into ANSI_SQL, anything else passed through verbatim under the `MDX` dialect). Requires exactly one `catalog` and one `model` object (Edge Case #8 out of v1 scope). Everything with no Ossie equivalent (unsupported top-level `object_type`s, full raw dimension dicts for hierarchy/level-order fidelity, unhandled `model`/`catalog` fields) is stashed via `make_stash_extension`, never silently dropped.
- [x] Correctness fix caught via manual testing before it shipped: a degenerate dimension's grain key (e.g. a `Date Dimension` keyed on a fact table's own `order_date` column) must **not** become that fact dataset's Ossie `primary_key` - `order_date` isn't row-unique in `orders`, and the Snowflake Semantic View emitter turns `primary_key` into a literal `PRIMARY KEY (...)` DDL clause. Fixed by computing the set of datasets used as some relationship's `from.dataset` ("fact datasets") first, and only propagating `is_unique_key` into `primary_key_by_dataset` for datasets outside that set.
- [x] New `lexis import sml <repo-dir> --out <file>` CLI command (`cli.py`), under a new `import` command group.
- [x] New fixture: `tests/fixtures/sml/` — a small hand-authored SML repo (one connection, two datasets, a 2-level `Customer Dimension` hierarchy with a secondary attribute, a degenerate `Date Dimension` keyed on the fact table's own column, one relationship, a plain metric pair, a ratio `metric_calc`, an arbitrary-MDX `metric_calc`, and a `row_security` object to exercise the unsupported-type stash path).
- [x] Tests: `tests/test_sml_parser.py` (12 tests, against the new fixture) and `tests/test_sml_roundtrip.py` (2 tests: Phase 1's own emitter output fed back through `parse_sml_repo()`, asserting structural equivalence - dataset/relationship/field/metric sets match, allowing for the ratio ↔ helper-metric asymmetry between the two directions). Full suite green (170 passed).
- [x] Verified manually end-to-end: `lexis import sml tests/fixtures/sml --out /tmp/imported.yaml`, then loaded the result back through `parser.py` and transpiled it to `duckdb` SQL for both a plain metric and the reconstructed ratio metric - correct DDL both times.

**Phase 3 — round-trip fidelity tests (both directions)**
- [ ] `tests/test_sml_roundtrip.py`: fixture-based round trip in both directions, `LOSSY:`-prefixed-warning assertions for every documented-unsupported feature (mirror `test_ossie_metric_no_silent_loss.py`'s no-silent-loss pattern — every drop must be *warned and stashed*, never silent).
- [ ] `tests/test_sml_roundtrip_properties.py`: Hypothesis property test generating random-but-valid models **within the v1 supported subset only** (no calculation_groups/row_security in the generator), using the same injectable `Rnd` interface pattern (Hypothesis-backed + plain-seeded-`random.Random`-backed) as `third_party/ossie/converters/databricks/tests/test_roundtrip_properties.py`, so the properties still run without the `hypothesis` package installed.

---

## Edge cases and challenges that cannot be fully resolved

These are structural, not implementation gaps — no amount of extra engineering closes them within Ossie's current spec shape:

1. **Row-level security is functionally lost, not just data-lost.** `row_security` can be stashed and round-tripped back to SML perfectly, but any Ossie-side consumer that isn't SML-aware — our own SQL emitters, the MCP tool manifest — has no idea the restriction exists and will happily generate unrestricted SQL. This is a genuine security regression risk if someone transpiles a security-bearing SML model to `duckdb`/`postgres`/etc. and relies on the output without knowing the restriction silently didn't travel. **Must be documented prominently, not just handled via stash-and-warn.**

2. **Arbitrary hand-written MDX cannot be translated to SQL.** MDX is evaluated by a multidimensional semantic engine at query time; it isn't compilable to a single ANSI SQL string in the general case. v1 passes raw MDX through under Ossie's `MDX` dialect value (schema-valid, but non-executable by any of our SQL emitters), *except* the one documented, mechanically-safe shape it also authors going the other way: a two-operand `[Measures].[a]/[Measures].[b]` division, which Phase 2 should decompose back into `AGG(...)/AGG(...)` ANSI_SQL. The ~20 built-in calculation templates (`Year to Date`, `Current vs Previous`, etc.) are a closed enough set that best-effort SQL window-function translation is *possible* as a future stretch goal, but is out of v1 scope and should not be attempted half-heartedly — a wrong silent translation is worse than an honest pass-through.

3. **SML requires exhaustive physical-schema column enumeration; Ossie datasets are typically partial.** A `dataset` object in SML must list every column of its backing table. Ossie's `OssieDataset.fields` conventionally lists only what the model actually uses. **Ossie → SML cannot always produce a schema-complete SML dataset** without live warehouse introspection — this repo already has DuckDB/Snowflake connection code (`cli.py`'s `_duckdb_file_connection`/`_snowflake_connection`) that could be reused for that in a future phase, but v1 will emit possibly-incomplete `columns` lists and must document that SML's own tooling may reject them until manually completed.

4. **Query-based (`dataset.sql`) datasets have no clean Ossie `source` equivalent.** Ossie's `source` field is used everywhere as a literal table reference (`database.schema.table`). Wrapping the query as a parenthesized subquery source is a plausible workaround but untested against every SQL dialect this project emits for — flag as unverified, and default to refusing conversion of query-based datasets in v1 if the wrapper produces anything the target dialect can't parse.

5. **No public SML JSON Schema and no open-source reference parser.** SML validation is delegated to AtScale's closed-source `sml-sdk`/`sml-cli` npm packages. Unlike the Ossie side (validated against the real upstream `core-spec/ossie-schema.json` via `tests/test_ossie_spec_conformance.py`), our SML-side models in `src/lexis/sml/models.py` are self-consistency checks against our own reverse-engineered-from-docs shape, not conformance with any canonical external schema. **There is no way to be fully confident our SML parsing/emission is spec-conformant** without either obtaining access to AtScale's closed tooling for cross-validation or accumulating enough real-world SML repos as test fixtures to build confidence empirically.

6. **Role-playing dimensions have no first-class Ossie equivalent.** The same physical dimension reused under different aliases (Order Date vs. Ship Date) can be represented as multiple `OssieRelationship` entries to the same `to` dataset (structurally fine), but the alias *semantics* only survive via the relationship's `name` field and a stash entry — any Ossie-side consumer not SML-aware sees two relationships to the same table with no indication they're "the same dimension, twice."

7. **Multi-repo `package` composition has zero analog in Ossie's single-document model.** SML model definitions can span multiple Git repositories with branch/commit/tag pinning. SML → Ossie must fully resolve every package dependency at conversion time (network/git access required). The reverse (Ossie → SML) cannot reconstruct *which* parts originally came from a shared external package — everything becomes locally-owned in the emitted repo, losing the sharing/dedup structure entirely.

8. **Composite models force a real design choice, not a mechanical conversion.** Combining multiple SML `model`s that share a dimension into one Ossie document can mean (a) one merged `OssieSemanticModel` deduping shared datasets/dimensions, or (b) one `OssieSemanticModel` per member model with duplicated shared-dimension definitions. (a) is cleaner for a single document but loses "these are independently addressable models too"; (b) preserves that but duplicates data. **Recommend (a) as the default, document (b) as an available alternative** — this is a modeling judgment call, not a bug to fix.

9. **Postgresql/Iris SQL dialects have no Ossie enum slot.** Never emitted on Ossie → SML (v1 only emits Snowflake/DatabricksSQL/BigQuery dialect variants it can actually map); preserved via stash on SML → Ossie.

10. **Shared dimensions across multiple SML models have no cross-model sharing concept in Ossie.** Each `OssieSemanticModel.datasets` is self-contained — a dimension used by three SML models becomes three duplicated `OssieDataset`/field definitions if those models land in separate semantic models (see #8), or one shared definition if merged (see #8's option (a)). Not a data-loss issue, but a real duplication/consistency-maintenance cost worth calling out.

---

## Verification

- `pytest tests/test_sml_emitter.py tests/test_sml_roundtrip.py tests/test_sml_roundtrip_properties.py -v` — new tests green, full suite (`pytest -q`) still green.
- `lexis transpile tests/fixtures/sml_source.yaml --target sml --out /tmp/sml_out/` then inspect `/tmp/sml_out/*.yml` by hand against the SML docs' field names.
- Round-trip smoke test: `lexis transpile <model> --target sml --out /tmp/rt/ && lexis import sml /tmp/rt/ --out /tmp/rt.yaml` (once Phase 2 lands) and diff against the original, expecting only the documented normalizations.
- Confirm every `LOSSY:`-prefixed warning path has a corresponding test asserting the warning fires *and* the data is retrievable from `custom_extensions` (never silently dropped, per `test_ossie_metric_no_silent_loss.py`'s pattern).
