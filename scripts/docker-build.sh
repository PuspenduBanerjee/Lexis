#!/usr/bin/env bash
# Builds Lexis container images directly (no compose file) - useful for CI or
# pushing to a registry. `<engine> compose build` (docker-compose.yml /
# docker-compose.uber.yml at the repo root) builds the same images from the same
# Dockerfiles for local dev.
#
# Works with Docker or Podman: set CONTAINER_ENGINE=podman (or it's auto-detected
# when only one of the two is on PATH). The Dockerfiles use fully-qualified base
# images (docker.io/...) so rootless Podman resolves them without prompting.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/docker-build.sh [--type TYPE] [TAG]

Build types (--type / -t):
  split   (default)  lexis-api + lexis-web  - API and the nginx/SPA frontend as
                     two images you scale/deploy separately
                     (docker/backend.Dockerfile + docker/frontend.Dockerfile)
  uber               lexis-uber             - web UI + API bundled in one image on
                     one port, no nginx (docker/uber.Dockerfile)
  all                every image above

Arguments:
  TAG                image tag to apply (default: latest)

Options:
  -t, --type TYPE    which images to build: split | uber | all (default: split)
  -h, --help         show this help and exit

Environment:
  CONTAINER_ENGINE   docker | podman (auto-detected when only one is on PATH)

Examples:
  scripts/docker-build.sh                     # lexis-api + lexis-web, :latest
  scripts/docker-build.sh 0.3.0               # lexis-api + lexis-web, :0.3.0
  scripts/docker-build.sh --type uber         # lexis-uber, :latest
  scripts/docker-build.sh -t all 0.3.0        # every image, :0.3.0
  CONTAINER_ENGINE=podman scripts/docker-build.sh
EOF
}

cd "$(dirname "${BASH_SOURCE[0]}")/.."

BUILD_TYPE="split"
TAG="latest"
tag_set=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -t|--type)
      [[ $# -ge 2 ]] || { echo "error: $1 needs a value (split|uber|all)" >&2; exit 2; }
      BUILD_TYPE="$2"
      shift 2
      ;;
    --type=*)
      BUILD_TYPE="${1#*=}"
      shift
      ;;
    -*)
      echo "error: unknown option '$1'" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ "${tag_set}" == true ]]; then
        echo "error: unexpected extra argument '$1'" >&2
        exit 2
      fi
      TAG="$1"
      tag_set=true
      shift
      ;;
  esac
done

case "${BUILD_TYPE}" in
  split|uber|all) ;;
  *)
    echo "error: invalid --type '${BUILD_TYPE}' (expected split|uber|all)" >&2
    exit 2
    ;;
esac

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

built=()

build_image() {
  local image="$1" dockerfile="$2"
  echo "Building ${image}:${TAG} with ${CONTAINER_ENGINE} (${dockerfile}) ..."
  "${CONTAINER_ENGINE}" build -f "${dockerfile}" -t "${image}:${TAG}" .
  built+=("${image}:${TAG}")
}

if [[ "${BUILD_TYPE}" == split || "${BUILD_TYPE}" == all ]]; then
  build_image lexis-api docker/backend.Dockerfile
  build_image lexis-web docker/frontend.Dockerfile
fi
if [[ "${BUILD_TYPE}" == uber || "${BUILD_TYPE}" == all ]]; then
  build_image lexis-uber docker/uber.Dockerfile
fi

echo "Built: ${built[*]}"
filters=()
for ref in "${built[@]}"; do
  filters+=(--filter "reference=${ref}")
done
"${CONTAINER_ENGINE}" images "${filters[@]}"
