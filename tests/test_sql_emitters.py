import duckdb
import pytest

from lexis._vendor.ossie import OssieDialect, OssieDialectExpression
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
