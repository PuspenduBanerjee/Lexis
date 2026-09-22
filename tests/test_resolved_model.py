import pytest

from lexis._vendor.ossie import OssieDialect
from lexis.resolved_model import MissingExpressionError, UnresolvedJoinError


def test_referenced_datasets_extracts_qualified_refs(tpcds_model):
    metric = tpcds_model.metrics["customer_lifetime_value"]
    expr = tpcds_model.resolve_expression(metric.expression, OssieDialect.ANSI_SQL)
    assert tpcds_model.referenced_datasets(expr) == ["store_sales", "customer"]


def test_join_path_direct_single_hop(tpcds_model):
    path = tpcds_model.join_path(["store_sales", "customer"])
    assert [r.name for r in path] == ["store_sales_to_customer"]


def test_join_path_does_not_pull_in_unrelated_datasets(tpcds_model):
    # item is one hop from store_sales; date_dim/store are also one hop but should
    # NOT appear just because they happen to be adjacent to the BFS root.
    path = tpcds_model.join_path(["store_sales", "item"])
    names = {r.name for r in path}
    assert names == {"store_sales_to_item"}


def test_join_path_multiple_targets_unions_shortest_paths(tpcds_model):
    path = tpcds_model.join_path(["store_sales", "customer", "item"])
    names = {r.name for r in path}
    assert names == {"store_sales_to_customer", "store_sales_to_item"}


def test_join_path_empty_for_single_dataset(tpcds_model):
    assert tpcds_model.join_path(["store_sales"]) == []


def test_join_path_raises_for_unknown_dataset(tpcds_model):
    with pytest.raises(UnresolvedJoinError):
        tpcds_model.join_path(["store_sales", "not_a_real_dataset"])


def test_resolve_expression_falls_back_to_ansi_sql(tpcds_model):
    metric = tpcds_model.metrics["total_sales"]
    # Fixture only defines ANSI_SQL; requesting SNOWFLAKE should fall back.
    expr = tpcds_model.resolve_expression(metric.expression, OssieDialect.SNOWFLAKE)
    assert expr == "SUM(store_sales.ss_ext_sales_price)"


def test_resolve_expression_raises_when_no_fallback_available():
    from lexis._vendor.ossie import OssieDialectExpression, OssieExpression

    expr = OssieExpression(dialects=[OssieDialectExpression(dialect=OssieDialect.SNOWFLAKE, expression="x")])
    from lexis.resolved_model import ResolvedModel

    with pytest.raises(MissingExpressionError):
        ResolvedModel(semantic_model=None).resolve_expression(expr, OssieDialect.DATABRICKS)


# ---- fact/dimension graph analysis (cross-fact group_by validation) --------


def test_fact_datasets_are_the_from_only_side(retail_model):
    # fct_store_sales/fct_store_returns are always `from`, never `to`; every
    # dimension is the reverse - always `to`, never `from`.
    assert retail_model.fact_datasets() == {"fct_store_sales", "fct_store_returns"}


def test_single_fact_model_has_exactly_one_fact(tpcds_model):
    assert tpcds_model.fact_datasets() == {"store_sales"}


def test_reachable_dimensions_stop_at_other_fact_tables(retail_model):
    # dim_promotion only connects to fct_store_sales - fct_store_returns must
    # not reach it just because dim_date bridges to fct_store_sales too.
    assert retail_model.reachable_dimensions("fct_store_sales") == {
        "dim_date", "dim_customer", "dim_item", "dim_store", "dim_promotion",
    }
    assert retail_model.reachable_dimensions("fct_store_returns") == {
        "dim_date", "dim_customer", "dim_item", "dim_store",
    }


def test_allowed_group_by_refs_sizes_match_the_measured_model_shape(retail_model):
    # Measured directly from retail_analytics_model.yaml's field counts: sales =
    # 16 fct_store_sales fields + 48 fields across its 5 reachable dims; returns =
    # 11 fct_store_returns fields + 42 fields across its 4 reachable dims (no
    # dim_promotion). Computed from relationships, not hard-coded here either -
    # this test would fail the moment the counts drift from the model.
    sales_refs = retail_model.allowed_group_by_refs("fct_store_sales")
    returns_refs = retail_model.allowed_group_by_refs("fct_store_returns")
    assert len(sales_refs) == 64
    assert len(returns_refs) == 53
    assert len(sales_refs) == len(set(sales_refs))  # no duplicates
    assert not any(ref.startswith("dim_promotion.") for ref in returns_refs)
    assert not any(ref.startswith("fct_store_sales.") for ref in returns_refs)
    assert not any(ref.startswith("fct_store_returns.") for ref in sales_refs)


