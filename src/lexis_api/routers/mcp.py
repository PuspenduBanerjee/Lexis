"""Two live MCP endpoints, both mounted (not normal `APIRouter`s - see `main.py`)
because the MCP Streamable HTTP transport (`StreamableHTTPSessionManager`) is a raw
ASGI app bound to one `Server` instance built fresh per request, so a small Starlette
`Route` with a raw ASGI endpoint is needed instead of FastAPI `Depends`-based routing.
Auth/lookup logic is intentionally re-derived from `deps.py`'s plain (non-`Depends`)
helpers rather than FastAPI's dependency injection, which doesn't apply outside
normal routes.

- `POST/GET/DELETE /api/models/{model_id}/mcp?connection_id=<id>`: one model+connection
  fixed in the URL, one `query_<metric>` tool per metric (`_MCPModelEndpoint`).
- `POST/GET/DELETE /api/mcp`: workspace-wide - model_id/connection_id are supplied per
  tool call instead (`_MCPWorkspaceEndpoint`, see `mcp_workspace.py`), so one client
  connection can query any model+connection without reconnecting to a different URL.

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

from lexis import mcp_server as mcp_server_module
from lexis.parser import parse_ossie_yaml
from lexis.resolved_model import ResolvedModel
from lexis_api.config import settings
from lexis_api.connection_runtime import emitter_for_connection_type, open_connection
from lexis_api.db import SessionLocal
from lexis_api.deps import find_connection_or_404, find_model_or_404, find_user_or_401
from lexis_api.mcp_workspace import build_workspace_server


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
                user_id_raw = request.headers.get("x-account-id")
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

            document = parse_ossie_yaml(record.raw_yaml)
            model = ResolvedModel.build(document.semantic_model[0])
            emitter = emitter_for_connection_type(conn.type)

            def execute(
                metric: str,
                group_by: list[str] | None,
                time_grain: str | None = None,
                time_field: str | None = None,
            ) -> dict:
                referenced = mcp_server_module.query_datasets(
                    model, metric, group_by, time_grain, time_field
                )
                with open_connection(conn, model, referenced) as con:
                    return mcp_server_module.run_metric_or_timeseries(
                        con, emitter, model, metric, group_by, time_grain, time_field
                    )

            server = mcp_server_module.build_server(model, execute, name=model.semantic_model.name)
            session_manager = StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)
            async with session_manager.run():
                await session_manager.handle_request(scope, receive, send)
        finally:
            db.close()


mcp_asgi_app = Starlette(
    routes=[Route("/{model_id}/mcp", _MCPModelEndpoint(), methods=["GET", "POST", "DELETE"])]
)


class _MCPWorkspaceEndpoint:
    """Raw ASGI callable for the workspace-wide MCP endpoint (see module docstring).
    Only auth (`X-Account-Id`) comes from the request - everything else is a tool
    call argument, resolved fresh per call inside `mcp_workspace.build_workspace_server`."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        db = SessionLocal()
        try:
            request = Request(scope, receive)
            try:
                user_id_raw = request.headers.get("x-account-id")
                user_id = int(user_id_raw) if user_id_raw is not None else settings.default_user_id
                find_user_or_401(db, user_id)
            except (TypeError, ValueError) as exc:
                await JSONResponse({"detail": str(exc)}, status_code=422)(scope, receive, send)
                return
            except HTTPException as exc:
                await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
                return

            server = build_workspace_server(db)
            session_manager = StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)
            async with session_manager.run():
                await session_manager.handle_request(scope, receive, send)
        finally:
            db.close()


mcp_workspace_asgi_app = Starlette(
    routes=[Route("/", _MCPWorkspaceEndpoint(), methods=["GET", "POST", "DELETE"])]
)

# `Starlette.Mount`'s path regex always requires a literal "/" after the mount
# prefix to match at all (see `Mount.__init__`: it compiles `path + "/{path:path}"`),
# so a bare `/api/mcp` request (no trailing slash) never actually reaches the
# `mcp_workspace_asgi_app` mount above - normally that just 307-redirects to
# `/api/mcp/` via Starlette's own `redirect_slashes`, but when the dev-only UI
# proxy's catch-all route is also registered (`mount_dev_ui_proxy`, see
# `main.py`/`dev_proxy.py`) that catch-all matches the bare path first and
# swallows it as a proxy request instead, breaking exact-path clients that don't
# follow redirects. `main.py` registers this exact route directly (not via
# `Mount`) so the bare form resolves the same way regardless of proxy state.
mcp_workspace_bare_route = Route("/api/mcp", _MCPWorkspaceEndpoint(), methods=["GET", "POST", "DELETE"])
