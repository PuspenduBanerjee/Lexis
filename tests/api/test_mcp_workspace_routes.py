"""End-to-end proof of the workspace-wide MCP endpoint (`POST /api/mcp`, see
`lexis_api/mcp_workspace.py`): model_id/connection_id are tool-call arguments here,
not baked into the URL like `/api/models/{model_id}/mcp?connection_id=<id>`
(covered by test_mcp_routes.py) - one connection can query any model+connection
the caller can see. Drives the raw MCP Streamable HTTP JSON-RPC wire protocol
directly through `TestClient`, same convention as test_mcp_routes.py.
"""

import pytest

from lexis.demo_data import export_demo_dataset

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture()
def model_id(client_as, tpcds_yaml) -> int:
    resp = client_as("editor").post("/api/models", json={"yaml_text": tpcds_yaml})
    return resp.json()["id"]


@pytest.fixture()
def connection_id(client_as, tmp_path) -> int:
    demo_path = tmp_path / "demo.duckdb"
    export_demo_dataset(demo_path, overwrite=True)
    resp = client_as("editor").post(
        "/api/connections",
        json={"name": "demo", "type": "duckdb_file", "config": {"path": str(demo_path)}},
    )
    return resp.json()["id"]


def _rpc(client, payload: dict) -> dict:
    resp = client.post("/api/mcp", json=payload, headers=MCP_HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _initialize(client) -> None:
    _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )


def _call_tool(client, name: str, arguments: dict, id_: int = 2) -> dict:
    body = _rpc(client, {"jsonrpc": "2.0", "id": id_, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return body["result"]


def test_tools_list_has_the_four_generic_tools(client_as, model_id, connection_id):
    client = client_as("viewer")
    _initialize(client)

    body = _rpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tool_names = {t["name"] for t in body["result"]["tools"]}
    assert tool_names == {"list_models", "list_connections", "list_metrics", "query_metric"}


def test_list_models_includes_the_created_model(client_as, model_id, connection_id):
    client = client_as("viewer")
    _initialize(client)

    result = _call_tool(client, "list_models", {})
    ids = {m["id"] for m in result["structuredContent"]["models"]}
    assert model_id in ids


def test_list_connections_includes_the_created_connection(client_as, model_id, connection_id):
    client = client_as("viewer")
    _initialize(client)

    result = _call_tool(client, "list_connections", {})
    ids = {c["id"] for c in result["structuredContent"]["connections"]}
    assert connection_id in ids


def test_list_metrics_returns_names_descriptions_and_group_by_refs(client_as, model_id, connection_id):
    client = client_as("viewer")
    _initialize(client)

    result = _call_tool(client, "list_metrics", {"model_id": model_id})
    metrics = {m["name"]: m for m in result["structuredContent"]["metrics"]}
    assert "total_sales" in metrics
    assert "item.i_category" in metrics["total_sales"]["group_by"]
    assert metrics["total_sales"]["description"]


def test_query_metric_executes_a_real_query(client_as, model_id, connection_id):
    client = client_as("viewer")
    _initialize(client)

    result = _call_tool(
        client,
        "query_metric",
        {"model_id": model_id, "metric": "total_sales", "connection_id": connection_id, "group_by": ["item.i_category"]},
    )
    assert result["isError"] is False
    assert result["structuredContent"]["columns"] == ["i_category", "total_sales"]
    assert result["structuredContent"]["row_count"] == 2


def test_query_metric_unknown_model_is_a_clean_tool_error(client_as, model_id, connection_id):
    client = client_as("viewer")
    _initialize(client)

    result = _call_tool(
        client, "query_metric", {"model_id": 999999, "metric": "total_sales", "connection_id": connection_id}
    )
    assert result["isError"] is True


def test_query_metric_unknown_metric_is_a_clean_tool_error(client_as, model_id, connection_id):
    client = client_as("viewer")
    _initialize(client)

    result = _call_tool(
        client, "query_metric", {"model_id": model_id, "metric": "does_not_exist", "connection_id": connection_id}
    )
    assert result["isError"] is True


def test_query_metric_unknown_connection_is_a_clean_tool_error(client_as, model_id):
    client = client_as("viewer")
    _initialize(client)

    result = _call_tool(
        client, "query_metric", {"model_id": model_id, "metric": "total_sales", "connection_id": 999999}
    )
    assert result["isError"] is True
