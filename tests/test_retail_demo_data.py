"""The generated retail demo dataset (`lexis.retail_demo_data`): shape, referential
integrity, determinism, and that the assembled DuckDB connection is queryable."""

import duckdb
import pytest

from lexis.retail_demo_data import (
    RETAIL_DEMO_SOURCES,
    SALES_ROW_COUNT,
    build_retail_demo_connection,
    export_retail_demo_dataset,
    gen_customers,
    gen_dates,
    gen_items,
    gen_promotions,
    gen_returns,
    gen_sales,
    gen_stores,
    generate_retail_demo_tables,
)


@pytest.fixture(scope="module")
def tables() -> dict[str, list[tuple]]:
    return generate_retail_demo_tables()


def test_row_counts(tables):
    assert len(tables["fct_store_sales"]) == SALES_ROW_COUNT == 10_000
    assert len(tables["dim_date"]) == 1096  # 2022-01-01 .. 2024-12-31 inclusive
    assert len(tables["dim_customer"]) == 800
    assert len(tables["dim_item"]) == 300
    assert len(tables["dim_store"]) == 25
    assert len(tables["dim_promotion"]) == 41  # 40 + the "No Promotion" sentinel
    assert len(tables["fct_store_returns"]) == 1500  # 15% of sales lines


def test_generation_is_deterministic():
    assert generate_retail_demo_tables() == generate_retail_demo_tables()


def test_different_seed_changes_the_data(tables):
    assert generate_retail_demo_tables(seed=1) != tables


def test_sales_facts_reference_valid_dimension_keys(tables):
    date_sks = {r[0] for r in tables["dim_date"]}
    item_sks = {r[0] for r in tables["dim_item"]}
    customer_sks = {r[0] for r in tables["dim_customer"]}
    store_sks = {r[0] for r in tables["dim_store"]}
    promo_sks = {r[0] for r in tables["dim_promotion"]}

    for date_sk, item_sk, customer_sk, store_sk, promo_sk, *_ in tables["fct_store_sales"]:
        assert date_sk in date_sks
        assert item_sk in item_sks
        assert customer_sk in customer_sks
        assert store_sk in store_sks
        assert promo_sk in promo_sks


def test_return_facts_reference_valid_dimension_keys(tables):
    date_sks = {r[0] for r in tables["dim_date"]}
    item_sks = {r[0] for r in tables["dim_item"]}
    customer_sks = {r[0] for r in tables["dim_customer"]}
    store_sks = {r[0] for r in tables["dim_store"]}

    for date_sk, item_sk, customer_sk, store_sk, *_ in tables["fct_store_returns"]:
        assert date_sk in date_sks
        assert item_sk in item_sks
        assert customer_sk in customer_sks
        assert store_sk in store_sks


def test_data_is_diverse(tables):
    categories = {r[3] for r in tables["dim_item"]}
    assert len(categories) == 10
    loyalty_tiers = {r[14] for r in tables["dim_customer"]}
    assert loyalty_tiers == {"Bronze", "Silver", "Gold", "Platinum"}
    store_types = {r[3] for r in tables["dim_store"]}
    assert len(store_types) >= 3
    sold_years = {sk // 10_000 for sk, *_ in tables["fct_store_sales"]}
    assert sold_years == {2022, 2023, 2024}


def test_promotion_sentinel_is_present(tables):
    sentinel = [p for p in tables["dim_promotion"] if p[0] == 0]
    assert len(sentinel) == 1
    assert sentinel[0][2] == "No Promotion"


def test_returns_never_exceed_the_sold_quantity(tables):
    by_line = {}
    for row in tables["fct_store_sales"]:
        by_line.setdefault((row[5], row[1]), []).append(row[6])  # (ticket, item) -> quantities
    for ret in tables["fct_store_returns"]:
        ticket, item, qty = ret[4], ret[1], ret[5]
        assert qty >= 1
        assert qty <= max(by_line[(ticket, item)])


def test_helpers_run_standalone():
    import random

    rng = random.Random(0)
    dates = gen_dates()
    date_sks = [r[0] for r in dates]
    assert gen_customers(rng, date_sks)
    assert gen_items(rng)
    assert gen_stores(rng, date_sks)
    promos = gen_promotions(rng, date_sks)
    assert promos[0][0] == 0
    sales = gen_sales(rng, dates, gen_items(rng), gen_customers(rng, date_sks), gen_stores(rng, date_sks), promos)
    assert len(sales) == SALES_ROW_COUNT
    assert gen_returns(rng, sales, dates)


def test_build_connection_is_queryable():
    con = build_retail_demo_connection()
    try:
        (count,) = con.execute("SELECT COUNT(*) FROM retail.public.fct_store_sales").fetchone()
        assert count == 10_000
        # a join across three tables resolves
        rows = con.execute(
            "SELECT i.i_category, SUM(ss.ss_ext_sales_price) "
            "FROM retail.public.fct_store_sales ss "
            "JOIN retail.public.dim_item i ON ss.ss_item_sk = i.i_item_sk "
            "GROUP BY 1"
        ).fetchall()
        assert len(rows) == 10
    finally:
        con.close()


def test_sources_match_the_created_tables():
    con = build_retail_demo_connection()
    try:
        tables = {
            f"retail.public.{name}"
            for (name,) in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ).fetchall()
        }
    finally:
        con.close()
    assert tables == set(RETAIL_DEMO_SOURCES)


def test_export_round_trips(tmp_path):
    path = tmp_path / "retail.duckdb"
    export_retail_demo_dataset(path)
    assert path.exists()

    con = duckdb.connect(str(path), read_only=True)
    try:
        (count,) = con.execute("SELECT COUNT(*) FROM public.fct_store_sales").fetchone()
    finally:
        con.close()
    assert count == 10_000


def test_export_refuses_to_overwrite_without_flag(tmp_path):
    path = tmp_path / "retail.duckdb"
    path.write_bytes(b"not a duckdb file")
    with pytest.raises(FileExistsError):
        export_retail_demo_dataset(path)
    export_retail_demo_dataset(path, overwrite=True)  # succeeds with the flag
