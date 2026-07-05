"""Live MCP endpoint: `POST/GET/DELETE /api/models/{model_id}/mcp?connection_id=<id>`.

Mounted (not a normal `APIRouter`, see `main.py`) because the MCP Streamable HTTP
transport (`StreamableHTTPSessionManager`) is a raw ASGI app bound to one `Server`
instance, and that `Server` differs per `(model_id, connection_id)` pair - so instead
of FastAPI `Depends`-based routing, a small Starlette `Route` with a raw ASGI endpoint
resolves `model_id` from the path (Starlette still populates `scope["path_params"]`
for class-based/raw-ASGI endpoints, not just `request -> response` ones), builds a
fresh `Server` + session manager scoped to that request, and drives the transport
directly. Auth/lookup logic is intentionally re-derived from `deps.py`'s plain
(non-`Depends`) helpers rather than FastAPI's dependency injection, which doesn't
apply outside normal routes.

Each MCP tool call opens (and closes) its own connection via the existing
`connection_runtime.open_connection` - same fresh-per-query cost model the `/run`
endpoint already has (see `duckdb_run.py`), just triggered by a tool call instead of
a form post.
"""

from fastapi import HTTPException
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from semantica import mcp_server as mcp_server_module
from semantica._vendor.osi import OSIDialect
from semantica.parser import parse_osi_yaml
from semantica.resolved_model import ResolvedModel
from semantica_api.config import settings
from semantica_api.connection_runtime import emitter_for_connection_type, open_connection
from semantica_api.db import SessionLocal
from semantica_api.deps import find_connection_or_404, find_model_or_404, find_user_or_401
from semantica_api.query_runtime import run_metric_query as run_metric_query_generic


class _MCPModelEndpoint:
    """Raw ASGI callable (not a `request -> response` function) so Starlette hands us
    `scope`/`receive`/`send` directly, which `StreamableHTTPSessionManager` needs."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        db = SessionLocal()
        try:
            try:
                model_id = int(scope["path_params"]["model_id"])
                connection_id_raw = request.query_params.get("connection_id")
                if connection_id_raw is None:
                    raise ValueError("connection_id query parameter is required")
                connection_id = int(connection_id_raw)
                user_id_raw = request.headers.get("x-user-id")
                user_id = int(user_id_raw) if user_id_raw is not None else settings.default_user_id

                find_user_or_401(db, user_id)
                record = find_model_or_404(db, model_id)
                conn = find_connection_or_404(db, connection_id)
            except (KeyError, TypeError, ValueError) as exc:
                await JSONResponse({"detail": str(exc)}, status_code=422)(scope, receive, send)
                return
            except HTTPException as exc:
                await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
                return

            document = parse_osi_yaml(record.raw_yaml)
            model = ResolvedModel.build(document.semantic_model[0])
            emitter = emitter_for_connection_type(conn.type)

            def execute(metric: str, group_by: list[str] | None) -> dict:
                metric_obj = model.metrics[metric]
                metric_expr = model.resolve_expression(metric_obj.expression, OSIDialect.ANSI_SQL)
                referenced = set(model.referenced_datasets(metric_expr))
                referenced |= {ref.split(".", 1)[0] for ref in (group_by or [])}
                with open_connection(conn, model, referenced) as con:
                    return run_metric_query_generic(con, emitter, model, metric, group_by)

            server = mcp_server_module.build_server(model, execute, name=model.semantic_model.name)
            session_manager = StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)
            async with session_manager.run():
                await session_manager.handle_request(scope, receive, send)
        finally:
            db.close()


mcp_asgi_app = Starlette(
    routes=[Route("/{model_id}/mcp", _MCPModelEndpoint(), methods=["GET", "POST", "DELETE"])]
)
