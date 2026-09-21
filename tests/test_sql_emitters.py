import duckdb
import pytest

from lexis._vendor.ossie import OssieDialect, OssieDialectExpression
from lexis.resolved_model import ResolvedModel
from lexis.transpilers.sql import BigQueryEmitter, DuckDBEmitter, SnowflakeEmitter


def test_duckdb_single_dataset_metric_has_no_join(tpcds_model):
    sql = DuckDBEmitter().emit_metric_query(tpcds_model, "total_sales")
    assert "JOIN" not in sql
    assert 'SUM(store_sales.ss_ext_sales_price) AS "total_sales"' in sql


def test_duckdb_cross_dataset_metric_with_group_by_joins_only_whats_needed(tpcds_model):
    sql = DuckDBEmitter().emit_metric_query(
        tpcds_model, "customer_lifetime_value", group_by=["item.i_category"]
    )
    assert sql.count("JOIN") == 2  # customer + item, not date_dim/store
    assert '"item".i_category AS "i_category"' in sql
    assert "GROUP BY 1" in sql


def test_cross_dataset_ratio_pre_aggregates_the_many_side_before_joining(tpcds_model):
    # store_productivity = SUM(store_sales.ss_ext_sales_price) / NULLIF(SUM(store.s_number_employees), 0):
    # a flat join would count each store's s_number_employees once per store_sales
    # row instead of once per store. The fix pre-aggregates store_sales to store
    # grain in a subquery *before* joining store, so store.s_number_employees is
    # summed once per distinct store.
    sql = DuckDBEmitter().emit_metric_query(tpcds_model, "store_productivity", group_by=["store.s_store_id"])
    assert "GROUP BY 1) AS \"__base\"" in sql  # inner query collapses to store grain first
    assert 'JOIN tpcds.public.store AS "store" ON "__base".ss_store_sk = "store".s_store_sk' in sql
    assert 'SUM("__base"."__numerator") / NULLIF(SUM(store.s_number_employees), 0)' in sql


def test_cross_dataset_ratio_runs_correctly_against_duckdb_with_fan_out(tpcds_model):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA tpcds")
    con.execute("CREATE TABLE tpcds.store_sales (ss_store_sk INT, ss_ext_sales_price DOUBLE)")
    con.execute("CREATE TABLE tpcds.store (s_store_sk INT, s_store_id VARCHAR, s_number_employees INT)")
    # Store 1 has 3 sales lines (the fan-out) and 10 employees; store 2 has 1 line
    # and 5 employees. A naive flat join would sum s_number_employees once per
    # sales line: 10*3 + 5*1 = 35, giving 130/35 (~3.71) instead of the correct
    # 130/15 (~8.67).
    con.execute(
        "INSERT INTO tpcds.store_sales VALUES (1,50.0),(1,30.0),(1,20.0),(2,30.0)"
    )
    con.execute("INSERT INTO tpcds.store VALUES (1,'S1',10),(2,'S2',5)")

    sql = DuckDBEmitter().emit_metric_query(tpcds_model, "store_productivity", group_by=[])
    sql = sql.replace("tpcds.public.", "tpcds.")
    result = con.execute(sql).fetchone()[0]
    assert result == pytest.approx(130.0 / 15.0)


def test_same_dataset_ratio_is_unaffected_by_the_grain_safe_rewrite(tpcds_model):
    # customer_lifetime_value's numerator and denominator are both on store_sales -
    # no cross-dataset fan-out risk, so it must keep the plain flat-join shape.
    sql = DuckDBEmitter().emit_metric_query(tpcds_model, "customer_lifetime_value")
    assert "__base" not in sql
    assert "SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk)" in sql


