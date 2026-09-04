"""End-to-end proof that the mounted MCP endpoint (see `semantica_api/routers/mcp.py`)
actually executes metric queries, not just serves the schema (that part is already
covered by `test_mcp_target` in `test_transpile_routes.py`). Drives the raw MCP
Streamable HTTP JSON-RPC wire protocol directly through `TestClient` - no need for the
`mcp` SDK's own client, since with `json_response=True` each request/response is a
plain JSON body.
"""

import pytest

from semantica.demo_data import export_demo_dataset

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


def _rpc(client, model_id: int, connection_id: int, payload: dict) -> dict:
    resp = client.post(
        f"/api/models/{model_id}/mcp?connection_id={connection_id}",
        json=payload,
        headers=MCP_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _initialize(client, model_id: int, connection_id: int) -> None:
    _rpc(
        client,
        model_id,
        connection_id,
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


def test_tools_list_returns_one_tool_per_metric(client_as, model_id, connection_id):
    client = client_as("viewer")
    _initialize(client, model_id, connection_id)

    body = _rpc(client, model_id, connection_id, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    tool_names = {t["name"] for t in body["result"]["tools"]}
    assert "query_total_sales" in tool_names


def test_tools_call_executes_a_real_query(client_as, model_id, connection_id):
    client = client_as("viewer")
    _initialize(client, model_id, connection_id)

    body = _rpc(
        client,
        model_id,
        connection_id,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "query_total_sales", "arguments": {"group_by": ["item.i_category"]}},
        },
    )

    result = body["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["columns"] == ["i_category", "total_sales"]
    assert result["structuredContent"]["row_count"] == 2


def test_unknown_connection_id_is_404(client_as, model_id):
    client = client_as("viewer")
    resp = client.post(
        f"/api/models/{model_id}/mcp?connection_id=999999",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        headers=MCP_HEADERS,
    )
    assert resp.status_code == 404


def test_missing_connection_id_query_param_is_422(client_as, model_id):
    client = client_as("viewer")
    resp = client.post(
        f"/api/models/{model_id}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers=MCP_HEADERS,
    )
    assert resp.status_code == 422
