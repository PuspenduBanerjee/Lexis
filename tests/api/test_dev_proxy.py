"""The dev-only UI proxy (`lexis_api/dev_proxy.py`) must stay off unless explicitly
enabled - it's a catch-all route, so an accidental activation could shadow real
`/api/...` routes. Doesn't exercise the actual HTTP/WebSocket forwarding itself
(that needs a real upstream server to proxy to - verified manually instead, since
this is a local dev convenience rather than a production code path)."""

from starlette.routing import Route

from lexis_api.config import settings
from lexis_api.main import app


def test_dev_ui_proxy_is_off_by_default():
    assert settings.dev_ui_proxy_target is None


def test_no_catch_all_route_is_mounted_by_default():
    # A catch-all `/{path:path}` route would appear as a plain `Route` (not a
    # `Mount`) whose path matches everything - assert none exists so a future
    # change can't accidentally leave the dev proxy mounted unconditionally.
    catch_all_paths = {r.path for r in app.routes if isinstance(r, Route) and r.path == "/{path:path}"}
    assert catch_all_paths == set()


def test_real_api_route_is_unaffected():
    from fastapi.testclient import TestClient

    resp = TestClient(app).get("/api/users/me", headers={"X-Account-Id": "1"})
    assert resp.status_code == 200
