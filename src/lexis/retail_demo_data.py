"""A larger, deliberately *diverse* demo dataset: a multi-fact retail star schema
(``fct_store_sales`` + ``fct_store_returns`` sharing conformed dimensions) with
**10,000 generated sales facts**, ~1,500 return facts, and fully populated
dimensions. Companion to :mod:`lexis.demo_data`'s tiny fixed TPC-DS fixture - that
one stays small so emitter/HTTP tests can assert exact aggregates against it; this
one exists to actually *demo* analytics (segmentation, seasonality, basket
analysis, returns, promo lift) against the bundled ``retail_analytics`` model
(``src/lexis_api/sample_data/retail_analytics_model.yaml``).

Everything is generated from a fixed ``random.Random`` seed, so the row set - and
therefore every aggregate computed from it - is fully reproducible; tests freeze
the exact numbers.

Like :mod:`lexis.demo_data`, requires the optional ``duckdb`` dependency and is
imported lazily by its callers (the CLI, ``lexis_api``) rather than by the
``lexis`` package itself.
"""

from __future__ import annotations

import csv
import os
import random
import tempfile
from datetime import date, timedelta
from itertools import accumulate
from pathlib import Path

import duckdb

# Catalog/schema the bundled ``retail_analytics`` model's ``source`` values use;
# ``ATTACH ':memory:' AS retail`` + ``CREATE SCHEMA retail.public`` makes the model's
# ``retail.public.*``-qualified SQL run unmodified (same trick as demo_data.py).
RETAIL_DEMO_CATALOG = "retail"

RETAIL_DEMO_SOURCES = frozenset(
    {
        "retail.public.fct_store_sales",
        "retail.public.fct_store_returns",
        "retail.public.dim_date",
        "retail.public.dim_customer",
        "retail.public.dim_item",
        "retail.public.dim_store",
        "retail.public.dim_promotion",
    }
)

SALES_ROW_COUNT = 10_000
_SEED = 20_240_907
_START_DATE = date(2022, 1, 1)
_END_DATE = date(2024, 12, 31)
_TAX_RATE = 0.08

_FIRST_NAMES = [
    "Ava", "Liam", "Noah", "Emma", "Olivia", "Mia", "Sophia", "Ethan", "Lucas", "Amara",
    "Priya", "Rohan", "Wei", "Ling", "Diego", "Sofía", "Yusuf", "Fatima", "Kenji", "Hana",
    "Isabella", "Mateo", "Chloe", "Elijah", "Nadia", "Omar", "Grace", "Henry", "Zara", "Aiden",
    "Layla", "Caleb", "Naomi", "Ivan", "Marta", "Tariq", "Aisha", "Sven", "Ingrid", "Kofi",
]
_LAST_NAMES = [
    "Nguyen", "Patel", "Kim", "Garcia", "Johnson", "Okafor", "Silva", "Müller", "Rossi", "Haddad",
    "Andersson", "Cohen", "Novak", "Popescu", "Ivanov", "Tanaka", "Chen", "Diallo", "Reyes", "Brown",
    "Fischer", "Kowalski", "Santos", "Baker", "Hoffman", "Petrov", "Wagner", "Meyer", "Costa", "Larsen",
]
_GENDERS = (("Female", 0.48), ("Male", 0.48), ("Nonbinary", 0.04))
_MARITAL = ("Single", "Married", "Divorced", "Widowed", "Domestic Partnership")
_EDUCATION = ("High School", "Some College", "Associate", "Bachelors", "Masters", "Doctorate", "Unknown")
_INCOME_BANDS = ("<30k", "30-60k", "60-90k", "90-120k", "120-160k", "160k+")
_LOYALTY_TIERS = (("Bronze", 0.5), ("Silver", 0.28), ("Gold", 0.16), ("Platinum", 0.06))
_CHANNELS = ("In-Store", "Online", "Mobile App", "Catalog")
_CITIES = [
    ("Seattle", "WA", "USA"), ("Portland", "OR", "USA"), ("San Francisco", "CA", "USA"),
    ("Los Angeles", "CA", "USA"), ("Denver", "CO", "USA"), ("Austin", "TX", "USA"),
    ("Dallas", "TX", "USA"), ("Chicago", "IL", "USA"), ("Minneapolis", "MN", "USA"),
    ("Detroit", "MI", "USA"), ("Atlanta", "GA", "USA"), ("Miami", "FL", "USA"),
    ("Charlotte", "NC", "USA"), ("Boston", "MA", "USA"), ("New York", "NY", "USA"),
    ("Philadelphia", "PA", "USA"), ("Washington", "DC", "USA"), ("Phoenix", "AZ", "USA"),
    ("Toronto", "ON", "Canada"), ("Vancouver", "BC", "Canada"),
]
_DIVISIONS = ("Northeast", "Southeast", "Midwest", "West", "Southwest", "Pacific")

