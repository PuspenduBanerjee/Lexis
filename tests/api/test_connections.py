"""CRUD + RBAC for named connections, plus real end-to-end execution against a
duckdb_file connection. Snowflake execution can't be tested against a real account
here, so its connection logic is covered with a mocked `snowflake.connector.connect`
(see test_snowflake_connection_*) - this only proves our code calls the driver
correctly, not that a real Snowflake account would accept the query."""

import os
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from lexis_api import connection_runtime
from lexis_api.models import ConnectionType


@pytest.fixture()
def model_id(client_as, tpcds_yaml) -> int:
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    return resp.json()["id"]


def _duckdb_file_body(name="my-duckdb", path="/tmp/does-not-matter.duckdb"):
    return {"name": name, "type": "duckdb_file", "config": {"path": path}}


def test_editor_can_create_and_admin_can_manage_anyones(client_as):
    resp = client_as("viewer").post("/api/connections", json=_duckdb_file_body())
    assert resp.status_code == 403

    resp = client_as("editor").post("/api/connections", json=_duckdb_file_body())
    assert resp.status_code == 201
    conn_id = resp.json()["id"]

    # another editor can't edit/delete it
    resp = client_as("viewer").put(f"/api/connections/{conn_id}", json=_duckdb_file_body(name="renamed"))
    assert resp.status_code == 403

    # admin can
    resp = client_as("admin").put(f"/api/connections/{conn_id}", json=_duckdb_file_body(name="renamed"))
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"

    resp = client_as("admin").delete(f"/api/connections/{conn_id}")
    assert resp.status_code == 204


def test_any_role_can_list_and_view(client_as):
    resp = client_as("editor").post("/api/connections", json=_duckdb_file_body())
    conn_id = resp.json()["id"]

    assert client_as("viewer").get("/api/connections").status_code == 200
    assert client_as("viewer").get(f"/api/connections/{conn_id}").status_code == 200


def test_get_missing_connection_is_404(client_as):
    resp = client_as("viewer").get("/api/connections/999")
    assert resp.status_code == 404


def test_duplicate_name_is_409(client_as):
    client_as("editor").post("/api/connections", json=_duckdb_file_body(name="dup"))
    resp = client_as("editor").post("/api/connections", json=_duckdb_file_body(name="dup"))
    assert resp.status_code == 409


def test_missing_required_config_key_is_422(client_as):
    resp = client_as("editor").post(
        "/api/connections", json={"name": "bad", "type": "duckdb_file", "config": {}}
    )
    assert resp.status_code == 422


def test_unknown_config_key_is_422(client_as):
    resp = client_as("editor").post(
        "/api/connections",
        json={"name": "bad2", "type": "duckdb_file", "config": {"path": "/x.duckdb", "extra": "nope"}},
    )
    assert resp.status_code == 422


def test_snowflake_requires_account_user_password_env(client_as):
    resp = client_as("editor").post(
        "/api/connections",
        json={"name": "sf", "type": "snowflake", "config": {"account": "abc"}},
    )
    assert resp.status_code == 422


