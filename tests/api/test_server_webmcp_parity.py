"""Parity checks between the two agent-facing surfaces this app exposes over the
same models: the Python MCP servers (workspace-wide `/api/mcp` and per-model
`/api/models/{id}/mcp`) and the WebMCP tools registered in the browser
(`useWorkspaceWebMcpTools`/`useModelWebMcpTools`).

WebMCP has no test runner in this repo, but its `execute()` bodies are thin,
direct maps over the exact same REST payload (`GET /api/models/{id}`,
`GET /api/models`) fetched here - see those hooks' source. Asserting the MCP
server's tool output against that REST payload is therefore an accurate proxy
for what WebMCP shows, without needing a browser/JS harness: if a REST field a
WebMCP hook reads verbatim (`time_fields`, `tool_description`, `description`,
`dataset_count`, `metric_count`) matches what the MCP server independently
computes for the same model, the two surfaces agree.
"""

from importlib import resources

import pytest

from lexis.retail_demo_data import export_retail_demo_dataset

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture()
def retail_yaml() -> str:
    return (resources.files("lexis_api.sample_data") / "retail_analytics_model.yaml").read_text()


@pytest.fixture()
def model_id(client_as, retail_yaml) -> int:
    resp = client_as("editor").post("/api/models", json={"yaml_text": retail_yaml})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture()
def connection_id(client_as, tmp_path) -> int:
    demo_path = tmp_path / "retail-demo.duckdb"
    export_retail_demo_dataset(demo_path, overwrite=True)
    resp = client_as("editor").post(
        "/api/connections",
        json={"name": "retail-demo", "type": "duckdb_file", "config": {"path": str(demo_path)}},
    )
    return resp.json()["id"]


def _rpc(client, url: str, payload: dict) -> dict:
    resp = client.post(url, json=payload, headers=MCP_HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _initialize(client, url: str) -> None:
    _rpc(
        client, url,
        {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )


def _call_tool(client, url: str, name: str, arguments: dict) -> dict:
    body = _rpc(client, url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return body["result"]


def _list_tools(client, url: str) -> list[dict]:
    body = _rpc(client, url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    return body["result"]["tools"]


def test_workspace_server_tools_are_all_read_only(client_as, model_id):
    # Point 1: server tools had no annotations at all; WebMCP's four workspace
    # tools already declare readOnlyHint (see useWorkspaceWebMcpTools.ts).
    client = client_as("viewer")
    _initialize(client, "/api/mcp")
    tools = {t["name"]: t for t in _list_tools(client, "/api/mcp")}
    assert set(tools) == {"list_models", "list_connections", "list_metrics", "query_metric"}
    for name, tool in tools.items():
        assert tool.get("annotations", {}).get("readOnlyHint") is True, f"{name} missing readOnlyHint"


def test_per_model_query_metric_tools_are_all_read_only(client_as, model_id, connection_id):
    # Point 1, second half: the per-model server's query_<metric> tools.
    client = client_as("viewer")
    url = f"/api/models/{model_id}/mcp?connection_id={connection_id}"
    _initialize(client, url)
    tools = _list_tools(client, url)
    assert len(tools) == 18  # one per retail_analytics_model.yaml metric
    for tool in tools:
        assert tool.get("annotations", {}).get("readOnlyHint") is True, f"{tool['name']} missing readOnlyHint"


def test_time_fields_agree_between_the_mcp_server_and_the_rest_api(client_as, model_id):
    # Point 2: WebMCP derived time_fields from a local is_time scan (5 dim_date
    # fields), the server from time_axis_refs (1: only d_date has a real Date
    # datatype). Both must now read the same computed value.
    client = client_as("viewer")
    _initialize(client, "/api/mcp")
    server_result = _call_tool(client, "/api/mcp", "list_metrics", {"model_id": model_id})
    server_time_fields = server_result["structuredContent"]["time_fields"]

    rest = client.get(f"/api/models/{model_id}")
    assert rest.status_code == 200, rest.text
    rest_time_fields = rest.json()["time_fields"]  # what timeSeries.ts's timeFields() now reads directly

    assert server_time_fields == rest_time_fields == ["dim_date.d_date"]


def test_metric_descriptions_agree_between_the_mcp_server_and_the_rest_api(client_as, model_id):
    # Point 3: WebMCP showed the bare `description`, dropping ai_context synonyms
    # the server's list_metrics/tool descriptions include (e.g. "Also known as:
    # revenue, gross sales, total sales."). Both must now show the same text -
    # MetricOut.tool_description, which WebMCP's hooks read instead of `description`.
    client = client_as("viewer")
    _initialize(client, "/api/mcp")
    server_result = _call_tool(client, "/api/mcp", "list_metrics", {"model_id": model_id})
    server_metrics = {m["name"]: m["description"] for m in server_result["structuredContent"]["metrics"]}

    rest = client.get(f"/api/models/{model_id}")
    rest_metrics = {m["name"]: m for m in rest.json()["metrics"]}

    assert set(server_metrics) == set(rest_metrics)
    for name, server_description in server_metrics.items():
        assert server_description == rest_metrics[name]["tool_description"]

    # And it's actually the richer, synonym-including text, not just the bare one.
    assert "Also known as: revenue, gross sales, total sales." in server_metrics["total_revenue"]
    assert rest_metrics["total_revenue"]["description"] == "Total extended sales revenue"
    assert rest_metrics["total_revenue"]["tool_description"] != rest_metrics["total_revenue"]["description"]


def test_list_models_union_agrees_between_the_mcp_server_and_the_rest_api(client_as, model_id):
    # Point 4: the server's list_models had description but not the counts;
    # WebMCP's had the counts but not description. Both must return the union now.
    client = client_as("viewer")
    _initialize(client, "/api/mcp")
    server_result = _call_tool(client, "/api/mcp", "list_models", {})
    server_models = {m["id"]: m for m in server_result["structuredContent"]["models"]}
    assert model_id in server_models

    rest = client.get("/api/models")
    assert rest.status_code == 200, rest.text
    rest_models = {m["id"]: m for m in rest.json()}
    assert model_id in rest_models

    server_m, rest_m = server_models[model_id], rest_models[model_id]
    for field in ("name", "description", "dataset_count", "metric_count"):
        assert server_m[field] == rest_m[field], field
