#!/usr/bin/env bash
# Single-image entrypoint: run DB migrations, then serve the UI + API from one
# uvicorn process on port 8000. Migrations and the app share one DB URL (see
# src/lexis_api/alembic/env.py), so a fresh volume / an upgrade is always applied
# before uvicorn starts accepting requests. Mirrors docker/backend-entrypoint.sh;
# the frontend is served by the app itself (LEXIS_FRONTEND_DIST_DIR).
set -euo pipefail

alembic upgrade head
exec uvicorn lexis_api.main:app --host 0.0.0.0 --port 8000