def test_duckdb_file_test_endpoint_reports_missing_file(client_as):
    resp = client_as("editor").post(
        "/api/connections", json=_duckdb_file_body(path="/no/such/file.duckdb")
    )
    conn_id = resp.json()["id"]
    resp = client_as("viewer").post(f"/api/connections/{conn_id}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "no such file" in body["detail"]


def test_duckdb_file_test_endpoint_succeeds_for_real_file(client_as, tmp_path):
    db_path = tmp_path / "real.duckdb"
    con = duckdb.connect(str(db_path))
    con.close()

    resp = client_as("editor").post("/api/connections", json=_duckdb_file_body(path=str(db_path)))
    conn_id = resp.json()["id"]
    resp = client_as("viewer").post(f"/api/connections/{conn_id}/test")
    assert resp.json() == {"ok": True, "detail": "file opened successfully"}


def test_run_metric_query_against_a_duckdb_file_connection(client_as, model_id, tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE SCHEMA public")
    con.execute("CREATE TABLE public.store_sales (ss_ext_sales_price DOUBLE, ss_net_profit DOUBLE)")
    con.execute("INSERT INTO public.store_sales VALUES (50.0, 5.0), (30.0, 3.0)")
    con.close()

    resp = client_as("editor").post(
        "/api/connections", json=_duckdb_file_body(name="warehouse", path=str(db_path))
    )
    conn_id = resp.json()["id"]

    resp = client_as("viewer").post(
        f"/api/models/{model_id}/run",
        data={"mode": "connection", "connection_id": str(conn_id), "metric": "total_sales", "group_by_json": "[]"},
    )
    assert resp.status_code == 200
    assert resp.json()["rows"] == [[80.0]]


def test_run_timeseries_against_a_duckdb_file_connection(client_as, model_id, tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE SCHEMA public")
    con.execute(
        "CREATE TABLE public.store_sales (ss_sold_date_sk INT, ss_ext_sales_price DOUBLE, ss_net_profit DOUBLE)"
    )
    con.execute("CREATE TABLE public.date_dim (d_date_sk INT, d_date DATE)")
    con.execute("INSERT INTO public.store_sales VALUES (1, 50.0, 5.0), (2, 30.0, 3.0)")
    con.execute("INSERT INTO public.date_dim VALUES (1, DATE '2025-02-01'), (2, DATE '2025-08-01')")
    con.close()

    resp = client_as("editor").post(
        "/api/connections", json=_duckdb_file_body(name="warehouse2", path=str(db_path))
    )
    conn_id = resp.json()["id"]

    resp = client_as("viewer").post(
        f"/api/models/{model_id}/run/timeseries",
        data={
            "mode": "connection", "connection_id": str(conn_id), "metric": "total_sales",
            "time_dataset": "date_dim", "time_field": "d_date", "grain": "year",
        },
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0][1] == pytest.approx(80.0)


def test_run_with_unknown_connection_id_is_422(client_as, model_id):
    resp = client_as("viewer").post(
        f"/api/models/{model_id}/run",
        data={"mode": "connection", "connection_id": "999999", "metric": "total_sales", "group_by_json": "[]"},
    )
    assert resp.status_code == 422


def test_run_connection_mode_without_connection_id_is_400(client_as, model_id):
    resp = client_as("viewer").post(
        f"/api/models/{model_id}/run",
        data={"mode": "connection", "metric": "total_sales", "group_by_json": "[]"},
    )
    assert resp.status_code == 400


# --- Snowflake: mocked, since no real account is available in this environment ---


def test_snowflake_connect_uses_password_from_env_var():
    fake_con = MagicMock()
    with patch("lexis_api.connection_runtime.snowflake.connector.connect", return_value=fake_con) as mock_connect:
        os.environ["TEST_SF_PW"] = "s3cret"
        try:
            with connection_runtime.open_snowflake_connection(
                {"account": "acct", "user": "bob", "password_env": "TEST_SF_PW", "warehouse": "WH"}
            ) as con:
                assert con is fake_con
        finally:
            del os.environ["TEST_SF_PW"]

    mock_connect.assert_called_once_with(
        account="acct", user="bob", password="s3cret", warehouse="WH",
        database=None, schema=None, role=None,
    )
    fake_con.close.assert_called_once()


def test_snowflake_connect_missing_env_var_is_400():
    os.environ.pop("TEST_SF_PW_MISSING", None)
    with pytest.raises(Exception) as exc_info:
        with connection_runtime.open_snowflake_connection(
            {"account": "acct", "user": "bob", "password_env": "TEST_SF_PW_MISSING"}
        ):
            pass
    assert "TEST_SF_PW_MISSING" in str(exc_info.value)


def test_emitter_for_connection_type():
    from lexis.transpilers.sql import DuckDBEmitter, SnowflakeEmitter

    assert isinstance(connection_runtime.emitter_for_connection_type(ConnectionType.DUCKDB_FILE), DuckDBEmitter)
    assert isinstance(connection_runtime.emitter_for_connection_type(ConnectionType.SNOWFLAKE), SnowflakeEmitter)
