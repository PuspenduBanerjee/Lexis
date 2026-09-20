"""Single-image frontend serving (`lexis_api/static.py`). Off unless
`frontend_dist_dir` is set; when on, it serves the built SPA from `/` with a
deep-link fallback to `index.html`, without shadowing `/api/...` routes.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lexis_api.config import settings
from lexis_api.main import app
from lexis_api.static import mount_spa


def test_frontend_serving_is_off_by_default():
    assert settings.frontend_dist_dir is None
    # No mount at "/" on the real app (the API routes are all under /api).
    assert not any(getattr(r, "path", None) == "" for r in app.routes if r.__class__.__name__ == "Mount")


@pytest.fixture()
def dist(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Lexis</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "privacy").mkdir()
    (tmp_path / "privacy" / "index.html").write_text("<!doctype html><title>Privacy</title>")
    return tmp_path


def test_mount_spa_rejects_a_dir_without_index_html(tmp_path):
    with pytest.raises(RuntimeError):
        mount_spa(FastAPI(), str(tmp_path))


def test_serves_index_asset_and_deep_link_fallback(dist):
    spa = FastAPI()

    @spa.get("/api/health")
    def _health() -> dict[str, str]:
        return {"status": "ok"}

    mount_spa(spa, str(dist))
    c = TestClient(spa)

    assert c.get("/").text.startswith("<!doctype html>")
    assert c.get("/assets/app.js").text == "console.log(1)"
    # Client-side route: no such file, so fall back to index.html (not 404).
    deep = c.get("/models/42")
    assert deep.status_code == 200
    assert deep.text.startswith("<!doctype html>")
    # A missing hashed asset stays a 404 rather than silently serving HTML.
    assert c.get("/assets/missing.js").status_code == 404
    # Real API route still wins over the catch-all mount.
    assert c.get("/api/health").json() == {"status": "ok"}


def test_serves_a_prerendered_route_directory_without_redirecting(dist):
    # A prerendered public route (frontend/scripts/prerender.mjs writes e.g.
    # privacy/index.html) must serve directly on the exact no-trailing-slash
    # path, not 307-redirect to add one: the base StaticFiles behavior builds
    # that redirect from the ASGI scope's scheme, which is plain "http" behind
    # a TLS-terminating proxy - downgrading an "https://" request and losing
    # any crawler that won't follow a scheme-downgrading redirect.
    spa = FastAPI()
    mount_spa(spa, str(dist))
    c = TestClient(spa, follow_redirects=False)

    resp = c.get("/privacy")
    assert resp.status_code == 200
    assert resp.text.startswith("<!doctype html><title>Privacy</title>")

    # A trailing slash still works too.
    resp_slash = c.get("/privacy/")
    assert resp_slash.status_code == 200
    assert resp_slash.text.startswith("<!doctype html><title>Privacy</title>")
