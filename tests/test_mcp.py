import json

from lexis.transpilers.mcp import (
    build_metric_tool_specs,
    build_mcp_tool_manifest,
    resolve_time_axis,
    time_axis_refs,
)


def test_one_tool_per_metric(tpcds_model):
    manifest = build_mcp_tool_manifest(tpcds_model)
    tool_names = {t["name"] for t in manifest["tools"]}
    assert tool_names == {
        "query_total_sales",
        "query_total_profit",
        "query_customer_lifetime_value",
        "query_sales_by_brand",
        "query_store_productivity",
    }


def test_description_includes_ai_context_synonyms(tpcds_model):
    manifest = build_mcp_tool_manifest(tpcds_model)
    total_sales = next(t for t in manifest["tools"] if t["name"] == "query_total_sales")
    assert "total revenue" in total_sales["description"]
    assert "gross sales" in total_sales["description"]


def test_group_by_enum_only_contains_real_dataset_field_refs(tpcds_model):
    manifest = build_mcp_tool_manifest(tpcds_model)
    tool = manifest["tools"][0]
    enum = tool["inputSchema"]["properties"]["group_by"]["items"]["enum"]
    assert "item.i_category" in enum
    assert "store_sales.ss_ext_sales_price" in enum
    assert "not_a_real.field" not in enum


def test_manifest_is_json_serializable(tpcds_model):
    manifest = build_mcp_tool_manifest(tpcds_model)
    json.dumps(manifest)  # should not raise


def test_time_axis_refs_prefers_the_date_typed_field(tpcds_model):
    # date_dim has d_date (datatype: Date) plus d_year/d_quarter_name/d_month_name
    # (is_time but not dates) - only the real date is a DATE_TRUNC axis.
    assert time_axis_refs(tpcds_model) == ["date_dim.d_date"]


def test_resolve_time_axis_defaults_to_the_sole_date_field(tpcds_model):
    assert resolve_time_axis(tpcds_model, None) == ("date_dim", "d_date")
    assert resolve_time_axis(tpcds_model, "date_dim.d_date") == ("date_dim", "d_date")


def test_tool_schema_adds_time_grain_and_field(tpcds_model):
    spec = next(s for s in build_metric_tool_specs(tpcds_model) if s["name"] == "query_total_sales")
    props = spec["inputSchema"]["properties"]
    assert props["time_grain"]["enum"] == ["day", "week", "month", "quarter", "year"]
    assert props["time_field"]["enum"] == ["date_dim.d_date"]
    assert "Monday" in props["time_grain"]["description"]
