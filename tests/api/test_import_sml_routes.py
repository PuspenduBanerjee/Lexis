"""`POST /api/models/import/sml`: import a browser-uploaded SML repo as a new model.

Uses the hand-authored `tests/fixtures/sml/` repo (see `tests/conftest.py`'s
`sml_repo_dir` fixture and `tests/test_sml_parser.py`) as real multi-file input -
each file's relative path travels as its multipart filename, exactly like the
frontend's folder-picker upload does.
"""

from pathlib import Path

import pytest

FIXTURES_SML = Path(__file__).resolve().parent.parent / "fixtures" / "sml"


def _sml_repo_files() -> list[tuple[str, tuple[str, bytes]]]:
    """One ("files", (relative_path, content)) tuple per *.yml in the fixture repo -
    httpx's TestClient accepts a list of same-keyed tuples for multiple file uploads
    under one field name."""
    return [
        ("files", (str(path.relative_to(FIXTURES_SML)), path.read_bytes()))
        for path in sorted(FIXTURES_SML.rglob("*.yml"))
    ]


def test_import_sml_creates_a_model(client_as):
    resp = client_as("editor").post("/api/models/import/sml", files=_sml_repo_files())
    assert resp.status_code == 201
    body = resp.json()

    model = body["model"]
    assert model["name"] == "sales_model"
    assert {d["name"] for d in model["datasets"]} == {"orders", "customers"}
    assert {m["name"] for m in model["metrics"]} == {
        "total_revenue",
        "order_count",
        "avg_order_value",
        "yoy_revenue_growth",
    }

    warnings = body["warnings"]
    assert any("pii_restriction" in w for w in warnings)
    assert any("yoy_revenue_growth" in w and "MDX" in w for w in warnings)


def test_import_sml_name_override(client_as):
    resp = client_as("editor").post(
        "/api/models/import/sml", data={"name": "My Imported Model"}, files=_sml_repo_files()
    )
    assert resp.status_code == 201
    assert resp.json()["model"]["name"] == "My Imported Model"


def test_viewer_cannot_import_sml(client_as):
    resp = client_as("viewer").post("/api/models/import/sml", files=_sml_repo_files())
    assert resp.status_code == 403


def test_import_sml_rejects_path_traversal(client_as):
    files = [("files", ("../evil.yml", b"unique_name: x\nobject_type: catalog\n"))]
    resp = client_as("editor").post("/api/models/import/sml", files=files)
    assert resp.status_code == 422


def test_import_sml_missing_catalog_is_422(client_as):
    # Only the model file, no catalog - parse_sml_repo requires exactly one of each.
    files = [
        f
        for f in _sml_repo_files()
        if not f[1][0].startswith("catalog")
    ]
    resp = client_as("editor").post("/api/models/import/sml", files=files)
    assert resp.status_code == 422


@pytest.fixture()
def imported_model_id(client_as) -> int:
    resp = client_as("editor").post("/api/models/import/sml", files=_sml_repo_files())
    return resp.json()["model"]["id"]


def test_imported_model_transpiles_like_any_other_model(client_as, imported_model_id):
    resp = client_as("viewer").post(
        f"/api/models/{imported_model_id}/transpile", json={"target": "duckdb", "metric": "total_revenue"}
    )
    assert resp.status_code == 200
    assert "SUM(orders.amount)" in resp.json()["content"]
