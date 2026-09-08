#!/usr/bin/env bash
# Builds the two Lexis container images (backend API + frontend/nginx) directly,
# independent of a compose file - useful for CI or pushing to a registry.
# `<engine> compose build` (using docker-compose.yml at the repo root) builds the
# same two images from the same Dockerfiles for local dev.
#
# Works with Docker or Podman: set CONTAINER_ENGINE=podman (or it's auto-detected
# when only one of the two is on PATH). The Dockerfiles use fully-qualified base
# images (docker.io/...) so rootless Podman resolves them without prompting.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ -z "${CONTAINER_ENGINE:-}" ]]; then
  if command -v docker >/dev/null 2>&1; then
    CONTAINER_ENGINE=docker
  elif command -v podman >/dev/null 2>&1; then
    CONTAINER_ENGINE=podman
  else
    echo "error: neither 'docker' nor 'podman' found on PATH (set CONTAINER_ENGINE)" >&2
    exit 1
  fi
fi

TAG="${1:-latest}"

echo "Building lexis-api:${TAG} with ${CONTAINER_ENGINE} ..."
"$CONTAINER_ENGINE" build -f docker/backend.Dockerfile -t "lexis-api:${TAG}" .

echo "Building lexis-web:${TAG} with ${CONTAINER_ENGINE} ..."
"$CONTAINER_ENGINE" build -f docker/frontend.Dockerfile -t "lexis-web:${TAG}" .

echo "Built lexis-api:${TAG} and lexis-web:${TAG}"
"$CONTAINER_ENGINE" images --filter "reference=lexis-api:${TAG}" --filter "reference=lexis-web:${TAG}"
