# Build context is the repo root - see docker-compose.yml / scripts/docker-build.sh.
FROM docker.io/node:24-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# -slim drops the dynamic modules (njs, image-filter, xslt, geoip) this config
# doesn't use - smaller image, smaller attack surface. `apk upgrade` then pulls
# Alpine security fixes the pinned base image hasn't been rebuilt with yet.
FROM docker.io/nginx:1.29-alpine-slim

# Declared (unused) so a shared `--build-arg LEXIS_VERSION=...` from CI doesn't
# warn here - the frontend image carries no Python package to version.
ARG LEXIS_VERSION

RUN apk upgrade --no-cache

COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

# Runtime DNS re-resolution for the `api` upstream (see docker/nginx.conf):
# a build-time default so `include` always resolves, plus an entrypoint script
# that rewrites it from the container's /etc/resolv.conf before nginx starts.
RUN printf 'resolver 127.0.0.11 valid=10s ipv6=off;\n' > /etc/nginx/lexis-resolver.conf
COPY docker/nginx-resolver.sh /docker-entrypoint.d/20-lexis-resolver.sh
RUN chmod +x /docker-entrypoint.d/20-lexis-resolver.sh

# OCI metadata (CI overrides description/created/revision via docker/metadata-action;
# this is the fallback for local `scripts/docker-build.sh` builds).
LABEL org.opencontainers.image.title="lexis-web" \
      org.opencontainers.image.description="Lexis web UI - React SPA served by nginx, proxying /api to the Lexis API" \
      org.opencontainers.image.source="https://github.com/PuspenduBanerjee/Lexis" \
      org.opencontainers.image.licenses="Apache-2.0"

EXPOSE 8080