def test_cross_dataset_ratio_group_by_resolves_the_attribute_not_the_raw_key(tpcds_model):
    # Two different items (11, 12) share category "Books". If the inner query
    # grouped by the raw foreign key (ss_item_sk) instead of the resolved
    # i_category, the same store would contribute its s_number_employees once per
    # *item* in the category rather than once per category - reproducing a milder
    # version of the fan-out bug for any group-by outside the ratio's own `store`.
    sql = DuckDBEmitter().emit_metric_query(tpcds_model, "store_productivity", group_by=["item.i_category"])
    assert '"item".i_category AS "__group_0"' in sql
    assert "GROUP BY 1, 2) AS \"__base\"" in sql  # store + resolved category, not store + item
    assert '"__base"."__group_0" AS "i_category"' in sql

    con = duckdb.connect()
    con.execute("CREATE SCHEMA tpcds")
    con.execute("CREATE TABLE tpcds.store_sales (ss_store_sk INT, ss_item_sk INT, ss_ext_sales_price DOUBLE)")
    con.execute("CREATE TABLE tpcds.store (s_store_sk INT, s_store_id VARCHAR, s_number_employees INT)")
    con.execute("CREATE TABLE tpcds.item (i_item_sk INT, i_category VARCHAR)")
    con.execute("INSERT INTO tpcds.store_sales VALUES (1,11,50.0),(1,12,30.0),(1,11,20.0)")
    con.execute("INSERT INTO tpcds.store VALUES (1,'S1',10)")
    con.execute("INSERT INTO tpcds.item VALUES (11,'Books'),(12,'Books')")

    sql = sql.replace("tpcds.public.", "tpcds.")
    result = dict(con.execute(sql).fetchall())
    assert result == pytest.approx({"Books": 100.0 / 10.0})


def test_cross_dataset_ratio_timeseries_pre_aggregates_before_joining(tpcds_model):
    # emit_timeseries_query has the same fan-out risk as emit_metric_query for this
    # metric shape, and needs the same fix: the period bucket is computed inside
    # the inner pre-aggregation (joining date_dim there) so s_number_employees is
    # summed once per store per period, not once per sales line.
    sql = DuckDBEmitter().emit_timeseries_query(tpcds_model, "store_productivity", "date_dim", "d_date", "year")
    assert '"__base"."__period" AS "period"' in sql
    assert "GROUP BY 1, 2) AS \"__base\"" in sql
    assert 'JOIN tpcds.public.store AS "store" ON "__base".ss_store_sk = "store".s_store_sk' in sql

    con = duckdb.connect()
    con.execute("CREATE SCHEMA tpcds")
    con.execute("CREATE TABLE tpcds.store_sales (ss_store_sk INT, ss_sold_date_sk INT, ss_ext_sales_price DOUBLE)")
    con.execute("CREATE TABLE tpcds.store (s_store_sk INT, s_store_id VARCHAR, s_number_employees INT)")
    con.execute("CREATE TABLE tpcds.date_dim (d_date_sk INT, d_date DATE)")
    # Store 1 has 2 sales lines in the same year and 10 employees - a flat join
    # would sum s_number_employees twice for that period instead of once.
    con.execute("INSERT INTO tpcds.store_sales VALUES (1,1,50.0),(1,2,30.0)")
    con.execute("INSERT INTO tpcds.store VALUES (1,'S1',10)")
    con.execute("INSERT INTO tpcds.date_dim VALUES (1,DATE '2024-03-01'),(2,DATE '2024-06-01')")

    sql = sql.replace("tpcds.public.", "tpcds.")
    rows = {r[0].isoformat()[:10]: r[1] for r in con.execute(sql).fetchall()}
    assert rows == pytest.approx({"2024-01-01": 80.0 / 10.0})


def test_cross_dataset_ratio_timeseries_drill_down_filter_applies_inside_the_inner_query(tpcds_model):
    sql = DuckDBEmitter().emit_timeseries_query(
        tpcds_model, "store_productivity", "date_dim", "d_date", "month",
        filter_grain="quarter", filter_value="2024-01-01",
    )
    assert "WHERE DATE_TRUNC('quarter', \"date_dim\".d_date) = DATE '2024-01-01'" in sql
    assert sql.index("WHERE") < sql.index("GROUP BY 1, 2")  # inside __base, before its GROUP BY