_CATEGORY_CLASSES: dict[str, tuple[str, ...]] = {
    "Electronics": ("Audio", "Computers", "Mobile", "Wearables", "Accessories", "Cameras"),
    "Home & Kitchen": ("Cookware", "Small Appliances", "Storage", "Bedding", "Decor", "Lighting"),
    "Apparel": ("Tops", "Bottoms", "Outerwear", "Footwear", "Activewear", "Accessories"),
    "Sports & Outdoors": ("Camping", "Cycling", "Fitness", "Team Sports", "Water Sports", "Hiking"),
    "Books": ("Fiction", "Nonfiction", "Children", "Reference", "Comics", "Cookbooks"),
    "Beauty": ("Skincare", "Haircare", "Makeup", "Fragrance", "Bath & Body", "Tools"),
    "Toys & Games": ("Building Sets", "Board Games", "Dolls", "Puzzles", "Outdoor Play", "Educational"),
    "Grocery": ("Snacks", "Beverages", "Pantry", "Breakfast", "Frozen", "Confectionery"),
    "Office": ("Paper", "Writing", "Organization", "Furniture", "Technology", "Supplies"),
    "Automotive": ("Interior", "Exterior", "Tools", "Electronics", "Fluids", "Tires"),
}
_CATEGORIES = tuple(_CATEGORY_CLASSES)
_BRANDS = [
    "SoundWave", "Northwind Press", "Peak Forge", "Aurora Labs", "Hearthstone", "TrailForge",
    "LumenTech", "Cobalt & Co", "Willowbrook", "Ridgeline", "Nimbus", "Vantage",
    "Kettle & Co", "BrightLeaf", "Momentum", "Harborview", "Copperfield", "Solstice",
    "Meridian", "Ironwood", "Pinecrest", "Cascade", "Everforge", "Marlowe",
    "Tidewater", "Grainhouse", "Quill & Co", "Alpine Peak", "Verdant", "Sablefish",
    "Larksong", "Foundry 9", "Brightwater", "Sterling Row", "Nova Craft", "Field & Study",
    "Ember", "Halcyon", "Driftwood", "Kestrel",
]
_MANUFACTURERS = [
    "Global Consumer Goods", "Pacific Rim Manufacturing", "Atlas Industries", "Vertex Products",
    "Continental Makers", "Summit Fabrication", "Keystone Supply", "Horizon Works",
    "Union Assembly", "Delta Provisions", "Anchor Holdings", "Beacon Manufacturing",
]
_COLORS = ("Black", "White", "Silver", "Slate", "Navy", "Crimson", "Forest", "Sand", "Charcoal", "Assorted")
_SIZES = ("XS", "S", "M", "L", "XL", "One Size", "N/A")
_UNITS = ("Each", "Pack of 2", "Pack of 4", "Pack of 6", "Dozen", "Case of 24")
_PRODUCT_ADJECTIVES = (
    "Pro", "Everyday", "Deluxe", "Compact", "Ultra", "Classic", "Essential", "Premium", "Lite", "Max",
)
_PRODUCT_NOUNS = (
    "Kit", "Set", "Bundle", "Edition", "Series", "Collection", "Pack", "System", "Model", "Line",
)

_STORE_TYPES = (
    # (name, floor_space range, employee range, weight)
    ("Flagship", (28_000, 55_000), (85, 180), 0.12),
    ("Standard", (14_000, 28_000), (35, 90), 0.48),
    ("Express", (3_500, 9_000), (10, 30), 0.28),
    ("Outlet", (18_000, 40_000), (25, 70), 0.12),
)
_COMPANY_NAME = "Northwind Retail Group"

