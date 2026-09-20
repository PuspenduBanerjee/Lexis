"""Serve the built frontend (the React SPA) from the API process itself, so a
single image/container exposes both the API and the UI. This is the production
counterpart to dev_proxy.py: dev_proxy forwards to the live Vite dev server,
this serves Vite's static `dist/` output directly.

Enabled only when `settings.frontend_dist_dir` points at a directory containing
`index.html` (see config.py / docker/uber.Dockerfile); unset by default, so
a plain `pip install "lexis-cli[api]"` run and the split api+nginx compose setup
(docker/nginx.conf serves the frontend there) are both unaffected.

`mount_spa` must be called last - after every real `/api/...` route/mount - so
Starlette's first-match-wins routing always tries the API routes before falling
through to this catch-all static mount.
"""

import stat
from pathlib import Path
from typing import Any

import anyio
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
    broken build.

    Also serves a prerendered route directory's `index.html` (e.g. `/privacy`
    -> `privacy/index.html`, written by frontend/scripts/prerender.mjs)
    directly, instead of the base class's default of redirecting to the
    trailing-slash URL first. That redirect is built from the ASGI scope's
    scheme, which reflects what the app server sees - plain `http`, since
    Cloudflare (or any TLS-terminating proxy) forwards to the origin over
    plain HTTP - so it downgrades an `https://` request to an `http://`
    redirect. A crawler that (correctly) won't follow a scheme-downgrading
    redirect - e.g. Google's OAuth consent screen homepage/policy verifier -
    would otherwise see zero content for these routes."""

    async def get_response(self, path: str, scope: Any) -> Response:
        if path and not path.endswith("/") and not path.startswith("assets/"):
            full_path, stat_result = await anyio.to_thread.run_sync(self.lookup_path, f"{path}/index.html")
            if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
                return self.file_response(full_path, stat_result, scope)
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