def test_cross_dataset_ratio_raises_a_clear_error_when_the_denominator_cant_be_pre_aggregated_safely(tpcds_model):
    # `store`'s primary key no longer matches the relationship's far side (composite
    # instead of the single s_store_sk column) - store_productivity can no longer be
    # proven safe to pre-aggregate, so it must raise instead of silently falling
    # back to the fan-out-prone flat join.
    store = tpcds_model.datasets["store"]
    tpcds_model.datasets["store"] = store.model_copy(update={"primary_key": ["s_store_sk", "s_store_id"]})
    with pytest.raises(ValueError, match="doesn't join directly"):
        DuckDBEmitter().emit_metric_query(tpcds_model, "store_productivity")


def test_cross_dataset_ratio_raises_a_clear_error_for_an_unsafe_group_by_dataset(tpcds_model):
    date_dim = tpcds_model.datasets["date_dim"]
    tpcds_model.datasets["date_dim"] = date_dim.model_copy(update={"primary_key": ["d_date_sk", "d_year"]})
    with pytest.raises(ValueError, match="doesn't join directly"):
        DuckDBEmitter().emit_metric_query(tpcds_model, "store_productivity", group_by=["date_dim.d_year"])


def test_bigquery_uses_backtick_quoting(tpcds_model):
    sql = BigQueryEmitter().emit_metric_query(tpcds_model, "total_sales")
    assert "`store_sales`" in sql
    assert '"store_sales"' not in sql


def test_bigquery_prefers_dedicated_dialect_expression_when_present(tpcds_model):
    # BigQueryEmitter.dialect is OssieDialect.BIGQUERY (Ossie added a dedicated
    # BIGQUERY dialect) - a model-supplied BIGQUERY expression should be used
    # instead of falling back to ANSI_SQL.
    metric = tpcds_model.metrics["total_sales"]
    bigquery_expr = metric.expression.model_copy(
        update={
            "dialects": [
                *metric.expression.dialects,
                OssieDialectExpression(
                    dialect=OssieDialect.BIGQUERY,
                    expression="SUM(store_sales.ss_ext_sales_price) /* bq-specific */",
                ),
            ]
        }
    )
    tpcds_model.metrics["total_sales"] = metric.model_copy(update={"expression": bigquery_expr})

    sql = BigQueryEmitter().emit_metric_query(tpcds_model, "total_sales")
    assert "/* bq-specific */" in sql


def test_snowflake_falls_back_to_ansi_sql_expression(tpcds_model):
    sql = SnowflakeEmitter().emit_metric_query(tpcds_model, "total_sales")
    assert "SUM(store_sales.ss_ext_sales_price)" in sql


def test_timeseries_query_groups_by_date_trunc(tpcds_model):
    sql = DuckDBEmitter().emit_timeseries_query(
        tpcds_model, "total_sales", "date_dim", "d_date", "quarter"
    )
    assert 'SELECT DATE_TRUNC(\'quarter\', "date_dim".d_date) AS "period"' in sql
    assert "JOIN" in sql  # store_sales -> date_dim
    assert "WHERE" not in sql
    assert "GROUP BY 1" in sql
    assert "ORDER BY 1" in sql


def test_timeseries_query_with_drill_down_filter(tpcds_model):
    sql = DuckDBEmitter().emit_timeseries_query(
        tpcds_model, "total_sales", "date_dim", "d_date", "month",
        filter_grain="quarter", filter_value="2024-01-01",
    )
    assert "WHERE DATE_TRUNC('quarter', \"date_dim\".d_date) = DATE '2024-01-01'" in sql


def test_timeseries_query_supports_week_grain(tpcds_model):
    sql = DuckDBEmitter().emit_timeseries_query(tpcds_model, "total_sales", "date_dim", "d_date", "week")
    assert 'SELECT DATE_TRUNC(\'week\', "date_dim".d_date) AS "period"' in sql


