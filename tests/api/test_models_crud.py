"""Model CRUD, exercised end-to-end through the HTTP layer."""


def test_create_and_get_reports_correct_counts(client_as, tpcds_yaml):
    create_resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["dataset_count"] == 5
    assert body["metric_count"] == 5
    assert len(body["datasets"]) == 5
    assert len(body["relationships"]) == 4
    assert len(body["metrics"]) == 5
    assert body["name"] == "tpcds_retail_model"

    clv = next(m for m in body["metrics"] if m["name"] == "customer_lifetime_value")
    assert clv["expression"] == "SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk)"
    assert set(clv["referenced_datasets"]) == {"store_sales", "customer"}

    get_resp = client_as("viewer").get(f"/api/models/{body['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["dataset_count"] == 5


def test_create_with_custom_name(client_as, tpcds_yaml):
    resp = client_as("editor").post("/api/models", json={"name": "My Retail Model", "yaml_text": tpcds_yaml})
    assert resp.status_code == 201
    assert resp.json()["name"] == "My Retail Model"


def test_list_summaries(client_as, tpcds_yaml):
    client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    resp = client_as("viewer").get("/api/models")
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 1
    assert "raw_yaml" not in summaries[0]  # summary, not detail


def test_update_model(client_as, tpcds_yaml):
    create_resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    model_id = create_resp.json()["id"]

    updated_yaml = tpcds_yaml.replace("name: tpcds_retail_model", "name: tpcds_retail_model_v2")
    update_resp = client_as("editor").put(f"/api/models/{model_id}", json={"yaml_text": updated_yaml})
    assert update_resp.status_code == 200

    get_resp = client_as("editor").get(f"/api/models/{model_id}")
    assert "tpcds_retail_model_v2" in get_resp.json()["raw_yaml"]


def test_delete_model(client_as, tpcds_yaml):
    create_resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    model_id = create_resp.json()["id"]

    assert client_as("editor").delete(f"/api/models/{model_id}").status_code == 204
    assert client_as("editor").get(f"/api/models/{model_id}").status_code == 404


def test_get_missing_model_is_404(client_as):
    assert client_as("viewer").get("/api/models/999").status_code == 404


def test_create_with_invalid_yaml_is_422(client_as):
    resp = client_as("editor").post("/api/models", json={"yaml_text": "not: [valid, osi"})
    assert resp.status_code == 422


def test_create_with_missing_required_field_is_422(client_as):
    resp = client_as("editor").post("/api/models", json={"yaml_text": "version: '0.2.0.dev0'\nsemantic_model: []"})
    assert resp.status_code == 422
