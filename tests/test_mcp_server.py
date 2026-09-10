import asyncio

import pytest
from mcp import types

from lexis.mcp_server import build_server


def _list_tools(server):
    return asyncio.run(server.request_handlers[types.ListToolsRequest](None))


def _call_tool(server, name: str, arguments: dict):
    req = types.CallToolRequest(params=types.CallToolRequestParams(name=name, arguments=arguments))
    return asyncio.run(server.request_handlers[types.CallToolRequest](req))


@pytest.fixture()
def recording_execute():
    calls = []

    def execute(
        metric: str,
        group_by: list[str] | None,
        time_grain: str | None = None,
        time_field: str | None = None,
    ) -> dict:
        calls.append((metric, group_by, time_grain, time_field))
        return {"columns": ["x"], "rows": [[1]], "row_count": 1, "sql": "SELECT 1"}

    execute.calls = calls
    return execute


def test_one_tool_per_metric(tpcds_model, recording_execute):
    server = build_server(tpcds_model, recording_execute)
    result = _list_tools(server)
    tool_names = {t.name for t in result.root.tools}
    assert tool_names == {
        "query_total_sales",
        "query_total_profit",
        "query_customer_lifetime_value",
        "query_sales_by_brand",
        "query_store_productivity",
    }


def test_call_tool_dispatches_to_execute_with_metric_and_group_by(tpcds_model, recording_execute):
    server = build_server(tpcds_model, recording_execute)
    result = _call_tool(server, "query_total_sales", {"group_by": ["item.i_category"]})

    assert recording_execute.calls == [("total_sales", ["item.i_category"], None, None)]
    assert result.root.isError is False
    assert result.root.structuredContent == {
        "columns": ["x"],
        "rows": [[1]],
        "row_count": 1,
        "sql": "SELECT 1",
    }


def test_call_tool_without_group_by_passes_none(tpcds_model, recording_execute):
    server = build_server(tpcds_model, recording_execute)
    _call_tool(server, "query_total_sales", {})
    assert recording_execute.calls == [("total_sales", None, None, None)]


def test_call_tool_passes_time_grain_and_field_through(tpcds_model, recording_execute):
    server = build_server(tpcds_model, recording_execute)
    _call_tool(server, "query_total_sales", {"time_grain": "week", "time_field": "date_dim.d_date"})
    assert recording_execute.calls == [("total_sales", None, "week", "date_dim.d_date")]


def test_tool_schema_exposes_time_grain_when_model_has_a_date_field(tpcds_model, recording_execute):
    server = build_server(tpcds_model, recording_execute)
    tools = {t.name: t for t in _list_tools(server).root.tools}
    props = tools["query_total_sales"].inputSchema["properties"]
    assert props["time_grain"]["enum"] == ["day", "week", "month", "quarter", "year"]
    assert props["time_field"]["enum"] == ["date_dim.d_date"]


def test_call_unknown_tool_is_an_error_result(tpcds_model, recording_execute):
    server = build_server(tpcds_model, recording_execute)
    result = _call_tool(server, "query_not_a_real_metric", {})
    assert result.root.isError is True
    assert recording_execute.calls == []
