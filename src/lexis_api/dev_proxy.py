"""Dev-only reverse proxy: forwards anything not matching `/api/*` to the Vite dev
server, so this app's own port serves both the API and the UI - lets one tunnel
(ngrok's free tier allows only one) expose the whole app instead of just the API.
Enabled only when `settings.dev_ui_proxy_target` is set (see `config.py`); never
mounted in production, where the built frontend is served by nginx instead
(`docker/nginx.conf`), not by this app.

Proxies plain HTTP requests and Vite's HMR WebSocket - without the latter the dev
server's client-side code just spins retrying a connection that never succeeds
(harmless, but noisy, and defeats live-reload through the tunnel).
"""

from collections.abc import Iterable

import anyio
import httpx
import websockets
from fastapi import FastAPI, Request, Response, WebSocket
from starlette.websockets import WebSocketDisconnect

# Headers that only make sense between one hop and the next - forwarding them
# verbatim across a proxy either breaks the rebuilt response (e.g. a stale
# Content-Length) or leaks proxy-internal details neither side should see.
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}


def _filtered_headers(items: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {k: v for k, v in items if k.lower() not in _HOP_BY_HOP_HEADERS}


def mount_dev_ui_proxy(app: FastAPI, target: str) -> None:
    """Mount the catch-all proxy on `app`, forwarding to `target` (the Vite dev
    server's base URL, e.g. "http://localhost:5173"). Must be mounted last -
    Starlette matches routes in registration order, so every real `/api/...`
    route/mount already on `app` still wins over this catch-all."""
    http_client = httpx.AsyncClient(base_url=target)
    ws_target = target.replace("https://", "wss://").replace("http://", "ws://")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def _proxy_http(path: str, request: Request) -> Response:
        try:
            upstream = await http_client.request(
                request.method,
                f"/{path}",
                params=request.query_params,
                headers=_filtered_headers(request.headers.items()),
                content=await request.body(),
            )
        except httpx.HTTPError as exc:
            # The Vite dev server being slow/unreachable is a normal, recurring
            # condition (cold-compile, not started yet, ...) - a clean 502 with a
            # one-line log entry beats an unhandled exception dumping a full
            # traceback (and, under a client that retries aggressively, doing
            # that every few seconds indefinitely - see git history for why this
            # comment exists).
            return Response(content=f"dev UI proxy: {exc}", status_code=502, media_type="text/plain")
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=_filtered_headers(upstream.headers.items()),
        )

    @app.websocket("/{path:path}")
    async def _proxy_websocket(websocket: WebSocket, path: str) -> None:
        await websocket.accept(subprotocol=websocket.headers.get("sec-websocket-protocol"))
        try:
            # `ping_interval` off: the `websockets` client otherwise pings the
            # upstream every 20s and closes the connection if it doesn't get a
            # timely pong - Vite's HMR socket doesn't necessarily answer that the
            # way this library expects, so left on this silently force-closes the
            # upstream leg every ~20-40s. That drops the browser's HMR socket too,
            # and Vite does a full page reload on every reconnect - the proxy
            # should stay transparent and not impose its own liveness policy on
            # a connection it didn't originate.
            requested_protocol = websocket.headers.get("sec-websocket-protocol")
            async with websockets.connect(
                f"{ws_target}/{path}",
                ping_interval=None,
                # Vite's HMR endpoint checks for the "vite-hmr" subprotocol to
                # recognize the connection as HMR traffic - omitting it (the
                # earlier bug here) leaves Vite never completing its side of the
                # handshake, so this call hangs until `open_timeout` (10s
                # default) fires, silently killing the whole bridge.
                subprotocols=[websockets.Subprotocol(requested_protocol)] if requested_protocol else None,
            ) as upstream:
                async with anyio.create_task_group() as tg:

                    async def from_client() -> None:
                        try:
                            while True:
                                message = await websocket.receive()
                                if message["type"] == "websocket.disconnect":
                                    return
                                if (text := message.get("text")) is not None:
                                    await upstream.send(text)
                                elif (data := message.get("bytes")) is not None:
                                    await upstream.send(data)
                        except WebSocketDisconnect:
                            pass
                        finally:
                            tg.cancel_scope.cancel()

                    async def from_upstream() -> None:
                        try:
                            async for message in upstream:
                                if isinstance(message, bytes):
                                    await websocket.send_bytes(message)
                                else:
                                    await websocket.send_text(message)
                        finally:
                            tg.cancel_scope.cancel()

                    tg.start_soon(from_client)
                    tg.start_soon(from_upstream)
        except Exception:
            # Vite's HMR client reconnects on its own on failure - don't crash the
            # whole proxy over one dropped/never-established dev-tooling socket.
            pass