_PROMO_CHANNELS = ("Email", "TV", "Radio", "Social", "In-Store Display", "Search", "Catalog", "Affiliate")
_PROMO_THEMES = (
    "Spring Refresh", "Summer Blowout", "Back to School", "Fall Finds", "Black Friday",
    "Cyber Monday", "Holiday Cheer", "New Year Reset", "Clearance Event", "Member Exclusive",
    "Weekend Flash", "Loyalty Bonus", "Bundle & Save", "Doorbuster", "Early Access",
)
_RETURN_REASONS = (
    ("Defective / damaged", 0.22),
    ("Wrong size or fit", 0.24),
    ("Changed mind", 0.20),
    ("Not as described", 0.12),
    ("Found better price", 0.09),
    ("Arrived too late", 0.06),
    ("Gift return", 0.07),
)

_PROMO_COUNT = 40
_CUSTOMER_COUNT = 800
_ITEM_COUNT = 300
_STORE_COUNT = 25
_RETURN_FRACTION = 0.15
_FIRST_TICKET_NUMBER = 100_000


def _weighted_choice(rng: random.Random, pairs: tuple[tuple[str, float], ...]) -> str:
    values = [v for v, _ in pairs]
    weights = [w for _, w in pairs]
    return rng.choices(values, weights=weights, k=1)[0]


def _age_band(birth_year: int) -> str:
    age = _END_DATE.year - birth_year
    for cutoff, label in ((25, "Under 25"), (35, "25-34"), (45, "35-44"), (55, "45-54"), (65, "55-64")):
        if age < cutoff:
            return label
    return "65+"


# --- dimension generators -------------------------------------------------------

_FIXED_HOLIDAYS = {
    (1, 1): "New Year's Day",
    (7, 4): "Independence Day",
    (11, 11): "Veterans Day",
    (12, 25): "Christmas Day",
    (12, 31): "New Year's Eve",
}
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _thanksgiving(year: int) -> date:
    """Fourth Thursday of November."""
    d = date(year, 11, 1)
    d += timedelta(days=(3 - d.weekday()) % 7)  # first Thursday
    return d + timedelta(weeks=3)


def gen_dates() -> list[tuple]:
    """One row per calendar day in ``[_START_DATE, _END_DATE]``.

    Columns: ``d_date_sk, d_date, d_year, d_quarter, d_quarter_name, d_month,
    d_month_name, d_day_of_month, d_day_of_week, d_day_name, d_is_weekend, d_week,
    d_holiday_name``.
    """
    rows: list[tuple] = []
    thanksgivings = {_thanksgiving(y): "Thanksgiving Day" for y in range(_START_DATE.year, _END_DATE.year + 1)}
    day = _START_DATE
    while day <= _END_DATE:
        quarter = (day.month - 1) // 3 + 1
        iso_dow = day.isoweekday()  # 1=Mon .. 7=Sun
        holiday = _FIXED_HOLIDAYS.get((day.month, day.day)) or thanksgivings.get(day)
        rows.append(
            (
                day.year * 10_000 + day.month * 100 + day.day,
                day,
                day.year,
                quarter,
                f"{day.year}Q{quarter}",
                day.month,
                _MONTH_NAMES[day.month - 1],
                day.day,
                iso_dow,
                _DAY_NAMES[iso_dow - 1],
                iso_dow >= 6,
                day.isocalendar().week,
                holiday,
            )
        )
        day += timedelta(days=1)
    return rows


def gen_customers(rng: random.Random, date_sks: list[int]) -> list[tuple]:
    """``_CUSTOMER_COUNT`` rows. Columns: ``c_customer_sk, c_customer_id,
    c_first_name, c_last_name, c_email, c_gender, c_marital_status, c_birth_year,
    c_age_band, c_education_status, c_income_band, c_city, c_state, c_country,
    c_loyalty_tier, c_preferred_channel, c_signup_date_sk``."""
    rows: list[tuple] = []
    for sk in range(1, _CUSTOMER_COUNT + 1):
        first = rng.choice(_FIRST_NAMES)
        last = rng.choice(_LAST_NAMES)
        birth_year = rng.randint(1946, 2005)
        city, state, country = rng.choice(_CITIES)
        rows.append(
            (
                sk,
                f"CUST-{sk:06d}",
                first,
                last,
                f"{first}.{last}{sk}@example.com".lower(),
                _weighted_choice(rng, _GENDERS),
                rng.choice(_MARITAL),
                birth_year,
                _age_band(birth_year),
                rng.choice(_EDUCATION),
                rng.choice(_INCOME_BANDS),
                city,
                state,
                country,
                _weighted_choice(rng, _LOYALTY_TIERS),
                rng.choice(_CHANNELS),
                rng.choice(date_sks),
            )
        )
    return rows


