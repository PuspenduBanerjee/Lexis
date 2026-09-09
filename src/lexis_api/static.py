"""Serve the built frontend (the React SPA) from the API process itself, so a
single image/container exposes both the API and the UI. This is the production
counterpart to dev_proxy.py: dev_proxy forwards to the live Vite dev server,
this serves Vite's static `dist/` output directly.

Enabled only when `settings.frontend_dist_dir` points at a directory containing
`index.html` (see config.py / docker/allinone.Dockerfile); unset by default, so
a plain `pip install "lexis-cli[api]"` run and the split api+nginx compose setup
(docker/nginx.conf serves the frontend there) are both unaffected.

`mount_spa` must be called last - after every real `/api/...` route/mount - so
Starlette's first-match-wins routing always tries the API routes before falling
through to this catch-all static mount.
"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles


class SpaStaticFiles(StaticFiles):
    """`StaticFiles` that falls back to `index.html` for any path that doesn't
    map to a real file, instead of returning 404 - so the SPA's client-side
    router resolves deep links (e.g. `/models/42`) on a hard refresh. A missing
    file below a hashed-asset path (`/assets/...`) still 404s, since the SPA
    never requests those by a wrong name and serving HTML there just masks a
    broken build."""

    async def get_response(self, path: str, scope: Any) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and not path.startswith("assets/"):
                return await super().get_response("index.html", scope)
            raise


def mount_spa(app: FastAPI, dist_dir: str) -> None:
    """Mount the built frontend at `/`, serving `dist_dir` (Vite's build output).

    Raises `RuntimeError` if `dist_dir` has no `index.html` - a misconfigured
    path should fail loudly at startup rather than 404 every request.
    """
    if not (Path(dist_dir) / "index.html").is_file():
        raise RuntimeError(f"frontend_dist_dir has no index.html: {dist_dir}")
    app.mount("/", SpaStaticFiles(directory=dist_dir, html=True), name="spa")
