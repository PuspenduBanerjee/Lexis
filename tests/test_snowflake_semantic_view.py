from lexis.transpilers.snowflake_semantic_view import emit_snowflake_semantic_view


def test_emits_well_formed_ddl_skeleton(tpcds_model):
    text = emit_snowflake_semantic_view(tpcds_model)

    assert text.startswith("CREATE OR REPLACE SEMANTIC VIEW tpcds_retail_model")
    assert text.strip().endswith(";")
    for keyword in ("TABLES (", "RELATIONSHIPS (", "FACTS (", "DIMENSIONS (", "METRICS ("):
        assert keyword in text


def test_tables_include_source_primary_key_and_comment(tpcds_model):
    text = emit_snowflake_semantic_view(tpcds_model)

    assert "store_sales AS tpcds.public.store_sales" in text
    assert "PRIMARY KEY (ss_item_sk, ss_ticket_number)" in text
    assert "COMMENT = 'Fact table containing all store sales transactions'" in text
    assert "WITH SYNONYMS ('sales transactions'" in text


def test_relationships_use_references_syntax(tpcds_model):
    text = emit_snowflake_semantic_view(tpcds_model)

    assert (
        "store_sales_to_date AS store_sales(ss_sold_date_sk) REFERENCES date_dim(d_date_sk)"
        in text
    )


def test_fields_without_dimension_block_become_facts(tpcds_model):
    text = emit_snowflake_semantic_view(tpcds_model)
    facts_section = text.split("FACTS (")[1].split("DIMENSIONS (")[0]

    assert "store_sales.ss_quantity AS ss_quantity" in facts_section
    assert "store_sales.ss_ext_sales_price AS ss_ext_sales_price" in facts_section
    # FK/attribute fields carry a `dimension` block and belong in DIMENSIONS, not FACTS.
    assert "store_sales.ss_sold_date_sk" not in facts_section


def test_fields_with_dimension_block_become_dimensions(tpcds_model):
    text = emit_snowflake_semantic_view(tpcds_model)
    dimensions_section = text.split("DIMENSIONS (")[1].split("METRICS (")[0]

    assert "store_sales.ss_sold_date_sk AS ss_sold_date_sk" in dimensions_section
    assert "date_dim.d_date AS d_date" in dimensions_section
    assert "store_sales.ss_quantity" not in dimensions_section


def test_metrics_use_snowflake_expression_and_are_qualified(tpcds_model):
    text = emit_snowflake_semantic_view(tpcds_model)
    metrics_section = text.split("METRICS (")[1]

    assert "store_sales.total_sales AS SUM(store_sales.ss_ext_sales_price)" in metrics_section


def test_cross_dataset_metric_attaches_to_first_referenced_dataset(tpcds_model):
    text = emit_snowflake_semantic_view(tpcds_model)
    metrics_section = text.split("METRICS (")[1]

    assert "store_sales.customer_lifetime_value AS SUM(store_sales.ss_ext_sales_price)" in metrics_section
