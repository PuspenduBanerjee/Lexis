"""Tests for lexis.dispatch's target-alias resolution."""

from lexis.dispatch import TARGET_ALIASES, transpile


def test_ssv_is_an_alias_for_snowflake_semantic_view(tpcds_document, tpcds_model):
    assert TARGET_ALIASES["ssv"] == "snowflake_semantic_view"

    aliased = transpile(tpcds_document, tpcds_model, "ssv")
    canonical = transpile(tpcds_document, tpcds_model, "snowflake_semantic_view")
    assert aliased == canonical


def test_cortex_analyst_is_an_alias_for_snowflake_cortex_analyst(tpcds_document, tpcds_model):
    assert TARGET_ALIASES["cortex_analyst"] == "snowflake_cortex_analyst"

    aliased = transpile(tpcds_document, tpcds_model, "cortex_analyst")
    canonical = transpile(tpcds_document, tpcds_model, "snowflake_cortex_analyst")
    assert aliased == canonical
