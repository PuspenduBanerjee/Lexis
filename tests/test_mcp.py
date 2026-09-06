import json

from lexis.transpilers.mcp import build_mcp_tool_manifest


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
