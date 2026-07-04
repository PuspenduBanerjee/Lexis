"""Upload safety checks: extension allowlist and size cap."""

import pytest


@pytest.fixture()
def model_id(client_as, tpcds_yaml) -> int:
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    return resp.json()["id"]


def test_wrong_extension_is_400(client_as, model_id, tmp_path):
    bad_file = tmp_path / "notadb.txt"
    bad_file.write_text("hello")
    with open(bad_file, "rb") as f:
        resp = client_as("viewer").post(
            f"/api/models/{model_id}/run",
            data={"mode": "upload", "metric": "total_sales", "group_by_json": "[]"},
            files={"file": ("notadb.txt", f, "text/plain")},
        )
    assert resp.status_code == 400


def test_oversized_upload_is_413(client_as, model_id, tmp_path, monkeypatch):
    from semantica_api.config import settings

    monkeypatch.setattr(settings, "max_duckdb_upload_mb", 0)

    big_file = tmp_path / "big.duckdb"
    big_file.write_bytes(b"x" * (2 * 1024 * 1024))
    with open(big_file, "rb") as f:
        resp = client_as("viewer").post(
            f"/api/models/{model_id}/run",
            data={"mode": "upload", "metric": "total_sales", "group_by_json": "[]"},
            files={"file": ("big.duckdb", f, "application/octet-stream")},
        )
    assert resp.status_code == 413


def test_upload_mode_without_file_is_400(client_as, model_id):
    resp = client_as("viewer").post(
        f"/api/models/{model_id}/run",
        data={"mode": "upload", "metric": "total_sales", "group_by_json": "[]"},
    )
    assert resp.status_code == 400
