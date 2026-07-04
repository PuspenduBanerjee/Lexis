#!/usr/bin/env bash
# Migrations and the app share one source of truth for the DB URL (see
# src/semantica_api/alembic/env.py), so running them here first means a fresh
# volume/upgrade is always applied before uvicorn starts accepting requests.
set -euo pipefail

alembic upgrade head
exec uvicorn semantica_api.main:app --host 0.0.0.0 --port 8000
