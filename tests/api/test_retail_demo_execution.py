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


def test_model_detail_api_exposes_the_same_instructions_the_mcp_servers_use(client_as, retail_yaml):
    # Regression test: the REST API's ModelDetailOut used to omit ai_context
    # instructions entirely, so a caller reading it (e.g. the WebMCP list_metrics
    # tool, which has no other way to reach this text) never saw guidance like
    # "don't combine sales and returns" or the US retail week note - even though
    # the Python MCP servers' own list_metrics/server instructions always did,
    # via this same model_instructions(). Both surfaces must now agree exactly.
    model = ResolvedModel.build(parse_ossie_yaml(retail_yaml).semantic_model[0])
    expected = model_instructions(model)

    resp = client_as("editor").post("/api/models", json={"yaml_text": retail_yaml})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["instructions"] == expected
    assert "sales and returns are separate facts" in body["instructions"]
    assert "return_rate_pct" in body["instructions"]
    assert "Sunday" in body["instructions"]


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


def test_sales_per_employee_is_thousands_not_pennies(client_as, model_id):
    # Regression test: sales_per_employee's denominator (dim_store.s_number_employees)
    # used to be summed at fct_store_sales' line-item grain, counting each store's
    # headcount once per sales line instead of once per store - a store with 400
    # sales lines had its employee count inflated ~400x, so the metric came out as
    # single-digit-dollar noise ($3.50-$33/employee) against $416K-$2.7M of revenue
    # per store type. Every store here has 10-177 employees (see
    # lexis.retail_demo_data), so a correct per-employee revenue share, even summed
    # over a handful of stores of one type, lands in the thousands of dollars - not
    # pennies, and not comparable to total revenue itself.
    resp = _run(
        client_as, model_id,
        mode="demo", metric="sales_per_employee", group_by_json='["dim_store.s_store_type"]',
    )
    assert resp.status_code == 200, resp.text
    rows = dict(resp.json()["rows"])
    assert set(rows) == {"Flagship", "Standard", "Express", "Outlet"}
    for store_type, value in rows.items():
        assert 500 < value < 50_000, f"{store_type}: {value} isn't a plausible $/employee"
    assert rows["Standard"] == pytest.approx(3291.83, rel=1e-3)
    assert rows["Express"] == pytest.approx(13082.98, rel=1e-3)
    assert rows["Flagship"] == pytest.approx(1347.94, rel=1e-3)
    assert rows["Outlet"] == pytest.approx(5201.97, rel=1e-3)


def test_revenue_per_sqft_is_plausible(client_as, model_id):
    # Same bug/fix as sales_per_employee, for dim_store.s_floor_space.
    resp = _run(
        client_as, model_id,
        mode="demo", metric="revenue_per_sqft", group_by_json='["dim_store.s_store_type"]',
    )
    assert resp.status_code == 200, resp.text
    rows = dict(resp.json()["rows"])
    assert set(rows) == {"Flagship", "Standard", "Express", "Outlet"}
    for store_type, value in rows.items():
        assert 1 < value < 500, f"{store_type}: {value} isn't a plausible $/sqft"
    assert rows["Flagship"] == pytest.approx(5.26, rel=1e-3)
    assert rows["Outlet"] == pytest.approx(7.22, rel=1e-3)
    assert rows["Express"] == pytest.approx(38.48, rel=1e-3)
    assert rows["Standard"] == pytest.approx(10.27, rel=1e-3)

    overall = _run(client_as, model_id, mode="demo", metric="revenue_per_sqft", group_by_json="[]")
    assert overall.json()["rows"][0][0] == pytest.approx(11.36, rel=1e-3)


def test_sales_per_employee_matches_an_independently_written_query(client_as, model_id):
    # Verifies the emitted SQL itself (not just the API's plausible-range check
    # above) against a from-scratch query that pre-aggregates fct_store_sales to
    # store grain *before* joining dim_store, so s_number_employees is summed once
    # per store regardless of how many sales lines that store has.
    from lexis.retail_demo_data import build_retail_demo_connection

    con = build_retail_demo_connection()
    try:
        independent = con.execute(
            """
            WITH per_store AS (
                SELECT ss_store_sk, SUM(ss_ext_sales_price) AS revenue
                FROM retail.public.fct_store_sales
                GROUP BY ss_store_sk
            )
            SELECT s.s_store_type, SUM(p.revenue) / SUM(s.s_number_employees)
            FROM per_store p JOIN retail.public.dim_store s ON p.ss_store_sk = s.s_store_sk
            GROUP BY s.s_store_type
            """
        ).fetchall()
    finally:
        con.close()

    resp = _run(
        client_as, model_id,
        mode="demo", metric="sales_per_employee", group_by_json='["dim_store.s_store_type"]',
    )
    assert resp.status_code == 200, resp.text
    api_rows = dict(resp.json()["rows"])
    assert api_rows == pytest.approx(dict(independent), rel=1e-9)