def gen_items(rng: random.Random) -> list[tuple]:
    """``_ITEM_COUNT`` rows. Columns: ``i_item_sk, i_item_id, i_product_name,
    i_category, i_class, i_brand, i_manufacturer, i_color, i_size, i_units,
    i_current_price, i_wholesale_cost``."""
    rows: list[tuple] = []
    for sk in range(1, _ITEM_COUNT + 1):
        category = _CATEGORIES[sk % len(_CATEGORIES)]
        item_class = rng.choice(_CATEGORY_CLASSES[category])
        brand = rng.choice(_BRANDS)
        price = round(rng.uniform(4.5, 480.0) * (1.4 if category == "Electronics" else 1.0), 2)
        rows.append(
            (
                sk,
                f"ITEM-{sk:06d}",
                f"{brand} {rng.choice(_PRODUCT_ADJECTIVES)} {item_class} {rng.choice(_PRODUCT_NOUNS)}",
                category,
                item_class,
                brand,
                rng.choice(_MANUFACTURERS),
                rng.choice(_COLORS),
                rng.choice(_SIZES),
                rng.choice(_UNITS),
                price,
                round(price * rng.uniform(0.38, 0.68), 2),
            )
        )
    return rows


def gen_stores(rng: random.Random, date_sks: list[int]) -> list[tuple]:
    """``_STORE_COUNT`` rows. Columns: ``s_store_sk, s_store_id, s_store_name,
    s_store_type, s_number_employees, s_floor_space, s_market_id,
    s_market_manager, s_company_name, s_division_name, s_city, s_state, s_country,
    s_zip, s_open_date_sk``."""
    type_names = [t[0] for t in _STORE_TYPES]
    type_weights = [t[3] for t in _STORE_TYPES]
    by_name = {t[0]: t for t in _STORE_TYPES}
    rows: list[tuple] = []
    for sk in range(1, _STORE_COUNT + 1):
        store_type = rng.choices(type_names, weights=type_weights, k=1)[0]
        _, floor_range, emp_range, _ = by_name[store_type]
        city, state, country = rng.choice(_CITIES)
        manager = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
        rows.append(
            (
                sk,
                f"STORE-{sk:03d}",
                f"{_COMPANY_NAME} - {city} {store_type}",
                store_type,
                rng.randint(*emp_range),
                rng.randint(*floor_range),
                rng.randint(1, 8),
                manager,
                _COMPANY_NAME,
                rng.choice(_DIVISIONS),
                city,
                state,
                country,
                f"{rng.randint(10_000, 99_999):05d}",
                rng.choice(date_sks),
            )
        )
    return rows


def gen_promotions(rng: random.Random, date_sks: list[int]) -> list[tuple]:
    """``_PROMO_COUNT`` rows plus a ``p_promo_sk = 0`` "No Promotion" sentinel that
    non-promoted sales lines point at (keeps the sales->promotion join an inner
    join with no orphan rows). Columns: ``p_promo_sk, p_promo_id, p_promo_name,
    p_channel, p_discount_pct, p_start_date_sk, p_end_date_sk, p_cost``."""
    lo, hi = min(date_sks), max(date_sks)
    rows: list[tuple] = [(0, "PROMO-000000", "No Promotion", "None", 0.0, lo, hi, 0.0)]
    for sk in range(1, _PROMO_COUNT + 1):
        start_sk, end_sk = sorted(rng.sample(date_sks, 2))
        theme = rng.choice(_PROMO_THEMES)
        rows.append(
            (
                sk,
                f"PROMO-{sk:06d}",
                f"{theme} {rng.choice(('Sale', 'Event', 'Deal', 'Special'))}",
                rng.choice(_PROMO_CHANNELS),
                round(rng.uniform(0.05, 0.45), 2),
                start_sk,
                end_sk,
                round(rng.uniform(500.0, 30_000.0), 2),
            )
        )
    return rows


