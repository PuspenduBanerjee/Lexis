import duckdb
import pytest

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


def test_snowflake_falls_back_to_ansi_sql_expression(tpcds_model):
    sql = SnowflakeEmitter().emit_metric_query(tpcds_model, "total_sales")
    assert "SUM(store_sales.ss_ext_sales_price)" in sql


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
