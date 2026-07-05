"""Prove the transpile route wires to the right emitter for each target.

Transpilation *correctness* is already covered by the existing tests/test_*.py
(test_sql_emitters.py, test_cube_emitter.py, test_dbt_osi.py, test_mcp.py) - these
tests only prove the route calls the right function with the right args.
"""

import json

import pytest


@pytest.fixture()
def model_id(client_as, tpcds_yaml) -> int:
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    return resp.json()["id"]


@pytest.mark.parametrize(
    ("target", "expected_substring"),
    [
        ("duckdb", 'FROM tpcds.public.store_sales AS "store_sales"'),
        ("postgres", 'FROM tpcds.public.store_sales AS "store_sales"'),
        ("bigquery", "FROM tpcds.public.store_sales AS `store_sales`"),
        ("databricks", "FROM tpcds.public.store_sales AS `store_sales`"),
        ("snowflake", 'FROM tpcds.public.store_sales AS "store_sales"'),
    ],
)
def test_sql_targets(client_as, model_id, target, expected_substring):
    resp = client_as("viewer").post(
        f"/api/models/{model_id}/transpile", json={"target": target, "metric": "total_sales"}
    )
    assert resp.status_code == 200
    assert expected_substring in resp.json()["content"]


def test_sql_target_without_metric_is_422(client_as, model_id):
    resp = client_as("viewer").post(f"/api/models/{model_id}/transpile", json={"target": "duckdb"})
    assert resp.status_code == 422


def test_cube_target(client_as, model_id):
    resp = client_as("viewer").post(f"/api/models/{model_id}/transpile", json={"target": "cube"})
    assert resp.status_code == 200
    assert "cubes:" in resp.json()["content"]


def test_dbt_target(client_as, model_id):
    resp = client_as("viewer").post(f"/api/models/{model_id}/transpile", json={"target": "dbt"})
    assert resp.status_code == 200
    body = resp.json()
    assert json.loads(body["content"])["version"] == "0.1.1"
    assert any("not dbt-supported" in w for w in body["warnings"])


def test_mcp_target(client_as, model_id):
    resp = client_as("viewer").post(f"/api/models/{model_id}/transpile", json={"target": "mcp"})
    assert resp.status_code == 200
    assert "tools" in json.loads(resp.json()["content"])


def test_snowflake_semantic_view_target(client_as, model_id):
    resp = client_as("viewer").post(
        f"/api/models/{model_id}/transpile", json={"target": "snowflake_semantic_view"}
    )
    assert resp.status_code == 200
    content = resp.json()["content"]
    assert content.startswith("CREATE OR REPLACE SEMANTIC VIEW")
    assert "TABLES (" in content