# --- fact generators -----------------------------------------------------------

def _date_sampler_weights(date_rows: list[tuple]) -> list[float]:
    """Skew sales toward recent years, Q4, and weekends - so time-series and
    seasonality demos actually show a shape."""
    year_factor = {2022: 0.7, 2023: 1.0, 2024: 1.4}
    weights: list[float] = []
    for row in date_rows:
        _, _, year, _, _, month, *_rest = row
        is_weekend = row[10]
        w = year_factor.get(year, 1.0)
        if month in (11, 12):
            w *= 1.9
        elif month in (1, 2):
            w *= 0.75
        if is_weekend:
            w *= 1.25
        weights.append(w)
    return weights


def gen_sales(
    rng: random.Random,
    date_rows: list[tuple],
    items: list[tuple],
    customers: list[tuple],
    stores: list[tuple],
    promotions: list[tuple],
) -> list[tuple]:
    """Exactly ``SALES_ROW_COUNT`` rows, grain = one sales line item. 1-6 line
    items share a ``ss_ticket_number`` (a basket). Columns: ``ss_sold_date_sk,
    ss_item_sk, ss_customer_sk, ss_store_sk, ss_promo_sk, ss_ticket_number,
    ss_quantity, ss_wholesale_cost, ss_list_price, ss_sales_price,
    ss_ext_sales_price, ss_ext_discount_amt, ss_ext_wholesale_cost, ss_ext_tax,
    ss_coupon_amt, ss_net_paid, ss_net_profit``."""
    date_sks = [r[0] for r in date_rows]
    cum_weights = list(accumulate(_date_sampler_weights(date_rows)))
    customer_sks = [r[0] for r in customers]
    store_sks = [r[0] for r in stores]
    real_promos = [p for p in promotions if p[0] != 0]  # (sk, ..., discount_pct at idx 4, ...)

    basket_sizes = (1, 2, 3, 4, 5, 6)
    basket_weights = (30, 26, 20, 12, 8, 4)
    qty_choices = (1, 2, 3, 4, 5, 6, 8, 10, 12)
    qty_weights = (46, 22, 13, 7, 4, 3, 2, 2, 1)

    rows: list[tuple] = []
    ticket_number = _FIRST_TICKET_NUMBER
    while len(rows) < SALES_ROW_COUNT:
        ticket_number += 1
        sold_date_sk = rng.choices(date_sks, cum_weights=cum_weights, k=1)[0]
        customer_sk = rng.choice(customer_sks)
        store_sk = rng.choice(store_sks)
        lines = rng.choices(basket_sizes, weights=basket_weights, k=1)[0]
        for _ in range(lines):
            if len(rows) >= SALES_ROW_COUNT:
                break
            item = rng.choice(items)
            list_price = item[10]
            wholesale_cost = item[11]
            quantity = rng.choices(qty_choices, weights=qty_weights, k=1)[0]

            if rng.random() < 0.35:
                promo = rng.choice(real_promos)
                promo_sk, discount_pct = promo[0], promo[4]
            else:
                promo_sk, discount_pct = 0, 0.0

            sales_price = round(list_price * (1.0 - discount_pct), 2)
            ext_sales_price = round(sales_price * quantity, 2)
            ext_discount_amt = round((list_price - sales_price) * quantity, 2)
            ext_wholesale_cost = round(wholesale_cost * quantity, 2)
            ext_tax = round(ext_sales_price * _TAX_RATE, 2)
            coupon_amt = round(rng.uniform(1.0, 15.0), 2) if rng.random() < 0.12 else 0.0
            net_paid = round(ext_sales_price - coupon_amt, 2)
            net_profit = round(net_paid - ext_wholesale_cost, 2)

            rows.append(
                (
                    sold_date_sk,
                    item[0],
                    customer_sk,
                    store_sk,
                    promo_sk,
                    ticket_number,
                    quantity,
                    wholesale_cost,
                    list_price,
                    sales_price,
                    ext_sales_price,
                    ext_discount_amt,
                    ext_wholesale_cost,
                    ext_tax,
                    coupon_amt,
                    net_paid,
                    net_profit,
                )
            )
    return rows


