"""Live DuckDB execution through the full HTTP + upload path.

Reuses `lexis_api.duckdb_runtime.build_tpcds_demo_connection` (see that module's
docstring for why this doesn't instead live under tests/fixtures/ as originally
sketched: production code can't depend on the tests/ tree).
"""

import duckdb
import pytest


@pytest.fixture()
def model_id(client_as, tpcds_yaml) -> int:
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    return resp.json()["id"]


def test_demo_mode_matches_unit_test_result(client_as, model_id):
    resp = client_as("viewer").post(
        f"/api/models/{model_id}/run",
        data={"mode": "demo", "metric": "customer_lifetime_value", "group_by_json": '["item.i_category"]'},
    )
    assert resp.status_code == 200
    body = resp.json()
    rows = dict(body["rows"])
    assert rows == pytest.approx({"Books": 30.0, "Electronics": 70.0})
    assert body["sql"] == (
        'SELECT "item".i_category AS "i_category", '
        "SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk) "
        'AS "customer_lifetime_value"\n'
        'FROM tpcds.public.store_sales AS "store_sales"\n'
        'JOIN tpcds.public.customer AS "customer" ON "store_sales".ss_customer_sk = "customer".c_customer_sk\n'
        'JOIN tpcds.public.item AS "item" ON "store_sales".ss_item_sk = "item".i_item_sk\n'
        "GROUP BY 1"
    )


def test_demo_mode_incompatible_dataset_is_400(client_as, model_id):
    # store_productivity references the `store` dataset, which the demo dataset
    # doesn't include (unlike date_dim, added for time-series support - see
    # test_timeseries_*.py assertions for that).
    resp = client_as("viewer").post(
        f"/api/models/{model_id}/run",
        data={"mode": "demo", "metric": "store_productivity", "group_by_json": "[]"},
    )
    assert resp.status_code == 400


def test_upload_mode_runs_against_real_duckdb_file(client_as, model_id, tmp_path):
    db_path = tmp_path / "upload.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE SCHEMA public")
    con.execute("CREATE TABLE public.store_sales (ss_ext_sales_price DOUBLE, ss_net_profit DOUBLE)")
    con.execute("INSERT INTO public.store_sales VALUES (50.0, 5.0), (30.0, 3.0)")
    con.close()

    with open(db_path, "rb") as f:
        resp = client_as("viewer").post(
            f"/api/models/{model_id}/run",
            data={"mode": "upload", "metric": "total_sales", "group_by_json": "[]"},
            files={"file": ("upload.duckdb", f, "application/octet-stream")},
        )
    assert resp.status_code == 200
    assert resp.json()["rows"] == [[80.0]]


def test_upload_mode_wrong_schema_is_400_not_500(client_as, model_id, tmp_path):
    db_path = tmp_path / "wrong.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE some_other_table (x INT)")
    con.close()

    with open(db_path, "rb") as f:
        resp = client_as("viewer").post(
            f"/api/models/{model_id}/run",
            data={"mode": "upload", "metric": "total_sales", "group_by_json": "[]"},
            files={"file": ("wrong.duckdb", f, "application/octet-stream")},
        )
    assert resp.status_code == 400


def test_export_demo_dataset_downloads_a_real_duckdb_file(client_as, model_id, tmp_path):
    """The exported file should be usable as an upload-mode source and produce the
    same result as running directly against the in-memory demo dataset."""
    resp = client_as("viewer").get("/api/demo-dataset/export")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="tpcds-demo.duckdb"'

    db_path = tmp_path / "exported.duckdb"
    db_path.write_bytes(resp.content)

    with open(db_path, "rb") as f:
        run_resp = client_as("viewer").post(
            f"/api/models/{model_id}/run",
            data={"mode": "upload", "metric": "total_sales", "group_by_json": "[]"},
            files={"file": ("exported.duckdb", f, "application/octet-stream")},
        )
    assert run_resp.status_code == 200
    assert run_resp.json()["rows"] == [[260.0]]