def test_sales_per_employee_by_year_sums_to_the_overall_total(client_as, model_id):
    # Regression test for the timeseries path specifically: `emit_metric_query` was
    # fixed first, but `emit_timeseries_query` still fell back to the flat
    # (line-grain) join, reproducing the exact original bug when bucketing by
    # time_grain ($9-$30/employee instead of four figures). Every store here sells
    # in all three years (see lexis.retail_demo_data), so total_employees - the
    # denominator - is the same divisor each year; summing the corrected per-year
    # values must therefore recover the overall (ungrouped) total exactly.
    resp = client_as("viewer").post(
        f"/api/models/{model_id}/run/timeseries",
        data={
            "mode": "demo", "metric": "sales_per_employee",
            "time_dataset": "dim_date", "time_field": "d_date", "grain": "year",
        },
    )
    assert resp.status_code == 200, resp.text
    periods = {row[0][:4]: row[1] for row in resp.json()["rows"]}
    assert set(periods) == {"2022", "2023", "2024"}
    for year, value in periods.items():
        assert not (9 < value < 30), f"{year}: {value} is in the old buggy $9-$30 range"
    assert periods["2022"] == pytest.approx(830, abs=5)
    assert periods["2023"] == pytest.approx(1150, abs=5)
    assert periods["2024"] == pytest.approx(1694, abs=5)
    assert sum(periods.values()) == pytest.approx(3674.22, rel=1e-4)


def test_sales_per_employee_grouped_by_item_category_counts_each_store_once_per_category(client_as, model_id):
    # Regression test: the pre-aggregation subquery used to group by the raw
    # foreign key (ss_item_sk) instead of the resolved i_category attribute, so a
    # store selling many different items in the same category still had its
    # employee count summed once per *item* rather than once per *category* - a
    # milder version of the original bug, for any grouping outside dim_store.
    resp = _run(
        client_as, model_id,
        mode="demo", metric="sales_per_employee", group_by_json='["dim_item.i_category"]',
    )
    assert resp.status_code == 200, resp.text
    rows = dict(resp.json()["rows"])
    assert len(rows) == 10
    for category, value in rows.items():
        assert not (9 < value < 30), f"{category}: {value} is in the old buggy $9-$30 range"
        assert value > 100, f"{category}: {value} isn't a plausible $/employee"
    assert rows["Electronics"] == pytest.approx(517.07, rel=1e-3)


def test_sales_per_employee_grouped_by_customer_loyalty_tier(client_as, model_id):
    resp = _run(
        client_as, model_id,
        mode="demo", metric="sales_per_employee", group_by_json='["dim_customer.c_loyalty_tier"]',
    )
    assert resp.status_code == 200, resp.text
    rows = dict(resp.json()["rows"])
    assert set(rows) == {"Bronze", "Silver", "Gold", "Platinum"}
    for tier, value in rows.items():
        assert not (9 < value < 30), f"{tier}: {value} is in the old buggy $9-$30 range"
    assert rows["Bronze"] == pytest.approx(1683.93, rel=1e-3)


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


def test_query_results_beyond_the_row_cap_set_a_truncated_flag(client_as, model_id, monkeypatch):
    from lexis_api.config import settings

    monkeypatch.setattr(settings, "max_result_rows", 3)

    resp = _run(
        client_as, model_id,
        mode="demo", metric="total_revenue", group_by_json='["dim_item.i_category"]',
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["truncated"] is True
    assert body["row_count"] == 3
    assert len(body["rows"]) == 3


def test_query_results_under_the_row_cap_are_not_flagged_truncated(client_as, model_id):
    resp = _run(
        client_as, model_id,
        mode="demo", metric="total_revenue", group_by_json='["dim_item.i_category"]',
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["truncated"] is False
    assert body["row_count"] == 10


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
