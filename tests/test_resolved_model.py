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