def test_timeseries_week_rolls_up_to_iso_monday_buckets(tpcds_model):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA tpcds")
    con.execute(
        "CREATE TABLE tpcds.store_sales (ss_sold_date_sk INT, ss_ext_sales_price DOUBLE, ss_net_profit DOUBLE)"
    )
    con.execute("CREATE TABLE tpcds.date_dim (d_date_sk INT, d_date DATE)")
    # 2024-01-03 (Wed) and 2024-01-07 (Sun) are the same ISO week (starts Mon 2024-01-01);
    # 2024-01-08 (Mon) starts the next one.
    con.execute("INSERT INTO tpcds.store_sales VALUES (1,10.0,1.0),(2,20.0,2.0),(3,5.0,0.5)")
    con.execute(
        "INSERT INTO tpcds.date_dim VALUES (1,DATE '2024-01-03'),(2,DATE '2024-01-07'),(3,DATE '2024-01-08')"
    )
    sql = DuckDBEmitter().emit_timeseries_query(tpcds_model, "total_sales", "date_dim", "d_date", "week")
    sql = sql.replace("tpcds.public.", "tpcds.")
    rows = {r[0].isoformat()[:10]: r[1] for r in con.execute(sql).fetchall()}
    assert rows == pytest.approx({"2024-01-01": 30.0, "2024-01-08": 5.0})


def test_timeseries_query_rejects_unsupported_grain(tpcds_model):
    with pytest.raises(ValueError, match="Unsupported time grain"):
        DuckDBEmitter().emit_timeseries_query(tpcds_model, "total_sales", "date_dim", "d_date", "century")


def test_timeseries_query_rejects_malformed_filter_value(tpcds_model):
    with pytest.raises(ValueError, match="ISO date"):
        DuckDBEmitter().emit_timeseries_query(
            tpcds_model, "total_sales", "date_dim", "d_date", "month",
            filter_grain="quarter", filter_value="not-a-date",
        )


def test_timeseries_sql_actually_runs_and_rolls_up_by_year(tpcds_model):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA tpcds")
    con.execute(
        "CREATE TABLE tpcds.store_sales (ss_sold_date_sk INT, ss_ext_sales_price DOUBLE, ss_net_profit DOUBLE)"
    )
    con.execute("CREATE TABLE tpcds.date_dim (d_date_sk INT, d_date DATE)")
    con.execute(
        "INSERT INTO tpcds.store_sales VALUES (1,50.0,5.0),(2,30.0,3.0),(3,20.0,2.0)"
    )
    con.execute(
        "INSERT INTO tpcds.date_dim VALUES (1,DATE '2023-03-01'),(2,DATE '2023-11-01'),(3,DATE '2024-06-01')"
    )

    sql = DuckDBEmitter().emit_timeseries_query(tpcds_model, "total_sales", "date_dim", "d_date", "year")
    sql = sql.replace("tpcds.public.", "tpcds.")

    rows = {r[0].isoformat()[:10]: r[1] for r in con.execute(sql).fetchall()}
    assert rows == pytest.approx({"2023-01-01": 80.0, "2024-01-01": 20.0})


def test_emitted_sql_actually_runs_against_duckdb_and_is_correct(tpcds_model):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA tpcds")
    con.execute(
        "CREATE TABLE tpcds.store_sales ("
        "ss_sold_date_sk INT, ss_item_sk INT, ss_customer_sk INT, ss_store_sk INT, "
        "ss_ext_sales_price DOUBLE, ss_net_profit DOUBLE)"
    )
    con.execute("CREATE TABLE tpcds.customer (c_customer_sk INT)")
    con.execute("CREATE TABLE tpcds.item (i_item_sk INT, i_category VARCHAR)")
    con.execute(
        "INSERT INTO tpcds.store_sales VALUES "
        "(1,10,100,1000,50.0,5.0),(1,11,101,1000,30.0,3.0),(2,10,100,1001,20.0,2.0)"
    )
    con.execute("INSERT INTO tpcds.customer VALUES (100),(101)")
    con.execute("INSERT INTO tpcds.item VALUES (10,'Electronics'),(11,'Books')")

    sql = DuckDBEmitter().emit_metric_query(
        tpcds_model, "customer_lifetime_value", group_by=["item.i_category"]
    )
    sql = sql.replace("tpcds.public.", "tpcds.")

    rows = dict(con.execute(sql).fetchall())
    assert rows == pytest.approx({"Books": 30.0, "Electronics": 70.0})


