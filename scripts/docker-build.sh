#!/usr/bin/env bash
# Builds the two Semantica Docker images (backend API + frontend/nginx) directly
# with `docker build`, independent of docker-compose - useful for CI or pushing to
# a registry. `docker compose build` (using docker-compose.yml at the repo root)
# builds the same two images from the same Dockerfiles for local dev.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TAG="${1:-latest}"

echo "Building semantica-api:${TAG} ..."
docker build -f docker/backend.Dockerfile -t "semantica-api:${TAG}" .

echo "Building semantica-web:${TAG} ..."
docker build -f docker/frontend.Dockerfile -t "semantica-web:${TAG}" .

echo "Built semantica-api:${TAG} and semantica-web:${TAG}"
docker images --filter "reference=semantica-api:${TAG}" --filter "reference=semantica-web:${TAG}"
