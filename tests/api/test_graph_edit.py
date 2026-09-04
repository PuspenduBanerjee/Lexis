"""PUT /api/models/{id}/graph: structured graph-canvas edits.

The canvas always submits the *full* current graph state (all datasets it knows
about, not a diff), same as a real frontend would after loading GET .../{id} into its
own node/edge state. These tests build that payload from the GET response, mirroring
real usage, then check the merge preserves what the canvas has no control for.
"""

import pytest

from semantica.parser import parse_ossie_yaml


@pytest.fixture()
def model(client_as, tpcds_yaml):
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    return resp.json()


def _datasets_payload(model_detail):
    return [
        {
            "name": d["name"],
            "source": d["source"],
            "fields": [
                {"name": f["name"], "expression": f["expression"], "description": f["description"]}
                for f in d["fields"]
            ],
        }
        for d in model_detail["datasets"]
    ]


def _relationships_payload(model_detail):
    return [
        {
            "name": r["name"],
            "from_dataset": r["from_dataset"],
            "to": r["to"],
            "from_columns": r["from_columns"],
            "to_columns": r["to_columns"],
        }
        for r in model_detail["relationships"]
    ]


def _metrics_payload(model_detail):
    return [
        {"name": m["name"], "expression": m["expression"], "description": m["description"]}
        for m in model_detail["metrics"]
    ]


def test_add_new_dataset_and_field(client_as, model):
    datasets = _datasets_payload(model)
    datasets.append(
        {
            "name": "promotion",
            "source": "tpcds.public.promotion",
            "fields": [{"name": "p_promo_sk", "expression": "p_promo_sk", "description": "Promo key"}],
        }
    )
    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph",
        json={"datasets": datasets, "relationships": _relationships_payload(model), "metrics": _metrics_payload(model)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dataset_count"] == 6
    promo = next(d for d in body["datasets"] if d["name"] == "promotion")
    assert promo["source"] == "tpcds.public.promotion"
    assert promo["fields"][0]["expression"] == "p_promo_sk"


def test_add_new_relationship(client_as, model):
    datasets = _datasets_payload(model)
    relationships = _relationships_payload(model)
    relationships.append(
        {
            "name": "store_sales_to_promotion",
            "from_dataset": "store_sales",
            "to": "store",  # reuse an existing dataset as target, just proving wiring
            "from_columns": ["ss_store_sk"],
            "to_columns": ["s_store_sk"],
        }
    )
    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph",
        json={"datasets": datasets, "relationships": relationships, "metrics": _metrics_payload(model)},
    )
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()["relationships"]}
    assert "store_sales_to_promotion" in names


def test_removing_a_dataset_from_payload_removes_it(client_as, model):
    datasets = [d for d in _datasets_payload(model) if d["name"] != "store"]
    # drop relationships that reference the removed dataset too, or the edit is invalid
    relationships = [r for r in _relationships_payload(model) if "store" not in (r["from_dataset"], r["to"])]

    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph",
        json={"datasets": datasets, "relationships": relationships, "metrics": _metrics_payload(model)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dataset_count"] == 4
    assert "store" not in {d["name"] for d in body["datasets"]}


def test_editing_field_expression_preserves_ai_context_and_dataset_metadata(client_as, model):
    datasets = _datasets_payload(model)
    store_sales = next(d for d in datasets if d["name"] == "store_sales")
    field = next(f for f in store_sales["fields"] if f["name"] == "ss_sold_date_sk")
    field["expression"] = "CAST(ss_sold_date_sk AS INT)"  # the only thing we're changing

    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph",
        json={"datasets": datasets, "relationships": _relationships_payload(model), "metrics": _metrics_payload(model)},
    )
    assert resp.status_code == 200

    document = parse_ossie_yaml(resp.json()["raw_yaml"])
    sm = document.semantic_model[0]
    ss_dataset = next(d for d in sm.datasets if d.name == "store_sales")

    # the edited field's expression changed...
    edited_field = next(f for f in ss_dataset.fields if f.name == "ss_sold_date_sk")
    assert edited_field.expression.dialects[0].expression == "CAST(ss_sold_date_sk AS INT)"
    # ...but its ai_context (which the canvas has no control for) survived
    assert edited_field.ai_context is not None
    assert "sale date" in edited_field.ai_context.synonyms

    # dataset-level attributes the canvas never touched are untouched too
    assert ss_dataset.primary_key == ["ss_item_sk", "ss_ticket_number"]
    assert ss_dataset.ai_context is not None

    # metrics round-tripped unchanged (this test isn't editing them), and
    # model-level custom_extensions (entirely outside the graph payload) survive
    assert len(sm.metrics) == 5
    assert sm.custom_extensions is not None and len(sm.custom_extensions) == 2


