"""Tests for the SML -> Ossie parser (src/lexis/sml/parse.py).

Uses the hand-authored `tests/fixtures/sml/` repo (see the `sml_repo_dir`
fixture in conftest.py) rather than the shared `tpcds_document` fixture -
Phase 2 needs real SML *input* to parse, which Phase 1's emitter-only tests
never needed. See SML_OSSIE_CONVERTER_PLAN.md at the repo root for the
documented supported-subset scope and the LOSSY: warning convention.
"""

import json

import pytest

from lexis.sml._common import ConversionError
from lexis.sml.parse import parse_sml_repo


def test_datasets_resolve_source_from_connection(sml_repo_dir):
    result = parse_sml_repo(sml_repo_dir)
    by_name = {d.name: d for d in result.document.semantic_model[0].datasets}
    assert by_name["orders"].source == "salesdb.public.orders"
    assert by_name["customers"].source == "salesdb.public.customers"


def test_dimension_attributes_flatten_to_fields_on_their_own_dataset(sml_repo_dir):
    result = parse_sml_repo(sml_repo_dir)
    customers = next(d for d in result.document.semantic_model[0].datasets if d.name == "customers")
    field_names = {f.name for f in customers.fields}
    # key attribute (Customer Dimension level) + region (Customer Region level,
    # the hierarchy's other level) + the leaf level's secondary attribute.
    assert {"customer_id", "region", "customer_name"} <= field_names


def test_degenerate_time_dimension_marks_its_field_is_time(sml_repo_dir):
    result = parse_sml_repo(sml_repo_dir)
    orders = next(d for d in result.document.semantic_model[0].datasets if d.name == "orders")
    order_date = next(f for f in orders.fields if f.name == "order_date")
    assert order_date.is_time_dimension()


def test_fact_dataset_backing_a_degenerate_dimension_key_gets_no_primary_key(sml_repo_dir):
    # order_date is the Date Dimension's grain key but is not row-unique in
    # orders (a fact table) - it must not become orders' Ossie primary_key,
    # which the Snowflake Semantic View emitter turns into a literal DDL
    # PRIMARY KEY clause.
    result = parse_sml_repo(sml_repo_dir)
    by_name = {d.name: d for d in result.document.semantic_model[0].datasets}
    assert by_name["orders"].primary_key is None
    assert by_name["customers"].primary_key == ["customer_id"]


def test_relationship_resolves_dimension_level_to_backing_dataset(sml_repo_dir):
    result = parse_sml_repo(sml_repo_dir)
    rel = result.document.semantic_model[0].relationships[0]
    assert rel.name == "orders_to_customer"
    assert rel.from_dataset == "orders"
    assert rel.to == "customers"
    assert rel.from_columns == ["customer_id"]
    assert rel.to_columns == ["customer_id"]


def test_plain_metric_becomes_aggregate_sql(sml_repo_dir):
    result = parse_sml_repo(sml_repo_dir)
    metrics = {m.name: m for m in result.document.semantic_model[0].metrics}
    assert metrics["total_revenue"].expression.dialects[0].expression == "SUM(orders.amount)"
    assert metrics["order_count"].expression.dialects[0].expression == "COUNT(DISTINCT orders.order_id)"


def test_ratio_metric_calc_reconstructs_ansi_sql(sml_repo_dir):
    result = parse_sml_repo(sml_repo_dir)
    metrics = {m.name: m for m in result.document.semantic_model[0].metrics}
    avg = metrics["avg_order_value"]
    assert avg.expression.dialects[0].dialect.value == "ANSI_SQL"
    assert avg.expression.dialects[0].expression == "SUM(orders.amount) / COUNT(DISTINCT orders.order_id)"
    assert not any("avg_order_value" in w for w in result.warnings)


def test_arbitrary_mdx_metric_calc_passes_through_verbatim(sml_repo_dir):
    result = parse_sml_repo(sml_repo_dir)
    metrics = {m.name: m for m in result.document.semantic_model[0].metrics}
    growth = metrics["yoy_revenue_growth"]
    assert growth.expression.dialects[0].dialect.value == "MDX"
    assert growth.expression.dialects[0].expression.startswith("([Measures].[total_revenue]")
    assert any("yoy_revenue_growth" in w and "MDX" in w for w in result.warnings)


def test_unsupported_object_type_is_stashed_not_dropped(sml_repo_dir):
    result = parse_sml_repo(sml_repo_dir)
    assert any("pii_restriction" in w and w.startswith("LOSSY:") for w in result.warnings)

    ext = result.document.semantic_model[0].custom_extensions[0]
    assert ext.vendor_name == "SML"
    stash = json.loads(ext.data)
    assert "pii_restriction" in stash["unsupported_objects"]
    assert stash["unsupported_objects"]["pii_restriction"]["object_type"] == "row_security"


def test_dimension_hierarchy_structure_is_stashed_for_round_trip(sml_repo_dir):
    result = parse_sml_repo(sml_repo_dir)
    ext = result.document.semantic_model[0].custom_extensions[0]
    stash = json.loads(ext.data)
    assert "Customer Dimension" in stash["dimensions"]
    assert "Date Dimension" in stash["dimensions"]
    # The 2-level hierarchy's structure (level order, nested secondary
    # attributes) is preserved verbatim, not just the flattened fields.
    levels = stash["dimensions"]["Customer Dimension"]["hierarchies"][0]["levels"]
    assert [lvl["unique_name"] for lvl in levels] == ["Customer Region", "Customer Dimension"]


def test_requires_exactly_one_model(tmp_path):
    (tmp_path / "catalog.yml").write_text("unique_name: c\nobject_type: catalog\n")
    with pytest.raises(ConversionError, match="exactly one model"):
        parse_sml_repo(tmp_path)


def test_requires_exactly_one_catalog(tmp_path):
    (tmp_path / "model.yml").write_text("unique_name: m\nobject_type: model\n")
    with pytest.raises(ConversionError, match="exactly one catalog"):
        parse_sml_repo(tmp_path)