def gen_returns(rng: random.Random, sales: list[tuple], date_rows: list[tuple]) -> list[tuple]:
    """A ``_RETURN_FRACTION`` sample of sales lines come back, 0-30 days later.
    Columns: ``sr_returned_date_sk, sr_item_sk, sr_customer_sk, sr_store_sk,
    sr_ticket_number, sr_return_quantity, sr_return_amt, sr_return_tax,
    sr_return_fee, sr_net_loss, sr_reason``."""
    sk_by_ordinal = [r[0] for r in date_rows]  # date_sks in calendar order
    ordinal_by_sk = {sk: i for i, sk in enumerate(sk_by_ordinal)}
    sample_size = int(len(sales) * _RETURN_FRACTION)
    returned_lines = rng.sample(sales, sample_size)

    rows: list[tuple] = []
    for line in returned_lines:
        (
            sold_date_sk, item_sk, customer_sk, store_sk, _promo_sk, ticket_number,
            quantity, _wholesale, _list_price, sales_price, ext_sales_price, *_rest,
        ) = line
        start = ordinal_by_sk[sold_date_sk]
        returned_ordinal = min(start + rng.randint(1, 30), len(sk_by_ordinal) - 1)
        return_quantity = rng.randint(1, quantity)
        return_amt = round(sales_price * return_quantity, 2)
        return_tax = round(return_amt * _TAX_RATE, 2)
        return_fee = round(rng.uniform(2.0, 9.0), 2) if rng.random() < 0.3 else 0.0
        net_loss = round(return_fee + return_amt * 0.08, 2)
        rows.append(
            (
                sk_by_ordinal[returned_ordinal],
                item_sk,
                customer_sk,
                store_sk,
                ticket_number,
                return_quantity,
                return_amt,
                return_tax,
                return_fee,
                net_loss,
                _weighted_choice(rng, _RETURN_REASONS),
            )
        )
    return rows


# --- assembly ------------------------------------------------------------------

_DDL = {
    "dim_date": (
        "d_date_sk INT, d_date DATE, d_year INT, d_quarter INT, d_quarter_name VARCHAR, "
        "d_month INT, d_month_name VARCHAR, d_day_of_month INT, d_day_of_week INT, "
        "d_day_name VARCHAR, d_is_weekend BOOLEAN, d_week INT, d_holiday_name VARCHAR"
    ),
    "dim_customer": (
        "c_customer_sk INT, c_customer_id VARCHAR, c_first_name VARCHAR, c_last_name VARCHAR, "
        "c_email VARCHAR, c_gender VARCHAR, c_marital_status VARCHAR, c_birth_year INT, "
        "c_age_band VARCHAR, c_education_status VARCHAR, c_income_band VARCHAR, c_city VARCHAR, "
        "c_state VARCHAR, c_country VARCHAR, c_loyalty_tier VARCHAR, c_preferred_channel VARCHAR, "
        "c_signup_date_sk INT"
    ),
    "dim_item": (
        "i_item_sk INT, i_item_id VARCHAR, i_product_name VARCHAR, i_category VARCHAR, "
        "i_class VARCHAR, i_brand VARCHAR, i_manufacturer VARCHAR, i_color VARCHAR, "
        "i_size VARCHAR, i_units VARCHAR, i_current_price DOUBLE, i_wholesale_cost DOUBLE"
    ),
    "dim_store": (
        "s_store_sk INT, s_store_id VARCHAR, s_store_name VARCHAR, s_store_type VARCHAR, "
        "s_number_employees INT, s_floor_space INT, s_market_id INT, s_market_manager VARCHAR, "
        "s_company_name VARCHAR, s_division_name VARCHAR, s_city VARCHAR, s_state VARCHAR, "
        "s_country VARCHAR, s_zip VARCHAR, s_open_date_sk INT"
    ),
    "dim_promotion": (
        "p_promo_sk INT, p_promo_id VARCHAR, p_promo_name VARCHAR, p_channel VARCHAR, "
        "p_discount_pct DOUBLE, p_start_date_sk INT, p_end_date_sk INT, p_cost DOUBLE"
    ),
    "fct_store_sales": (
        "ss_sold_date_sk INT, ss_item_sk INT, ss_customer_sk INT, ss_store_sk INT, "
        "ss_promo_sk INT, ss_ticket_number BIGINT, ss_quantity INT, ss_wholesale_cost DOUBLE, "
        "ss_list_price DOUBLE, ss_sales_price DOUBLE, ss_ext_sales_price DOUBLE, "
        "ss_ext_discount_amt DOUBLE, ss_ext_wholesale_cost DOUBLE, ss_ext_tax DOUBLE, "
        "ss_coupon_amt DOUBLE, ss_net_paid DOUBLE, ss_net_profit DOUBLE"
    ),
    "fct_store_returns": (
        "sr_returned_date_sk INT, sr_item_sk INT, sr_customer_sk INT, sr_store_sk INT, "
        "sr_ticket_number BIGINT, sr_return_quantity INT, sr_return_amt DOUBLE, "
        "sr_return_tax DOUBLE, sr_return_fee DOUBLE, sr_net_loss DOUBLE, sr_reason VARCHAR"
    ),
}