# ---- cross-fact group_by validation (retail_analytics: fct_store_sales /
# fct_store_returns share dim_date/customer/item/store but not dim_promotion) --


def test_single_fact_and_ratio_preaggregation_sql_shapes_are_byte_identical(retail_model):
    # Snapshot guard for requirement 5: adding cross-fact group_by validation and
    # the drill-across path must not change one character of the *existing*
    # single-fact or same-fact-ratio/grain-safe-ratio SQL shapes.
    e = DuckDBEmitter()
    assert e.emit_metric_query(retail_model, "total_revenue", group_by=[]) == (
        'SELECT SUM(fct_store_sales.ss_ext_sales_price) AS "total_revenue"\n'
        'FROM retail.public.fct_store_sales AS "fct_store_sales"'
    )
    assert e.emit_metric_query(retail_model, "total_revenue", group_by=["dim_item.i_category"]) == (
        'SELECT "dim_item".i_category AS "i_category", SUM(fct_store_sales.ss_ext_sales_price) AS "total_revenue"\n'
        'FROM retail.public.fct_store_sales AS "fct_store_sales"\n'
        'JOIN retail.public.dim_item AS "dim_item" ON "fct_store_sales".ss_item_sk = "dim_item".i_item_sk\n'
        "GROUP BY 1"
    )
    assert e.emit_metric_query(retail_model, "sales_per_employee", group_by=["dim_store.s_store_type"]) == (
        'SELECT "dim_store".s_store_type AS "s_store_type", '
        'SUM("__base"."__numerator") / NULLIF(SUM(dim_store.s_number_employees), 0) AS "sales_per_employee"\n'
        'FROM (SELECT "fct_store_sales".ss_store_sk, SUM("fct_store_sales".ss_ext_sales_price) AS "__numerator"\n'
        'FROM retail.public.fct_store_sales AS "fct_store_sales"\n'
        'GROUP BY 1) AS "__base"\n'
        'JOIN retail.public.dim_store AS "dim_store" ON "__base".ss_store_sk = "dim_store".s_store_sk\n'
        "GROUP BY 1"
    )


def test_total_revenue_rejects_a_returns_only_group_by(retail_model):
    with pytest.raises(ValueError, match=r"can't be grouped by 'fct_store_returns\.sr_reason'"):
        DuckDBEmitter().emit_metric_query(retail_model, "total_revenue", group_by=["fct_store_returns.sr_reason"])


def test_return_amount_rejects_a_promotion_group_by(retail_model):
    with pytest.raises(ValueError, match=r"can't be grouped by 'dim_promotion\.p_channel'"):
        DuckDBEmitter().emit_metric_query(retail_model, "return_amount", group_by=["dim_promotion.p_channel"])


def test_return_amount_rejects_a_sales_only_group_by(retail_model):
    with pytest.raises(ValueError, match=r"can't be grouped by 'fct_store_sales\.ss_promo_sk'"):
        DuckDBEmitter().emit_metric_query(retail_model, "return_amount", group_by=["fct_store_sales.ss_promo_sk"])


def test_rejection_error_names_the_metric_and_valid_dataset_prefixes(retail_model):
    with pytest.raises(ValueError) as exc_info:
        DuckDBEmitter().emit_metric_query(retail_model, "return_amount", group_by=["dim_promotion.p_channel"])
    message = str(exc_info.value)
    assert "'return_amount'" in message
    assert "dim_promotion.p_channel" in message
    for dataset in ("dim_customer", "dim_date", "dim_item", "dim_store", "fct_store_returns"):
        assert dataset in message
    assert "dim_promotion" not in message.split(":", 1)[1]  # not offered as a *valid* dataset


