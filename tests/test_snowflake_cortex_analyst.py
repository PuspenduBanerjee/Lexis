import yaml

from lexis.transpilers.snowflake_cortex_analyst import (
    SnowflakeCortexAnalystConversionError,
    emit_snowflake_cortex_analyst,
)


def test_emits_top_level_name_and_description(tpcds_document):
    result = emit_snowflake_cortex_analyst(tpcds_document)
    model = yaml.safe_load(result.artifact.content)

    assert model["name"] == "tpcds_retail_model"
    assert model["description"] == "TPC-DS retail semantic model for sales and customer analytics"


def test_dataset_source_becomes_qualified_uppercase_base_table(tpcds_document):
    result = emit_snowflake_cortex_analyst(tpcds_document)
    model = yaml.safe_load(result.artifact.content)

    store_sales = next(t for t in model["tables"] if t["name"] == "store_sales")
    assert store_sales["base_table"] == {"database": "TPCDS", "schema": "PUBLIC", "table": "STORE_SALES"}


def test_primary_key_and_unique_keys_wrapped_in_columns(tpcds_document):
    result = emit_snowflake_cortex_analyst(tpcds_document)
    model = yaml.safe_load(result.artifact.content)

    store_sales = next(t for t in model["tables"] if t["name"] == "store_sales")
    assert store_sales["primary_key"] == {"columns": ["ss_item_sk", "ss_ticket_number"]}
    assert store_sales["unique_keys"] == [{"columns": ["ss_item_sk", "ss_ticket_number"]}]


def test_fields_are_classified_into_dimensions_time_dimensions_and_facts(tpcds_document):
    result = emit_snowflake_cortex_analyst(tpcds_document)
    model = yaml.safe_load(result.artifact.content)

    store_sales = next(t for t in model["tables"] if t["name"] == "store_sales")
    dimension_names = {f["name"] for f in store_sales.get("dimensions", [])}
    fact_names = {f["name"] for f in store_sales.get("facts", [])}

    # explicit `dimension: {is_time: false}` -> dimension, not time_dimension
    assert "ss_sold_date_sk" in dimension_names
    # a plain measure field with no `dimension` block -> fact
    assert "ss_quantity" in fact_names
    assert "ss_quantity" not in dimension_names


def test_relationship_columns_pair_from_and_to(tpcds_document):
    result = emit_snowflake_cortex_analyst(tpcds_document)
    model = yaml.safe_load(result.artifact.content)

    rel = next(r for r in model["relationships"] if r["name"] == "store_sales_to_date")
    assert rel["left_table"] == "store_sales"
    assert rel["right_table"] == "date_dim"
    assert rel["relationship_columns"] == [{"left_column": "ss_sold_date_sk", "right_column": "d_date_sk"}]


def test_metric_expression_prefers_ansi_sql(tpcds_document):
    result = emit_snowflake_cortex_analyst(tpcds_document)
    model = yaml.safe_load(result.artifact.content)

    total_sales = next(m for m in model["metrics"] if m["name"] == "total_sales")
    assert total_sales["expr"] == "SUM(store_sales.ss_ext_sales_price)"


def test_ai_context_and_custom_extensions_are_dropped_with_a_warning(tpcds_document):
    result = emit_snowflake_cortex_analyst(tpcds_document)

    assert any("ai_context" in w and "custom_extensions" in w for w in result.warnings)


def test_unsupported_version_raises_conversion_error(tpcds_document):
    bad_document = tpcds_document.model_copy(update={"version": "0.1.0"})

    try:
        emit_snowflake_cortex_analyst(bad_document)
        assert False, "expected SnowflakeCortexAnalystConversionError"
    except SnowflakeCortexAnalystConversionError as exc:
        assert "Unsupported Ossie specification version" in str(exc)
