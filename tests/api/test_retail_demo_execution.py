"""Live DuckDB execution of the bundled `retail_analytics` model against the
generated 10,000-fact retail demo dataset, through the full HTTP path. Numbers are
frozen from the fixed-seed generator in `lexis.retail_demo_data`.
"""

from importlib import resources

import pytest

from lexis.parser import parse_ossie_yaml
from lexis.resolved_model import ResolvedModel
from lexis.transpilers.mcp import model_instructions, time_axis_refs


@pytest.fixture()
def retail_yaml() -> str:
    return (resources.files("lexis_api.sample_data") / "retail_analytics_model.yaml").read_text()


def test_retail_model_hints_its_us_retail_week_in_ai_context(retail_yaml):
    model = ResolvedModel.build(parse_ossie_yaml(retail_yaml).semantic_model[0])
    assert time_axis_refs(model) == ["dim_date.d_date"]
    instructions = model_instructions(model)
    assert "time_grain=week" in instructions
    assert "Sunday" in instructions  # ISO buckets by default, but label as US retail weeks


@pytest.fixture()
def model_id(client_as, retail_yaml) -> int:
    resp = client_as("editor").post("/api/models", json={"yaml_text": retail_yaml})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _run(client_as, model_id, **form):
    return client_as("viewer").post(f"/api/models/{model_id}/run", data=form)


def test_total_revenue_ungrouped(client_as, model_id):
    resp = _run(client_as, model_id, mode="demo", metric="total_revenue", group_by_json="[]")
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"][0][0] == pytest.approx(5_522_357.40, rel=1e-6)


def test_revenue_by_item_category(client_as, model_id):
    resp = _run(
        client_as, model_id,
        mode="demo", metric="total_revenue", group_by_json='["dim_item.i_category"]',
    )
    assert resp.status_code == 200, resp.text
    rows = dict(resp.json()["rows"])
    assert set(rows) == {
        "Apparel", "Automotive", "Beauty", "Books", "Electronics",
        "Grocery", "Home & Kitchen", "Office", "Sports & Outdoors", "Toys & Games",
    }
    assert rows["Electronics"] == pytest.approx(777_151.53, rel=1e-6)
    assert sum(rows.values()) == pytest.approx(5_522_357.40, rel=1e-6)


def test_units_and_transactions(client_as, model_id):
    units = _run(client_as, model_id, mode="demo", metric="units_sold", group_by_json="[]")
    assert units.json()["rows"][0][0] == 24_296
    txns = _run(client_as, model_id, mode="demo", metric="transaction_count", group_by_json="[]")
    assert txns.json()["rows"][0][0] == 3_856


def test_returns_metric_uses_the_second_fact_table(client_as, model_id):
    resp = _run(client_as, model_id, mode="demo", metric="return_amount", group_by_json="[]")
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"][0][0] == pytest.approx(587_990.80, rel=1e-6)


def test_gross_margin_pct_is_a_ratio(client_as, model_id):
    resp = _run(client_as, model_id, mode="demo", metric="gross_margin_pct", group_by_json="[]")
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"][0][0] == pytest.approx(42.43, rel=1e-3)


def test_timeseries_shows_year_over_year_growth(client_as, model_id):
    resp = client_as("viewer").post(
        f"/api/models/{model_id}/run/timeseries",
        data={
            "mode": "demo", "metric": "total_revenue",
            "time_dataset": "dim_date", "time_field": "d_date", "grain": "year",
        },
    )
    assert resp.status_code == 200, resp.text
    periods = {row[0][:4]: row[1] for row in resp.json()["rows"]}
    assert periods["2022"] == pytest.approx(1_247_878.51, rel=1e-6)
    assert periods["2023"] == pytest.approx(1_728_989.17, rel=1e-6)
    assert periods["2024"] == pytest.approx(2_545_489.72, rel=1e-6)


def test_tpcds_metric_on_the_retail_model_is_not_demo_compatible(client_as, model_id, tpcds_yaml):
    """A model whose sources aren't a bundled fixture schema is rejected in demo
    mode (the retail model *is* a fixture, so this proves the negative via tpcds'
    `store` dataset, which no bundled demo provides)."""
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    other_id = resp.json()["id"]
    resp = client_as("viewer").post(
        f"/api/models/{other_id}/run",
        data={"mode": "demo", "metric": "store_productivity", "group_by_json": "[]"},
    )
    assert resp.status_code == 400
