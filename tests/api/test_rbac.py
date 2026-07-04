"""RBAC matrix: Admin / Editor / Viewer permissions, per the plan's permission table."""

import pytest


@pytest.fixture()
def editor_model_id(client_as, tpcds_yaml) -> int:
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_unknown_user_id_is_401(client):
    resp = client.get("/api/users/me", headers={"X-User-Id": "999"})
    assert resp.status_code == 401


@pytest.mark.parametrize("role", ["admin", "editor", "viewer"])
def test_any_role_can_list_and_view(client_as, editor_model_id, role):
    assert client_as(role).get("/api/models").status_code == 200
    assert client_as(role).get(f"/api/models/{editor_model_id}").status_code == 200


@pytest.mark.parametrize("role", ["admin", "editor", "viewer"])
def test_any_role_can_transpile_and_run(client_as, editor_model_id, role):
    resp = client_as(role).post(
        f"/api/models/{editor_model_id}/transpile", json={"target": "duckdb", "metric": "total_sales"}
    )
    assert resp.status_code == 200

    resp = client_as(role).post(
        f"/api/models/{editor_model_id}/run",
        data={"mode": "demo", "metric": "total_sales", "group_by_json": "[]"},
    )
    assert resp.status_code == 200


def test_viewer_cannot_create_model(client_as, tpcds_yaml):
    resp = client_as("viewer").post("/api/models", json={"yaml_text": tpcds_yaml})
    assert resp.status_code == 403


def test_editor_can_create_model(client_as, tpcds_yaml):
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    assert resp.status_code == 201


def test_editor_can_edit_own_model(client_as, editor_model_id, tpcds_yaml):
    resp = client_as("editor").put(f"/api/models/{editor_model_id}", json={"yaml_text": tpcds_yaml})
    assert resp.status_code == 200


def test_second_editor_cannot_edit_first_editors_model(client, client_as, editor_model_id, tpcds_yaml):
    from semantica_api.db import SessionLocal
    from semantica_api.models import Role, User

    db = SessionLocal()
    try:
        db.add(User(id=4, username="editor2", role=Role.EDITOR))
        db.commit()
    finally:
        db.close()

    client.headers.update({"X-User-Id": "4"})
    resp = client.put(f"/api/models/{editor_model_id}", json={"yaml_text": tpcds_yaml})
    assert resp.status_code == 403


def test_viewer_cannot_edit_any_model(client_as, editor_model_id, tpcds_yaml):
    resp = client_as("viewer").put(f"/api/models/{editor_model_id}", json={"yaml_text": tpcds_yaml})
    assert resp.status_code == 403


def test_admin_can_edit_anyones_model(client_as, editor_model_id, tpcds_yaml):
    resp = client_as("admin").put(f"/api/models/{editor_model_id}", json={"yaml_text": tpcds_yaml})
    assert resp.status_code == 200


def test_viewer_cannot_delete_model(client_as, editor_model_id):
    resp = client_as("viewer").delete(f"/api/models/{editor_model_id}")
    assert resp.status_code == 403


def test_admin_can_delete_anyones_model(client_as, editor_model_id):
    resp = client_as("admin").delete(f"/api/models/{editor_model_id}")
    assert resp.status_code == 204


def test_non_admin_cannot_list_users(client_as):
    assert client_as("editor").get("/api/users").status_code == 403
    assert client_as("viewer").get("/api/users").status_code == 403


def test_admin_can_list_users(client_as):
    resp = client_as("admin").get("/api/users")
    assert resp.status_code == 200
    assert {u["username"] for u in resp.json()} == {"admin", "editor1", "viewer1"}