def test_unknown_relationship_dataset_is_422(client_as, model):
    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph",
        json={
            "datasets": _datasets_payload(model),
            "relationships": [
                {
                    "name": "bad_rel",
                    "from_dataset": "store_sales",
                    "to": "not_a_real_dataset",
                    "from_columns": ["x"],
                    "to_columns": ["y"],
                }
            ],
        },
    )
    assert resp.status_code == 422


def test_duplicate_dataset_name_is_422(client_as, model):
    datasets = _datasets_payload(model)
    datasets.append(dict(datasets[0]))  # duplicate the first dataset's name
    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph", json={"datasets": datasets, "relationships": []}
    )
    assert resp.status_code == 422


def test_add_new_metric(client_as, model):
    metrics = _metrics_payload(model)
    metrics.append({"name": "avg_sale_price", "expression": "AVG(store_sales.ss_sales_price)", "description": None})

    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph",
        json={
            "datasets": _datasets_payload(model),
            "relationships": _relationships_payload(model),
            "metrics": metrics,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric_count"] == 6
    added = next(m for m in body["metrics"] if m["name"] == "avg_sale_price")
    assert added["expression"] == "AVG(store_sales.ss_sales_price)"


def test_editing_metric_expression_preserves_ai_context(client_as, model):
    metrics = _metrics_payload(model)
    total_sales = next(m for m in metrics if m["name"] == "total_sales")
    total_sales["expression"] = "SUM(store_sales.ss_ext_sales_price) * 1.1"  # the only thing we're changing

    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph",
        json={
            "datasets": _datasets_payload(model),
            "relationships": _relationships_payload(model),
            "metrics": metrics,
        },
    )
    assert resp.status_code == 200

    document = parse_ossie_yaml(resp.json()["raw_yaml"])
    sm = document.semantic_model[0]
    edited = next(m for m in sm.metrics if m.name == "total_sales")
    assert edited.expression.dialects[0].expression == "SUM(store_sales.ss_ext_sales_price) * 1.1"
    # ai_context (which the canvas has no control for) survived
    assert edited.ai_context is not None
    assert "gross sales" in edited.ai_context.synonyms


def test_removing_a_metric_from_payload_removes_it(client_as, model):
    metrics = [m for m in _metrics_payload(model) if m["name"] != "store_productivity"]

    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph",
        json={
            "datasets": _datasets_payload(model),
            "relationships": _relationships_payload(model),
            "metrics": metrics,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric_count"] == 4
    assert "store_productivity" not in {m["name"] for m in body["metrics"]}


def test_duplicate_metric_name_is_422(client_as, model):
    metrics = _metrics_payload(model)
    metrics.append(dict(metrics[0]))  # duplicate the first metric's name

    resp = client_as("editor").put(
        f"/api/models/{model['id']}/graph",
        json={
            "datasets": _datasets_payload(model),
            "relationships": _relationships_payload(model),
            "metrics": metrics,
        },
    )
    assert resp.status_code == 422


def test_viewer_cannot_edit_graph(client_as, model):
    resp = client_as("viewer").put(
        f"/api/models/{model['id']}/graph",
        json={
            "datasets": _datasets_payload(model),
            "relationships": _relationships_payload(model),
            "metrics": _metrics_payload(model),
        },
    )
    assert resp.status_code == 403


def test_admin_can_edit_anyones_graph(client_as, model):
    resp = client_as("admin").put(
        f"/api/models/{model['id']}/graph",
        json={
            "datasets": _datasets_payload(model),
            "relationships": _relationships_payload(model),
            "metrics": _metrics_payload(model),
        },
    )
    assert resp.status_code == 200
