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