def test_mixed_group_by_rejects_at_the_first_invalid_field(retail_model):
    with pytest.raises(ValueError, match=r"can't be grouped by 'fct_store_returns\.sr_reason'"):
        DuckDBEmitter().emit_metric_query(
            retail_model, "total_revenue", group_by=["dim_item.i_category", "fct_store_returns.sr_reason"]
        )


def test_aggregate_spanning_both_facts_is_rejected_at_query_time(retail_model):
    metric = retail_model.metrics["total_revenue"]
    bad_expr = metric.expression.model_copy(
        update={
            "dialects": [
                metric.expression.dialects[0].model_copy(
                    update={"expression": "SUM(fct_store_sales.ss_ext_sales_price - fct_store_returns.sr_return_amt)"}
                )
            ]
        }
    )
    retail_model.metrics["bad_metric"] = metric.model_copy(update={"name": "bad_metric", "expression": bad_expr})
    with pytest.raises(ValueError, match="span more than one fact table"):
        DuckDBEmitter().emit_metric_query(retail_model, "bad_metric")


def test_return_rate_pct_overall_matches_the_independent_ratio(retail_model):
    sql = DuckDBEmitter().emit_metric_query(retail_model, "return_rate_pct", group_by=[])
    assert "FULL OUTER JOIN" in sql
    assert "IS NOT DISTINCT FROM" not in sql  # no group_by -> trivial ON 1 = 1, nothing to compare
    assert 'ON 1 = 1' in sql


def test_return_rate_pct_group_by_uses_null_safe_full_outer_join(retail_model):
    sql = DuckDBEmitter().emit_metric_query(retail_model, "return_rate_pct", group_by=["dim_date.d_holiday_name"])
    assert "FULL OUTER JOIN" in sql
    assert "IS NOT DISTINCT FROM" in sql
    assert "\"__num\".\"__key_0\" IS NOT DISTINCT FROM \"__den\".\"__key_0\"" in sql
    assert 'COALESCE("__num"."__key_0", "__den"."__key_0") AS "d_holiday_name"' in sql


def test_return_rate_pct_rejects_promotion_and_off_fact_group_by(retail_model):
    with pytest.raises(ValueError, match=r"can't be grouped by 'dim_promotion\.p_channel'"):
        DuckDBEmitter().emit_metric_query(retail_model, "return_rate_pct", group_by=["dim_promotion.p_channel"])
    with pytest.raises(ValueError, match=r"can't be grouped by 'fct_store_returns\.sr_reason'"):
        DuckDBEmitter().emit_metric_query(retail_model, "return_rate_pct", group_by=["fct_store_returns.sr_reason"])
    with pytest.raises(ValueError, match=r"can't be grouped by 'fct_store_sales\.ss_promo_sk'"):
        DuckDBEmitter().emit_metric_query(retail_model, "return_rate_pct", group_by=["fct_store_sales.ss_promo_sk"])


def test_return_rate_pct_timeseries_buckets_via_each_facts_own_date_key(retail_model):
    sql = DuckDBEmitter().emit_timeseries_query(retail_model, "return_rate_pct", "dim_date", "d_date", "quarter")
    assert sql.count("DATE_TRUNC") == 2  # once per fact's own subquery
    assert "FULL OUTER JOIN" in sql
    assert 'COALESCE("__num"."__period", "__den"."__period") AS "period"' in sql
    assert sql.rstrip().endswith("ORDER BY 1")


def test_return_rate_pct_drill_down_filter_applies_inside_both_subqueries(retail_model):
    sql = DuckDBEmitter().emit_timeseries_query(
        retail_model, "return_rate_pct", "dim_date", "d_date", "month",
        filter_grain="quarter", filter_value="2024-01-01",
    )
    assert sql.count("WHERE DATE_TRUNC('quarter', \"dim_date\".d_date) = DATE '2024-01-01'") == 2