def generate_retail_demo_tables(seed: int = _SEED) -> dict[str, list[tuple]]:
    """All seven tables as ``{table_name: rows}``, fully deterministic for a given
    ``seed`` - separated from the DuckDB wiring so it's unit-testable without a
    connection."""
    rng = random.Random(seed)
    dates = gen_dates()
    date_sks = [r[0] for r in dates]
    customers = gen_customers(rng, date_sks)
    items = gen_items(rng)
    stores = gen_stores(rng, date_sks)
    promotions = gen_promotions(rng, date_sks)
    sales = gen_sales(rng, dates, items, customers, stores, promotions)
    returns = gen_returns(rng, sales, dates)
    return {
        "dim_date": dates,
        "dim_customer": customers,
        "dim_item": items,
        "dim_store": stores,
        "dim_promotion": promotions,
        "fct_store_sales": sales,
        "fct_store_returns": returns,
    }


def _csv_cell(value: object) -> object:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, date):
        return value.isoformat()
    return value


def _bulk_load(con: duckdb.DuckDBPyConnection, table: str, rows: list[tuple]) -> None:
    """Load ``rows`` via a temp-file ``COPY ... FROM`` - DuckDB's ``executemany``
    is pathologically slow for tens of thousands of rows, and a single giant
    multi-row ``VALUES`` isn't much better; a CSV bulk load is ~200x faster and
    needs no pandas/pyarrow. The CSV is written with the DuckDB defaults an empty
    field means SQL NULL, ``true``/``false`` for booleans, ISO dates."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerows([_csv_cell(v) for v in row] for row in rows)
        con.execute(
            f"COPY {table} FROM '{path}' (FORMAT csv, HEADER false, NULLSTR '')"
        )
    finally:
        os.unlink(path)


def build_retail_demo_connection(target: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """Attach ``target`` under catalog ``retail`` and populate ``retail.public.*``
    with the generated dataset, so the bundled ``retail_analytics`` model's SQL
    runs against it unmodified. For a file ``target``, closing the returned
    connection leaves the data on disk (see :func:`export_retail_demo_dataset`)."""
    tables = generate_retail_demo_tables()
    con = duckdb.connect()
    con.execute(f"ATTACH '{target}' AS {RETAIL_DEMO_CATALOG}")
    con.execute(f"CREATE SCHEMA {RETAIL_DEMO_CATALOG}.public")
    for name, columns in _DDL.items():
        con.execute(f"CREATE TABLE {RETAIL_DEMO_CATALOG}.public.{name} ({columns})")
        _bulk_load(con, f"{RETAIL_DEMO_CATALOG}.public.{name}", tables[name])
    return con


def export_retail_demo_dataset(path: str | Path, *, overwrite: bool = False) -> None:
    """Write the retail demo dataset to a real ``.duckdb`` file - the same schema
    and rows :func:`build_retail_demo_connection` builds in-memory, so the file can
    be re-uploaded or registered as a ``duckdb_file`` connection and produce
    identical results. Mirrors :func:`lexis.demo_data.export_demo_dataset`."""
    path = Path(path)
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"{path} already exists")
        path.unlink()
    build_retail_demo_connection(target=str(path)).close()
