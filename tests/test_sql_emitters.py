import duckdb
import pytest

from semantica._vendor.ossie import OssieDialect, OssieDialectExpression
from semantica.transpilers.sql import BigQueryEmitter, DuckDBEmitter, SnowflakeEmitter


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
