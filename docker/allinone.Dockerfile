# syntax=docker/dockerfile:1
# Single image bundling the web UI and the API behind one process and one port.
# The React SPA is built with node, then served as static files by the FastAPI
# app itself (LEXIS_FRONTEND_DIST_DIR -> src/lexis_api/static.py) - no nginx, no
# process manager. Use docker/backend.Dockerfile + docker/frontend.Dockerfile
# instead when you want the UI and API scaled/deployed separately.
#
# Build context is the repo root (see scripts/docker-build.sh).

# --- Stage 1: build the frontend -------------------------------------------------
FROM docker.io/node:24-alpine AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: the API image, plus the built UI --------------------------------
FROM docker.io/python:3.14-slim

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE NOTICE alembic.ini ./
COPY src/lexis ./src/lexis

ARG LEXIS_VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${LEXIS_VERSION}

RUN --mount=type=cache,target=/root/.cache/pip pip install -e ".[api]"

COPY src ./src

COPY docker/allinone-entrypoint.sh /usr/local/bin/allinone-entrypoint.sh
COPY docker/healthcheck.py /usr/local/bin/lexis-healthcheck.py
RUN chmod +x /usr/local/bin/allinone-entrypoint.sh

# Vite build output, served by the app from `/` (see src/lexis_api/static.py).
COPY --from=web /web/dist /app/frontend-dist
ENV LEXIS_FRONTEND_DIST_DIR=/app/frontend-dist

# SQLite lives on a volume, not in the image, so data survives container recreation.
ENV LEXIS_DATABASE_URL=sqlite:////data/lexis.db
# The SPA and the API are same-origin here, so CORS is irrelevant - but keep the
# app's own port allowed for anything that still sends an Origin header.
ENV LEXIS_CORS_ORIGINS='["http://localhost:8000"]'

RUN useradd --system --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /data /app
VOLUME /data
USER app

LABEL org.opencontainers.image.title="lexis" \
      org.opencontainers.image.description="Lexis - single image bundling the web UI and the FastAPI/MCP backend" \
      org.opencontainers.image.source="https://github.com/PuspenduBanerjee/Lexis" \
      org.opencontainers.image.licenses="Apache-2.0"

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "/usr/local/bin/lexis-healthcheck.py"]
ENTRYPOINT ["allinone-entrypoint.sh"]
