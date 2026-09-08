# syntax=docker/dockerfile:1
# Build context is the repo root (see docker-compose.yml / scripts/docker-build.sh) -
# so this can COPY src/, pyproject.toml, and alembic.ini in one shot.
FROM docker.io/python:3.14-slim

# Pull whatever Debian security updates have shipped since the base image was
# built. Most current CVEs against trixie's util-linux/perl-base cluster have no
# upstream fix yet (local-privesc TOCTOU, not reachable by this API), but this
# absorbs them automatically once Debian releases the point updates.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# README.md is required at build time: pyproject.toml's `readme = "README.md"` makes
# hatchling read it while generating package metadata for the `pip install -e` below,
# and it errors out ("Readme file does not exist") if the file is missing.
COPY pyproject.toml README.md LICENSE NOTICE alembic.ini ./

# Copy only the hatchling package (src/lexis) before installing: dependency
# resolution needs it, but edits to src/lexis_api (the API code, where most churn
# is) then don't invalidate this layer. The pip cache mount persists downloaded
# wheels across builds, so even a pyproject.toml change reinstalls without
# re-downloading from PyPI. (Drop `--no-cache-dir` - the cache mount is not a
# layer, so it doesn't bloat the image.)
COPY src/lexis ./src/lexis

# Editable install: the wheel's `packages` config only lists src/lexis (the
# published PyPI package should stay CLI/library-only), but a source install of
# this image needs lexis_api too - editable mode adds the whole src/ tree to the
# path regardless of that restriction, since /app/src stays present at runtime
# (the full COPY below).
RUN --mount=type=cache,target=/root/.cache/pip pip install -e ".[api]"

COPY src ./src

COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh
COPY docker/healthcheck.py /usr/local/bin/lexis-healthcheck.py
RUN chmod +x /usr/local/bin/backend-entrypoint.sh

# SQLite lives on a volume, not in the image, so data survives container recreation.
ENV LEXIS_DATABASE_URL=sqlite:////data/lexis.db

# Run as non-root. /data is chowned before VOLUME so the named volume inherits
# `app` ownership on first use (Podman/Docker seed a fresh named volume from the
# image path, permissions included); the entrypoint's alembic step and uvicorn
# then write the SQLite file without needing root.
RUN useradd --system --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /data /app
VOLUME /data
USER app

EXPOSE 8000
ENTRYPOINT ["backend-entrypoint.sh"]
