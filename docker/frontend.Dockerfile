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

RUN apk upgrade --no-cache

COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
