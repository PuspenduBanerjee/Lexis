"""Tests for the Ossie -> SML emitter (src/lexis/sml/emit.py).

Mirrors test_dbt_ossie.py's structure/fixtures: uses the shared `tpcds_document`
fixture from conftest.py rather than hand-building an OssieDocument. See
SML_OSSIE_CONVERTER_PLAN.md at the repo root for the documented supported-subset
scope and the LOSSY: warning convention these tests exercise.
"""

import yaml

from lexis.sml.emit import emit_sml_files


def test_emits_expected_file_set(tpcds_document):
    result = emit_sml_files(tpcds_document)
    assert "catalog.yml" in result.files
    assert "connections/Connection - tpcds.public.yml" in result.files
    assert "models/tpcds_retail_model.yml" in result.files
    for dataset in ("store_sales", "customer", "item", "date_dim", "store"):
        assert f"datasets/{dataset}.yml" in result.files
    # Only relationship targets get a synthesized dimension - store_sales is the
    # fact and never a relationship's `to`, so it has no dimension file.
    for dim in ("date_dim", "customer", "item", "store"):
        assert f"dimensions/{dim} Dimension.yml" in result.files
    assert "dimensions/store_sales Dimension.yml" not in result.files


def test_dataset_maps_source_to_connection_and_columns(tpcds_document):
    result = emit_sml_files(tpcds_document)
    dataset = yaml.safe_load(result.files["datasets/store_sales.yml"])
    assert dataset["object_type"] == "dataset"
    assert dataset["connection_id"] == "Connection - tpcds.public"
    assert dataset["table"] == "store_sales"
    column_names = {c["name"] for c in dataset["columns"]}
    assert "ss_ext_sales_price" in column_names
    assert "ss_sold_date_sk" in column_names


def test_connection_split_from_three_part_source(tpcds_document):
    result = emit_sml_files(tpcds_document)
    conn = yaml.safe_load(result.files["connections/Connection - tpcds.public.yml"])
    assert conn == {
        "unique_name": "Connection - tpcds.public",
        "object_type": "connection",
        "database": "tpcds",
        "schema": "public",
    }


def test_simple_aggregate_metric_decomposes_to_plain_metric(tpcds_document):
    result = emit_sml_files(tpcds_document)
    metric = yaml.safe_load(result.files["metrics/total_sales.yml"])
    assert metric["object_type"] == "metric"
    assert metric["calculation_method"] == "sum"
    assert metric["dataset"] == "store_sales"
    assert metric["column"] == "ss_ext_sales_price"


def test_ratio_metric_becomes_metric_calc_reusing_existing_numerator(tpcds_document):
    result = emit_sml_files(tpcds_document)
    metric_calc = yaml.safe_load(result.files["metrics/customer_lifetime_value.yml"])
    assert metric_calc["object_type"] == "metric_calc"
    # total_sales is SUM(store_sales.ss_ext_sales_price), the same aggregate as the
    # ratio's numerator - it's reused rather than duplicated as a new helper metric.
    assert metric_calc["expression"] == "[Measures].[total_sales]/[Measures].[customer.c_customer_sk count distinct]"

    denominator = yaml.safe_load(result.files["metrics/customer.c_customer_sk count distinct.yml"])
    assert denominator["object_type"] == "metric"
    assert denominator["calculation_method"] == "count distinct"
    assert denominator["dataset"] == "customer"
    assert denominator["column"] == "c_customer_sk"
    assert not any("customer_lifetime_value" in w for w in result.warnings)


def test_ratio_metric_drops_nullif_guard_with_a_warning(tpcds_document):
    result = emit_sml_files(tpcds_document)
    metric_calc = yaml.safe_load(result.files["metrics/store_productivity.yml"])
    assert metric_calc["object_type"] == "metric_calc"
    assert metric_calc["expression"] == "[Measures].[total_sales]/[Measures].[store.s_number_employees sum]"
    assert any(
        "store_productivity" in w and "NULLIF" in w and "dropped" in w for w in result.warnings
    )


