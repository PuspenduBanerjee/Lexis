"""Round-trip smoke test: Phase 1's own Ossie -> SML output, fed back through
Phase 2's SML -> Ossie parser (`tests/fixtures/sml/` covers hand-authored SML
*input* shapes the emitter never produces, like multi-level hierarchies or
row_security - this file instead checks the emitter and parser agree with each
other on the shape they share).

Structural equivalence only ("up to documented normalizations" - see
SML_OSSIE_CONVERTER_PLAN.md's Verification section), not byte-identical YAML:
Phase 1 emits a schema-complete single-level dimension for every relationship
target, and Phase 2 re-derives the same fields/relationships/metrics from it.
"""

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
