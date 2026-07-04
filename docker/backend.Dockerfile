# Build context is the repo root (see docker-compose.yml / scripts/docker-build.sh) -
# so this can COPY src/, pyproject.toml, and alembic.ini in one shot.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml LICENSE NOTICE alembic.ini ./
COPY src ./src

RUN pip install --no-cache-dir ".[api]"

COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh
RUN chmod +x /usr/local/bin/backend-entrypoint.sh

# SQLite lives on a volume, not in the image, so data survives container recreation.
ENV SEMANTICA_DATABASE_URL=sqlite:////data/semantica.db
RUN mkdir -p /data
VOLUME /data

EXPOSE 8000
ENTRYPOINT ["backend-entrypoint.sh"]
