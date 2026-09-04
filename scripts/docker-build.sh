#!/usr/bin/env bash
# Builds the two Lexis Docker images (backend API + frontend/nginx) directly
# with `docker build`, independent of docker-compose - useful for CI or pushing to
# a registry. `docker compose build` (using docker-compose.yml at the repo root)
# builds the same two images from the same Dockerfiles for local dev.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TAG="${1:-latest}"

echo "Building lexis-api:${TAG} ..."
docker build -f docker/backend.Dockerfile -t "lexis-api:${TAG}" .

echo "Building lexis-web:${TAG} ..."
docker build -f docker/frontend.Dockerfile -t "lexis-web:${TAG}" .

echo "Built lexis-api:${TAG} and lexis-web:${TAG}"
docker images --filter "reference=lexis-api:${TAG}" --filter "reference=lexis-web:${TAG}"