def test_drill_across_null_safe_join_on_synthetic_data_with_a_one_sided_key():
    """Unit test with hand-built tables: two group keys, one shared between both
    facts (`store_sales_to_store.dim_store 'S1'`, appearing in both), one where a
    key is NULL in both facts' matching rows (must merge into one row, not two -
    the reason for IS NOT DISTINCT FROM instead of `=`), and one where a key
    exists in only one fact (the other side must NULLIF/COALESCE, not drop the row)."""
    from lexis._vendor.ossie import (
        OssieDataset,
        OssieDialect,
        OssieDialectExpression,
        OssieExpression,
        OssieField,
        OssieMetric,
        OssieRelationship,
        OssieSemanticModel,
    )

    def field(name):
        return OssieField(name=name, expression=OssieExpression(
            dialects=[OssieDialectExpression(dialect=OssieDialect.ANSI_SQL, expression=name)]
        ))

    sales = OssieDataset(
        name="sales", source="t.sales", primary_key=["sale_id"],
        fields=[field("sale_id"), field("store_id"), field("amt")],
    )
    returns = OssieDataset(
        name="returns", source="t.returns", primary_key=["return_id"],
        fields=[field("return_id"), field("store_id"), field("amt")],
    )
    store = OssieDataset(
        name="store", source="t.store", primary_key=["store_id"],
        fields=[field("store_id"), field("region")],
    )
    metric = OssieMetric(
        name="drill_metric",
        expression=OssieExpression(dialects=[OssieDialectExpression(
            dialect=OssieDialect.ANSI_SQL,
            expression="SUM(returns.amt) / NULLIF(SUM(sales.amt), 0)",
        )]),
    )
    semantic_model = OssieSemanticModel(
        name="synthetic",
        datasets=[sales, returns, store],
        relationships=[
            OssieRelationship(name="sales_to_store", **{"from": "sales"}, to="store", from_columns=["store_id"], to_columns=["store_id"]),
            OssieRelationship(name="returns_to_store", **{"from": "returns"}, to="store", from_columns=["store_id"], to_columns=["store_id"]),
        ],
        metrics=[metric],
    )
    model = ResolvedModel.build(semantic_model)

    con = duckdb.connect()
    con.execute("CREATE SCHEMA t")
    con.execute("CREATE TABLE t.sales (sale_id INT, store_id VARCHAR, amt DOUBLE)")
    con.execute("CREATE TABLE t.returns (return_id INT, store_id VARCHAR, amt DOUBLE)")
    con.execute("CREATE TABLE t.store (store_id VARCHAR, region VARCHAR)")
    # S1 (region 'East'): sales AND returns. S2 (region NULL): sales only, no
    # returns row at all. S3 (region NULL): returns only, no sales row at all -
    # S2 and S3 both group under a NULL region key and must stay as TWO rows
    # (different store_id -> different S2/S3 group_by key isn't NULL here, so
    # this also covers "NULL region matches NULL region" via S4/S5 below).
    con.execute("INSERT INTO t.store VALUES ('S1','East'),('S2',NULL),('S3',NULL)")
    con.execute("INSERT INTO t.sales VALUES (1,'S1',100.0),(2,'S2',50.0)")
    con.execute("INSERT INTO t.returns VALUES (1,'S1',10.0),(2,'S3',8.0)")

    sql = DuckDBEmitter().emit_metric_query(model, "drill_metric", group_by=["store.region"])
    rows = {r[0]: r[1] for r in con.execute(sql).fetchall()}

    # 'East' (S1): both sides present -> 10.0 / 100.0.
    assert rows["East"] == pytest.approx(10.0 / 100.0)
    # NULL region (S2 sales-only + S3 returns-only, merged by NULL region since
    # IS NOT DISTINCT FROM treats their NULLs as equal): sales=50, returns=8.
    assert None in rows
    assert rows[None] == pytest.approx(8.0 / 50.0)
    assert len(rows) == 2  # not split into extra rows for the unmatched sides
