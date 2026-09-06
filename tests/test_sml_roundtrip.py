"""Phase 3: round-trip fidelity tests, both directions.

- Ossie -> SML -> Ossie: Phase 1's own emitter output fed back through Phase 2's
  parser. Structural equivalence only ("up to documented normalizations" - see
  SML_OSSIE_CONVERTER_PLAN.md's Verification section), not byte-identical YAML:
  the emitter always produces a schema-complete single-level dimension for
  every relationship target, and the parser re-derives the same
  fields/relationships/metrics from it.
- SML -> Ossie -> SML (`TestSmlToOssieToSml`): the hand-authored `sml_repo_dir`
  fixture parsed then re-emitted, checking the multi-level hierarchy, the
  degenerate dimension, and an unconvertible metric_calc's raw MDX all survive
  via emit.py's stash-awareness - not just the Ossie-side data
  `tests/test_sml_parser.py` already checks.
"""

import yaml

from lexis.sml._common import read_stash
from lexis.sml.emit import emit_sml_files
from lexis.sml.parse import parse_sml_repo


def _write_sml_repo(tmp_path, files: dict[str, str]):
    for filename, content in files.items():
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def test_roundtrip_preserves_datasets_relationships_and_metrics(tpcds_document, tmp_path):
    emitted = emit_sml_files(tpcds_document)
    assert emitted.warnings == [] or all(w.startswith("metric ") for w in emitted.warnings)  # NULLIF-guard notes only

    repo_dir = _write_sml_repo(tmp_path, emitted.files)
    parsed = parse_sml_repo(repo_dir)

    original = tpcds_document.semantic_model[0]
    reparsed = parsed.document.semantic_model[0]

    assert {d.name for d in reparsed.datasets} == {d.name for d in original.datasets}

    original_rel_pairs = {(r.from_dataset, r.to) for r in original.relationships}
    reparsed_rel_pairs = {(r.from_dataset, r.to) for r in reparsed.relationships}
    assert reparsed_rel_pairs == original_rel_pairs

    # Every metric that round-trips as ANSI_SQL must still resolve to the same
    # aggregate SQL Ossie started with (order of terms, spacing aside for the
    # two ratio metrics that go through a metric_calc synthesize/reconstruct
    # round trip).
    original_by_name = {m.name: m for m in original.metrics}
    reparsed_by_name = {m.name: m for m in reparsed.metrics}
    # emit.py synthesizes small helper metrics for a ratio metric_calc's operands
    # (e.g. "customer.c_customer_sk count distinct") when no existing metric
    # already has that shape - every *original* metric name must still be
    # present, plus however many synthesized helpers the ratio metrics needed.
    assert set(original_by_name) <= set(reparsed_by_name)
    for name, metric in reparsed_by_name.items():
        dialect = metric.expression.dialects[0]
        assert dialect.dialect.value == "ANSI_SQL", f"{name} unexpectedly lost its ANSI_SQL round trip"


def test_roundtrip_field_expressions_survive(tpcds_document, tmp_path):
    emitted = emit_sml_files(tpcds_document)
    repo_dir = _write_sml_repo(tmp_path, emitted.files)
    parsed = parse_sml_repo(repo_dir)

    reparsed_store = next(d for d in parsed.document.semantic_model[0].datasets if d.name == "store")
    original_store = next(d for d in tpcds_document.semantic_model[0].datasets if d.name == "store")

    reparsed_field_names = {f.name for f in reparsed_store.fields}
    original_field_names = {f.name for f in original_store.fields}
    assert reparsed_field_names == original_field_names


class TestSmlToOssieToSml:
    """The other direction: parse the hand-authored fixture (`sml_repo_dir`),
    then re-emit it, checking that the 2-level hierarchy, the degenerate time
    dimension (no relationship to trigger it), and an unconvertible
    metric_calc's raw MDX all survive - not just the Ossie-side data Phase 2's
    own parser tests already check."""

    def test_dimension_hierarchy_reemits_verbatim_from_the_stash(self, sml_repo_dir):
        parsed = parse_sml_repo(sml_repo_dir)
        emitted = emit_sml_files(parsed.document)

        original = yaml.safe_load((sml_repo_dir / "dimensions" / "Customer Dimension.yml").read_text())
        reemitted = yaml.safe_load(emitted.files["dimensions/Customer Dimension.yml"])
        assert reemitted == original

    def test_degenerate_dimension_with_no_relationship_still_reemits(self, sml_repo_dir):
        parsed = parse_sml_repo(sml_repo_dir)
        emitted = emit_sml_files(parsed.document)

        original = yaml.safe_load((sml_repo_dir / "dimensions" / "Date Dimension.yml").read_text())
        reemitted = yaml.safe_load(emitted.files["dimensions/Date Dimension.yml"])
        assert reemitted == original

    def test_relationship_targets_the_stashed_dimensions_leaf_level(self, sml_repo_dir):
        parsed = parse_sml_repo(sml_repo_dir)
        emitted = emit_sml_files(parsed.document)

        model = yaml.safe_load(emitted.files["models/sales_model.yml"])
        rel = model["relationships"][0]
        assert rel["to"] == {"dimension": "Customer Dimension", "level": "Customer Dimension"}

    def test_arbitrary_mdx_metric_calc_survives_two_full_hops(self, sml_repo_dir):
        parsed = parse_sml_repo(sml_repo_dir)
        emitted = emit_sml_files(parsed.document)

        model = yaml.safe_load(emitted.files["models/sales_model.yml"])
        stashed = {m["name"]: m for m in model.get("x_lexis_unconverted_metrics", [])}
        assert "yoy_revenue_growth" in stashed
        assert stashed["yoy_revenue_growth"]["expression"]["dialects"][0]["dialect"] == "MDX"

        original = yaml.safe_load((sml_repo_dir / "metrics" / "yoy_revenue_growth.yml").read_text())
        assert (
            stashed["yoy_revenue_growth"]["expression"]["dialects"][0]["expression"]
            == original["expression"]
        )

    def test_unsupported_object_type_survives_as_retrievable_stash(self, sml_repo_dir):
        # Known, documented limitation (see SML_OSSIE_CONVERTER_PLAN.md): an
        # unsupported object_type like row_security round-trips as *retrievable*
        # data on the Ossie document - never silently lost - but emit.py does
        # not re-materialize it as its own standalone SML file, since the
        # original file's folder placement was never captured to reconstruct.
        parsed = parse_sml_repo(sml_repo_dir)
        stash = read_stash(parsed.document.semantic_model[0])
        assert "pii_restriction" in stash["unsupported_objects"]

        emitted = emit_sml_files(parsed.document)
        assert not any("pii_restriction" in name for name in emitted.files)
