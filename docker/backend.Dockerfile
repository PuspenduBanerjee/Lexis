# Build context is the repo root (see docker-compose.yml / scripts/docker-build.sh) -
# so this can COPY src/, pyproject.toml, and alembic.ini in one shot.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml LICENSE NOTICE alembic.ini ./
COPY src ./src

# Editable install: the wheel's `packages` config only lists src/lexis (the
# published PyPI package should stay CLI/library-only), but a source install of
# this image needs lexis_api too - editable mode adds the whole src/ tree to the
# path regardless of that restriction, since /app/src stays present at runtime.
RUN pip install --no-cache-dir -e ".[api]"

COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh
RUN chmod +x /usr/local/bin/backend-entrypoint.sh

# SQLite lives on a volume, not in the image, so data survives container recreation.
ENV LEXIS_DATABASE_URL=sqlite:////data/lexis.db
RUN mkdir -p /data
VOLUME /data

EXPOSE 8000
ENTRYPOINT ["backend-entrypoint.sh"]
