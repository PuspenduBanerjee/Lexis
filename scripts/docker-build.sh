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
Usage: scripts/docker-build.sh [--type TYPE] [--platform PLATFORM] [--prefix PREFIX] [TAG]

Build types (--type / -t):
  split   (default)  lexis-api + lexis-web  - API and the nginx/SPA frontend as
                     two images you scale/deploy separately
                     (docker/backend.Dockerfile + docker/frontend.Dockerfile)
  uber               lexis-uber             - web UI + API bundled in one image on
                     one port, no nginx (docker/uber.Dockerfile)
  all                every image above

Arguments:
  TAG                image tag to apply (default: "latest", or "<arch>-latest" when
                     --platform is a single linux/<arch> platform, e.g. building
                     --platform linux/arm64 with no TAG tags it arm64-latest)

Options:
  -t, --type TYPE        which images to build: split | uber | all (default: split)
  -p, --platform PLATFORM
                          target platform, e.g. linux/arm64 or linux/amd64 (default:
                          unset - the engine's own default, normally the host's
                          platform). Passed straight through as `--platform` to
                          `docker build`/`podman build`. Building for a platform other
                          than the host's needs cross-arch emulation registered
                          (Docker Desktop/Docker Engine with buildx: usually already
                          set up; standalone: `docker run --privileged --rm
                          tonistiigi/binfmt --install all`; Podman: `podman machine`
                          on macOS handles it, native Linux needs qemu-user-static).
                          Docker also requires the buildx builder (default since
                          Docker 23) - the legacy builder rejects `--platform`.
  --prefix PREFIX         prepended to every image name, e.g. `--prefix
                          puspendubanerjee/` builds `puspendubanerjee/lexis-api`
                          instead of `lexis-api` - so the result can be `docker push`ed
                          straight to Docker Hub (or any registry: `--prefix
                          ghcr.io/you/`) with no separate retagging step. Include
                          the trailing `/` yourself; also settable via the
                          IMAGE_PREFIX env var (the flag wins if both are given).
  -h, --help              show this help and exit

Environment:
  CONTAINER_ENGINE   docker | podman (auto-detected when only one is on PATH)
  IMAGE_PREFIX       default for --prefix

Examples:
  scripts/docker-build.sh                     # lexis-api + lexis-web, :latest
  scripts/docker-build.sh 0.3.0               # lexis-api + lexis-web, :0.3.0
  scripts/docker-build.sh --type uber         # lexis-uber, :latest
  scripts/docker-build.sh -t all 0.3.0        # every image, :0.3.0
  scripts/docker-build.sh --platform linux/arm64 --type uber
                                               # lexis-uber:arm64-latest
  scripts/docker-build.sh --prefix puspendubanerjee/ --type all
                                               # puspendubanerjee/lexis-api:latest, ...
  CONTAINER_ENGINE=podman scripts/docker-build.sh
EOF
}

cd "$(dirname "${BASH_SOURCE[0]}")/.."

BUILD_TYPE="split"
TAG=""
PLATFORM=""
IMAGE_PREFIX="${IMAGE_PREFIX:-}"
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
    -p|--platform)
      [[ $# -ge 2 ]] || { echo "error: $1 needs a value (e.g. linux/arm64)" >&2; exit 2; }
      PLATFORM="$2"
      shift 2
      ;;
    --platform=*)
      PLATFORM="${1#*=}"
      shift
      ;;
    --prefix)
      [[ $# -ge 2 ]] || { echo "error: $1 needs a value (e.g. puspendubanerjee/)" >&2; exit 2; }
      IMAGE_PREFIX="$2"
      shift 2
      ;;
    --prefix=*)
      IMAGE_PREFIX="${1#*=}"
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

# Default tag: "latest", except a single-arch --platform with no explicit TAG gets
# "<arch>-latest" instead (e.g. --platform linux/arm64 -> arm64-latest) so an
# arm64 and an amd64 build of the same version don't clobber each other's :latest.
# Skipped for a comma-separated multi-platform value (ambiguous which arch to name).
if [[ "${tag_set}" == false ]]; then
  TAG="latest"
  if [[ -n "${PLATFORM}" && "${PLATFORM}" != *,* ]]; then
    IFS='/' read -r _platform_os platform_arch _platform_variant <<< "${PLATFORM}"
    [[ -n "${platform_arch}" ]] && TAG="${platform_arch}-latest"
  fi
fi

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
  local base_name="$1" dockerfile="$2"
  local image="${IMAGE_PREFIX}${base_name}"
  local -a platform_args=()
  [[ -n "${PLATFORM}" ]] && platform_args=(--platform "${PLATFORM}")
  echo "Building ${image}:${TAG} with ${CONTAINER_ENGINE} (${dockerfile})${PLATFORM:+, platform ${PLATFORM}} ..."
  "${CONTAINER_ENGINE}" build "${platform_args[@]}" -f "${dockerfile}" -t "${image}:${TAG}" .
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