def test_metric_home_facts_is_the_single_referenced_fact(retail_model):
    from lexis._vendor.ossie import OssieDialect

    expr = retail_model.resolve_expression(
        retail_model.metrics["total_revenue"].expression, OssieDialect.ANSI_SQL
    )
    assert retail_model.metric_home_facts(expr) == ["fct_store_sales"]


def test_metric_home_facts_ignores_a_one_side_dimension_in_a_ratio(retail_model):
    # sales_per_employee references dim_store (the ratio's denominator dataset)
    # too, but dim_store isn't a fact - home_facts must stay just the one fact.
    from lexis._vendor.ossie import OssieDialect

    expr = retail_model.resolve_expression(
        retail_model.metrics["sales_per_employee"].expression, OssieDialect.ANSI_SQL
    )
    assert retail_model.metric_home_facts(expr) == ["fct_store_sales"]


def test_metric_home_facts_finds_both_facts_for_a_drill_across_metric(retail_model):
    from lexis._vendor.ossie import OssieDialect

    expr = retail_model.resolve_expression(
        retail_model.metrics["return_rate_pct"].expression, OssieDialect.ANSI_SQL
    )
    assert set(retail_model.metric_home_facts(expr)) == {"fct_store_returns", "fct_store_sales"}


def test_metric_allowed_group_by_for_a_single_fact_metric_matches_its_facts_set(retail_model):
    from lexis._vendor.ossie import OssieDialect

    expr = retail_model.resolve_expression(
        retail_model.metrics["return_amount"].expression, OssieDialect.ANSI_SQL
    )
    assert set(retail_model.metric_allowed_group_by(expr)) == set(
        retail_model.allowed_group_by_refs("fct_store_returns")
    )


def test_metric_allowed_group_by_for_a_drill_across_metric_is_the_intersection(retail_model):
    # return_rate_pct's allowed set must be exactly sales ∩ returns: date/
    # customer/item/store only, never promotion (sales-only) or sr_*/ss_* (each
    # fact's own fields, which the other fact can't join to at all).
    from lexis._vendor.ossie import OssieDialect

    expr = retail_model.resolve_expression(
        retail_model.metrics["return_rate_pct"].expression, OssieDialect.ANSI_SQL
    )
    allowed = set(retail_model.metric_allowed_group_by(expr))
    sales_allowed = set(retail_model.allowed_group_by_refs("fct_store_sales"))
    returns_allowed = set(retail_model.allowed_group_by_refs("fct_store_returns"))
    assert allowed == sales_allowed & returns_allowed
    assert not any(ref.startswith("dim_promotion.") for ref in allowed)
    assert not any(ref.startswith("fct_store_sales.") for ref in allowed)
    assert not any(ref.startswith("fct_store_returns.") for ref in allowed)


def test_aggregate_spanning_multiple_facts_is_detected(retail_model):
    assert retail_model.metric_aggregate_spans_multiple_facts(
        "SUM(fct_store_sales.ss_ext_sales_price - fct_store_returns.sr_return_amt)"
    )


def test_separate_per_fact_aggregates_combined_by_a_ratio_are_not_flagged(retail_model):
    # This is exactly return_rate_pct's shape: two *separate* aggregate calls,
    # each touching only one fact - not one aggregate spanning both.
    assert not retail_model.metric_aggregate_spans_multiple_facts(
        "100.0 * SUM(fct_store_returns.sr_return_amt) / NULLIF(SUM(fct_store_sales.ss_ext_sales_price), 0)"
    )


def test_no_existing_metric_expression_is_flagged_as_spanning_facts(retail_model):
    from lexis._vendor.ossie import OssieDialect

    for name, metric in retail_model.metrics.items():
        expr = retail_model.resolve_expression(metric.expression, OssieDialect.ANSI_SQL)
        assert not retail_model.metric_aggregate_spans_multiple_facts(expr), name