def test_unsupported_metric_expression_is_excluded_with_lossy_warning(tpcds_document):
    # A three-term expression isn't a simple aggregate or a two-term ratio of them,
    # so it must still be excluded rather than guessed at. Ossie models are frozen,
    # so build the modified metric via model_copy rather than mutating in place.
    semantic_model = tpcds_document.semantic_model[0]
    old_metric = semantic_model.metrics[0]
    new_dialect = old_metric.expression.dialects[0].model_copy(
        update={
            "expression": (
                "SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk) / 2"
            )
        }
    )
    new_expression = old_metric.expression.model_copy(update={"dialects": [new_dialect]})
    new_metric = old_metric.model_copy(update={"expression": new_expression})
    new_semantic_model = semantic_model.model_copy(
        update={"metrics": [new_metric, *semantic_model.metrics[1:]]}
    )
    document = tpcds_document.model_copy(
        update={"semantic_model": [new_semantic_model, *tpcds_document.semantic_model[1:]]}
    )

    result = emit_sml_files(document)
    assert f"metrics/{new_metric.name}.yml" not in result.files
    lossy = [w for w in result.warnings if w.startswith("LOSSY:")]
    assert any(new_metric.name in w and "metric_calc requires MDX" in w for w in lossy)


def test_model_relationships_target_synthesized_dimensions(tpcds_document):
    result = emit_sml_files(tpcds_document)
    model = yaml.safe_load(result.files["models/tpcds_retail_model.yml"])
    by_name = {r["unique_name"]: r for r in model["relationships"]}
    rel = by_name["store_sales_to_customer"]
    assert rel["from"] == {"dataset": "store_sales", "join_columns": ["ss_customer_sk"]}
    assert rel["to"] == {"dimension": "customer Dimension", "level": "customer Dimension"}


def test_model_lists_every_convertible_metric_including_synthesized_helpers(tpcds_document):
    result = emit_sml_files(tpcds_document)
    model = yaml.safe_load(result.files["models/tpcds_retail_model.yml"])
    metric_names = {m["unique_name"] for m in model["metrics"]}
    assert metric_names == {
        "total_sales",
        "total_profit",
        "sales_by_brand",
        "customer_lifetime_value",
        "store_productivity",
        "customer.c_customer_sk count distinct",
        "store.s_number_employees sum",
    }


def test_time_dimension_marked_type_time(tpcds_document):
    result = emit_sml_files(tpcds_document)
    date_dim = yaml.safe_load(result.files["dimensions/date_dim Dimension.yml"])
    assert date_dim["type"] == "time"

    store_dim = yaml.safe_load(result.files["dimensions/store Dimension.yml"])
    assert store_dim["type"] == "standard"


def test_dimension_has_single_level_with_secondary_attributes(tpcds_document):
    result = emit_sml_files(tpcds_document)
    store_dim = yaml.safe_load(result.files["dimensions/store Dimension.yml"])
    assert len(store_dim["hierarchies"]) == 1
    hierarchy = store_dim["hierarchies"][0]
    assert len(hierarchy["levels"]) == 1
    level = hierarchy["levels"][0]
    assert level["unique_name"] == "store Dimension"
    assert "store s_store_id" in level["secondary_attributes"]

    key_attr = next(a for a in store_dim["level_attributes"] if a["unique_name"] == "store Dimension")
    assert key_attr["is_unique_key"] is True
    assert key_attr["dataset"] == "store"
    assert key_attr["key_columns"] == ["s_store_sk"]


def test_catalog_matches_semantic_model_identity(tpcds_document):
    result = emit_sml_files(tpcds_document)
    catalog = yaml.safe_load(result.files["catalog.yml"])
    assert catalog["object_type"] == "catalog"
    assert catalog["unique_name"] == "tpcds_retail_model"
