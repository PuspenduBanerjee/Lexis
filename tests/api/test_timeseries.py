"""Time-series drill-down/roll-up execution: DATE_TRUNC-based grain grouping through
the full HTTP path, against the demo dataset's date_dim rows (see
duckdb_runtime.build_tpcds_demo_connection's docstring for the exact fixture data)."""

import duckdb
import pytest


@pytest.fixture()
def model_id(client_as, tpcds_yaml) -> int:
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    return resp.json()["id"]


def _run(client_as, model_id, **form):
    return client_as("viewer").post(f"/api/models/{model_id}/run/timeseries", data=form)


def test_year_grain_rolls_up_across_quarters(client_as, model_id):
    resp = _run(
        client_as, model_id,
        mode="demo", metric="total_sales", time_dataset="date_dim", time_field="d_date", grain="year",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["columns"] == ["period", "total_sales"]
    periods = {row[0][:10]: row[1] for row in body["rows"]}
    assert periods == pytest.approx({"2023-01-01": 200.0, "2024-01-01": 60.0})


def test_drill_down_into_quarter_within_a_year(client_as, model_id):
    resp = _run(
        client_as, model_id,
        mode="demo", metric="total_sales", time_dataset="date_dim", time_field="d_date", grain="quarter",
        filter_grain="year", filter_value="2023-01-01",
    )
    assert resp.status_code == 200
    body = resp.json()
    periods = {row[0][:10]: row[1] for row in body["rows"]}
    assert periods == pytest.approx({
        "2023-01-01": 80.0,  # Q1: the two original store_sales rows dated 2023-01-15
        "2023-04-01": 20.0,  # Q2
        "2023-07-01": 40.0,  # Q3
        "2023-10-01": 60.0,  # Q4
    })


def test_drill_further_into_month_within_a_quarter(client_as, model_id):
    resp = _run(
        client_as, model_id,
        mode="demo", metric="total_sales", time_dataset="date_dim", time_field="d_date", grain="month",
        filter_grain="quarter", filter_value="2024-01-01",
    )
    assert resp.status_code == 200
    body = resp.json()
    periods = {row[0][:10]: row[1] for row in body["rows"]}
    assert periods == pytest.approx({"2024-01-01": 25.0})


def test_unsupported_grain_is_422(client_as, model_id):
    resp = _run(
        client_as, model_id,
        mode="demo", metric="total_sales", time_dataset="date_dim", time_field="d_date", grain="century",
    )
    assert resp.status_code == 422


def test_unknown_metric_is_422(client_as, model_id):
    resp = _run(
        client_as, model_id,
        mode="demo", metric="does_not_exist", time_dataset="date_dim", time_field="d_date", grain="year",
    )
    assert resp.status_code == 422


def test_unknown_time_dataset_is_422(client_as, model_id):
    resp = _run(
        client_as, model_id,
        mode="demo", metric="total_sales", time_dataset="not_a_dataset", time_field="d_date", grain="year",
    )
    assert resp.status_code == 422


def test_upload_mode_runs_timeseries_against_real_duckdb_file(client_as, model_id, tmp_path):
    db_path = tmp_path / "upload.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE SCHEMA public")
    con.execute(
        "CREATE TABLE public.store_sales (ss_sold_date_sk INT, ss_ext_sales_price DOUBLE, ss_net_profit DOUBLE)"
    )
    con.execute("CREATE TABLE public.date_dim (d_date_sk INT, d_date DATE)")
    con.execute("INSERT INTO public.store_sales VALUES (1, 50.0, 5.0), (2, 30.0, 3.0)")
    con.execute("INSERT INTO public.date_dim VALUES (1, DATE '2025-02-01'), (2, DATE '2025-08-01')")
    con.close()

    with open(db_path, "rb") as f:
        resp = client_as("viewer").post(
            f"/api/models/{model_id}/run/timeseries",
            data={
                "mode": "upload", "metric": "total_sales",
                "time_dataset": "date_dim", "time_field": "d_date", "grain": "year",
            },
            files={"file": ("upload.duckdb", f, "application/octet-stream")},
        )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0][1] == pytest.approx(80.0)
