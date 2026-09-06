import yaml

from lexis.transpilers.cube import emit_cube_yaml


def test_emits_well_formed_cube_schema(tpcds_model):
    text = emit_cube_yaml(tpcds_model)
    parsed = yaml.safe_load(text)

    assert "cubes" in parsed
    cube_names = {c["name"] for c in parsed["cubes"]}
    assert cube_names == {"store_sales", "date_dim", "customer", "item", "store"}
    for cube in parsed["cubes"]:
        assert {"name", "sql_table", "dimensions", "measures"} <= set(cube)


def test_simple_aggregate_metric_becomes_typed_measure(tpcds_model):
    parsed = yaml.safe_load(emit_cube_yaml(tpcds_model))
    store_sales = next(c for c in parsed["cubes"] if c["name"] == "store_sales")
    total_sales = next(m for m in store_sales["measures"] if m["name"] == "total_sales")
    assert total_sales["type"] == "sum"
    assert total_sales["sql"] == "ss_ext_sales_price"


def test_cross_dataset_metric_becomes_number_measure_with_raw_sql(tpcds_model):
    parsed = yaml.safe_load(emit_cube_yaml(tpcds_model))
    store_sales = next(c for c in parsed["cubes"] if c["name"] == "store_sales")
    clv = next(m for m in store_sales["measures"] if m["name"] == "customer_lifetime_value")
    assert clv["type"] == "number"
    assert "customer.c_customer_sk" in clv["sql"]


def test_joins_reflect_relationships_from_this_dataset(tpcds_model):
    parsed = yaml.safe_load(emit_cube_yaml(tpcds_model))
    store_sales = next(c for c in parsed["cubes"] if c["name"] == "store_sales")
    join_targets = {j["name"] for j in store_sales["joins"]}
    assert join_targets == {"date_dim", "customer", "item", "store"}
    assert all(j["relationship"] == "many_to_one" for j in store_sales["joins"])
