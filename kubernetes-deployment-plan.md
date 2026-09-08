# Deploy Lexis to Kubernetes via Podman (`podman kube play`) + Helm chart

> Status: **planning / to revisit later.** Nothing in this doc has been implemented.

## Context

Lexis currently ships only a Docker/Podman **Compose** deployment (`docker-compose.yml`,
`docker/backend.Dockerfile`, `docker/frontend.Dockerfile`). The `feature/podman` branch
added rootless-Podman compatibility (fully-qualified base images, a file-based
healthcheck, `scripts/docker-build.sh`). There are **no Kubernetes manifests** of any
kind in the repo.

Goal: package the two services (FastAPI `api` on :8000, nginx-served React `web` on :8080)
as a **Helm chart** that renders to Kubernetes YAML, and run it on a single host with
**`podman kube play`** (no real scheduler / cluster). Images are published to **Docker Hub**.
Ship **SQLite** manifests now (1 API replica) and **document a PostgreSQL migration path**
for future multi-replica / real-cluster use.

### What we're working with (from exploration)

| Item | Value |
|---|---|
| Services | `api` (uvicorn, :8000, internal), `web` (nginx, :8080, published). MCP endpoint is the **same** api process under `/api/mcp*`. |
| UI ↔ API | Same-origin `/api/*`; nginx proxies `location /api/ → http://api:8000/api/` (hardcoded compose service name `api`). No API URL baked into the frontend bundle. |
| Persistent state | One volume: SQLite at `/data/lexis.db` (`LEXIS_DATABASE_URL=sqlite:////data/lexis.db`). `/tmp` scratch for `.duckdb` uploads (≤ `LEXIS_MAX_DUCKDB_UPLOAD_MB`, default 50). |
| Migrations | `docker/backend-entrypoint.sh` runs `alembic upgrade head` then `exec uvicorn ...` on every start. |
| Startup seeding | `main.py` lifespan seeds 3 demo users + 2 sample models. |
| Config (env, prefix `LEXIS_`) | `LEXIS_DATABASE_URL`, `LEXIS_CORS_ORIGINS` (JSON list string), `LEXIS_DEFAULT_USER_ID`, `LEXIS_MAX_DUCKDB_UPLOAD_MB`, `LEXIS_UPLOAD_TMP_DIR`, `LEXIS_MAX_RESULT_ROWS`. `src/lexis_api/config.py`. Dev-only: `LEXIS_DEV_SETUP_DEMO` / `LEXIS_DEMO_DATA_DIR` (startup writes demo `.duckdb` files + `duckdb_file` connections) — leave **unset** in the chart. |
| Secrets | Only Snowflake passwords, read from an env var **named** by each connection's `password_env` (`connection_runtime.py`). None required unless a Snowflake connection is used. |
| Health | `GET /api/health` — unauthenticated, no DB touch. Good for liveness **and** readiness. nginx has no health location — probe `/`. |
| Security (compose) | api: `no-new-privileges`, `cap_drop: ALL`, uid 1000. web: `cap_drop: ALL` + `cap_add: CHOWN,SETUID,SETGID,DAC_OVERRIDE` (nginx master starts as root), `no-new-privileges`. |
| Scaling constraint | SQLite = single writer → **1 api replica, `Recreate`, RWO volume**. `db.py` branches only on `sqlite` prefix, so a Postgres URL "just works" once a driver is added. |
| No | GPU / ML models, Redis, queues, object storage, LLM API keys, existing k8s/Helm, image-publish CI. |

## Decisions (from user)

1. **Runtime target:** `podman kube play` on a single host — no real cluster, no HPA, no Ingress controller. Topology should still mirror a real cluster so the chart is reusable later.
2. **Packaging:** Helm chart at `charts/lexis/`. Rendered for Podman with `helm template ... | podman kube play -`.
3. **Database:** SQLite manifests now; Postgres path documented + gated behind a chart value (`postgres.enabled`, off by default).
4. **Registry:** GitHub Container Registry — `ghcr.io/<owner>/lexis-api` and `.../lexis-web`, built and pushed by GitHub Actions (`.github/workflows/publish-images.yml`, **added**). The same workflow **also pushes to Docker Hub** (`docker.io/<DOCKERHUB_USERNAME>/lexis-{api,web}`) when the `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` repo secrets are set — otherwise that target is skipped. Manual `podman push` to any registry still works via `scripts/docker-build.sh`.

## Podman `kube play` constraints that shape the design

- **Supported kinds:** `Pod`, `Deployment`, `PersistentVolumeClaim`, `ConfigMap`, `Secret`, `Service` (basic ClusterIP DNS via aardvark-dns), `Job`, `initContainers`, `securityContext`, `resources.limits`, `livenessProbe`/`readinessProbe` (httpGet/exec).
- **Not supported:** `Ingress`, `HorizontalPodAutoscaler`, `StatefulSet` (partial/varies), storage classes / dynamic provisioning (PVC → a plain podman named volume).
- **Cross-pod DNS:** a `Service` named `api` is resolvable from the `web` pod on the network `kube play` creates. nginx now re-resolves `api` at runtime (`resolver` from `/etc/resolv.conf` + variable `proxy_pass`, added in `docker/nginx.conf` + `docker/nginx-resolver.sh`), so a restarted/rescheduled api pod with a new IP is picked up without restarting `web`. For a **single Pod** with both containers, the `api` name still resolves to the shared pod IP, so no nginx change is needed there either.
- **Port exposure:** no LoadBalancer/NodePort. Expose `web` with `hostPort` on the container port (or `podman kube play --publish 8080:8080`). Chart value `web.hostPort`.
- **`no-new-privileges`:** express as `securityContext.allowPrivilegeEscalation: false` (honored by Podman) rather than the compose `security_opt`.

## What to build

### 1. Helm chart — `charts/lexis/`

```
charts/lexis/
  Chart.yaml                     # name: lexis, type: application, appVersion "0.1.0"
  values.yaml                    # documented defaults (see below)
  values-podman.yaml             # overlay: ingress off, hostPort on, resources modest
  templates/
    _helpers.tpl                 # lexis.labels, lexis.selectorLabels, image refs
    configmap.yaml               # LEXIS_CORS_ORIGINS, LEXIS_MAX_*, LEXIS_DEFAULT_USER_ID, LEXIS_UPLOAD_TMP_DIR=/tmp
    secret.yaml                  # {{- if .Values.snowflake.passwords }} — name→value env pairs; else skip
    api-pvc.yaml                 # {{- if not .Values.postgres.enabled }} RWO PVC "lexis-data", .Values.api.persistence.size
    api-deployment.yaml          # replicas 1, strategy Recreate, initContainer for migrations (see note), 1 container
    api-service.yaml             # name: api (MUST stay "api"), ClusterIP, port 8000
    web-deployment.yaml          # replicas .Values.web.replicas (default 1), RollingUpdate
    web-service.yaml             # name: web, ClusterIP, port 8080
    ingress.yaml                 # {{- if .Values.ingress.enabled }} — OFF for podman, ready for real clusters
    postgres.yaml                # {{- if .Values.postgres.enabled }} — Deployment + Service + PVC (dev-grade single instance)
    NOTES.txt                    # how to reach the app + podman kube down hint
  .helmignore
```

Key template details:

- **api container**
  - image `{{ .Values.image.registry }}/{{ .Values.image.api.repository }}:{{ .Values.image.api.tag | default .Chart.AppVersion }}`, `pullPolicy` value.
  - `env` from the ConfigMap (`envFrom: configMapRef`) + `LEXIS_DATABASE_URL` from a value (`sqlite:////data/lexis.db` default, or the Postgres URL when `postgres.enabled`).
  - `volumeMounts`: `lexis-data → /data` (from PVC; omit when Postgres), `scratch → /tmp` (`emptyDir`, `sizeLimit` = `2 * maxDuckdbUploadMb` Mi).
  - `securityContext`: `runAsNonRoot: true`, `runAsUser: 1000`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `readOnlyRootFilesystem: true` (works — writes go to `/data` + `/tmp` only), `seccompProfile.type: RuntimeDefault`.
  - `livenessProbe` & `readinessProbe`: `httpGet /api/health` port 8000 (`initialDelaySeconds` ~10, `periodSeconds` 15). Startup handled by `readinessProbe` `failureThreshold` (migrations + seeding take a few s).
  - `resources`: requests `100m`/`256Mi`, limits `1`/`512Mi` (tunable; DuckDB query bursts).
- **Migrations** — two supported modes, pick via `.Values.migrations.mode`:
  - `entrypoint` (default, SQLite): keep `backend-entrypoint.sh` as-is; safe with 1 replica.
  - `initContainer` (Postgres / multi-replica): initContainer runs `alembic upgrade head`; override the main container `command` to skip the migrate step (needs a tiny entrypoint tweak — see change #2, optional).
- **web container**
  - image `.../lexis-web`, port 8080, `hostPort: {{ .Values.web.hostPort }}` (podman overlay only).
  - `securityContext`: `capabilities.drop: [ALL]`, `add: [CHOWN, SETUID, SETGID, DAC_OVERRIDE]`, `allowPrivilegeEscalation: false`. `readOnlyRootFilesystem: false` (nginx writes `/var/cache/nginx`, `/var/run`) unless we add emptyDir mounts — keep `false` for now, note as hardening follow-up.
  - `readinessProbe`/`livenessProbe`: `httpGet /` port 8080.
  - No `depends_on` equivalent — the readiness probe + nginx retry/proxy handles api-not-ready (nginx returns 502 briefly).

`values.yaml` surface (documented):
```yaml
image:
  registry: ghcr.io/<owner>
  pullPolicy: IfNotPresent
  api: { repository: lexis-api, tag: "" }   # "" → Chart.AppVersion
  web: { repository: lexis-web, tag: "" }
imagePullSecrets: []                        # add if the GHCR packages stay private
api:
  persistence: { size: 1Gi }
  cors: ["http://localhost:8080"]           # MUST list the browser origin used to reach web
  maxDuckdbUploadMb: 50
  maxResultRows: 1000
  defaultUserId: 1
  resources: { ... }
web:
  replicas: 1
  hostPort: 8080                            # podman overlay
  resources: { ... }
migrations: { mode: entrypoint }            # entrypoint | initContainer
ingress: { enabled: false, className: "", host: "", tls: false }
postgres:
  enabled: false
  image: docker.io/postgres:17-alpine
  auth: { username: lexis, password: lexis, database: lexis }
  persistence: { size: 2Gi }
snowflake:
  passwords: {}                             # { MY_CONN_PW: "s3cr3t" } → Secret + env
```

### 2. Repo code changes (small)

- **`scripts/docker-build.sh`** — add optional tag/push: honor `REGISTRY` env; when set, tag `${REGISTRY}/lexis-{api,web}:${TAG}` and `${CONTAINER_ENGINE} push`. Or add a sibling `scripts/publish-images.sh`. (Test: shellcheck + a dry-run guard.)
- **`docker/backend-entrypoint.sh`** *(only if `migrations.mode=initContainer` is wanted)* — gate the migrate line behind `${LEXIS_RUN_MIGRATIONS:-1}` so the initContainer owns migrations and the app container skips them. Default unchanged. Add a test in `tests/` covering the env-var branch (bash test or a small pytest invoking the script).
- **`docker/nginx.conf` + `docker/nginx-resolver.sh`** *(done on the branch)* — nginx re-resolves the `api` upstream at runtime: a `resolver` line generated from the container's `/etc/resolv.conf` by `/docker-entrypoint.d/20-lexis-resolver.sh`, plus a variable in `proxy_pass`. Engine-agnostic (Docker embedded DNS / Podman aardvark-dns). No `LEXIS_API_UPSTREAM` / template needed; if you ever want to point `web` at a non-`api` host, add an `ENV`-driven `set $lexis_api_upstream` instead.
- **`pyproject.toml`** *(for the documented Postgres path)* — add `pg = ["psycopg[binary]>=3.2"]` under `[project.optional-dependencies]`; the api image installs `".[api]"` — either fold pg in or build a `lexis-api-pg` variant. Document; do **not** enable by default.

### 3. Runner + docs

- **`scripts/kube-play.sh`** — wrapper: `helm template lexis charts/lexis -f charts/lexis/values-podman.yaml ${EXTRA_ARGS} | podman kube play --replace -`. `scripts/kube-down.sh` → `... | podman kube down -`. (Test: shellcheck.)
- **`docs/deploy-kubernetes.md`** (new) — prerequisites (`helm`, Podman 5.x, `podman.socket` not needed for `kube play`), build+push to Docker Hub, `podman kube play` walkthrough, reaching the app on `http://localhost:8080`, CORS note, `podman kube play`'s unsupported-kinds list, teardown, and the **PostgreSQL migration path** (set `postgres.enabled=true` or point `LEXIS_DATABASE_URL` at an external DB, switch `migrations.mode=initContainer`, add the `pg` extra, expect to lose the SQLite data / re-seed).
- **`README.md`** — add a short "Kubernetes / `podman kube play`" subsection linking to `docs/deploy-kubernetes.md`, alongside the existing "Using Podman instead" section (~L281).
- **`.github/workflows/publish-images.yml`** — **added.** Buildx matrix over both images (`docker/backend.Dockerfile`, `docker/frontend.Dockerfile`, context = repo root). Pushes to `ghcr.io/<owner>/lexis-{api,web}` on pushes to `main` and on `v*` tags; builds only (no push) on PRs that touch `docker/`, `src/`, `frontend/`, or `pyproject.toml`. GHCR auth via the built-in `GITHUB_TOKEN` (`packages: write`) — no extra secrets. **Docker Hub** is an additional push target: a `Resolve registry targets` step appends `docker.io/<DOCKERHUB_USERNAME>/<image>` to the `metadata-action` image list and enables the Docker Hub login **only when** the `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` repo secrets exist (set them under Settings → Secrets and variables → Actions; use a Docker Hub access token, not the password). Tags: branch, `pr-N`, semver (`X.Y.Z` + `X.Y`), `sha-…`, and `latest` on the default branch. GHA layer cache. After the first successful run, make the `lexis-api` / `lexis-web` GHCR packages public (or wire an `imagePullSecret` into the chart) so `podman kube play` can pull them.

### 4. `.dockerignore` / `.helmignore`

- `.dockerignore` already excludes `docs`, `.github`, etc. Add `charts` so chart edits don't bust the image build cache.

## Verification

1. **Chart lints & renders**
   - `helm lint charts/lexis`
   - `helm template lexis charts/lexis -f charts/lexis/values-podman.yaml | kubeconform -strict -summary` (add `kubeconform` to dev tooling / a CI job).
2. **Images build with Podman**
   - `CONTAINER_ENGINE=podman ./scripts/docker-build.sh dev` → `lexis-api:dev`, `lexis-web:dev` present in `podman images`.
   - Push path (CI): merge to `main`, confirm the `publish-images.yml` run is green and `ghcr.io/<owner>/lexis-api:latest` + `:sha-<short>` exist. Local alternative: `REGISTRY=ghcr.io/<owner> CONTAINER_ENGINE=podman ./scripts/docker-build.sh dev`.
3. **`podman kube play` brings the app up**
   - `./scripts/kube-play.sh` (images tag = `dev` via `--set image.api.tag=dev --set image.web.tag=dev`).
   - `podman pod ps` / `podman ps` → api + web running; `podman logs <api>` shows `alembic upgrade head` then `Uvicorn running on 0.0.0.0:8000` and the seed log lines.
   - Probes: `podman healthcheck run <api-container>` exits 0; readiness gate satisfied.
4. **End-to-end**
   - `curl -fsS http://localhost:8080/api/health` → `{"status":"ok"}` (proves nginx → `api` Service DNS → uvicorn).
   - `curl -fsS http://localhost:8080/` → `index.html`.
   - Browser `http://localhost:8080` → app loads, model list shows `tpcds` + `retail_analytics`, a query on `retail_analytics` returns rows (proves DuckDB + `/tmp` scratch + `X-Account-Id` default).
   - `curl -s -X POST http://localhost:8080/api/mcp -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"c","version":"0"}}}'` → MCP init response (proves the ASGI mount is reachable through the ingress path).
5. **Persistence**
   - `./scripts/kube-down.sh` then `./scripts/kube-play.sh` again → previously created data survives (PVC-backed podman volume `lexis-data`); no re-seed of duplicate demo users.
6. **Postgres path (spot check, not shipped on)**
   - `helm template ... --set postgres.enabled=true --set migrations.mode=initContainer` renders a postgres Deployment/Service/PVC, drops the `lexis-data` PVC, and the api Deployment gains a migration initContainer with the Postgres `LEXIS_DATABASE_URL`.

## Follow-ups (not done)

- **Slim the `lexis-api` image (~352 MB now).** Weight is Python deps, not the base (`python:3.14-slim` is right; Alpine/musl breaks duckdb/pyarrow/cryptography wheels, distroless has no shell for the bash entrypoint + no 3.14). Biggest win: split `snowflake-connector-python` into a `[snowflake]` extra and lazy-import it (`src/lexis_api/main.py:8`, `connection_runtime.py:17`; `cli.py` already does), building a separate `-snowflake` variant → −~65 MB (connector + botocore's 27 MB of service JSON + cryptography + boto3). Then multi-stage + `strip --strip-unneeded` on `.so`s → −31 MB, and drop pip/`--no-compile` → −~22 MB. ~352 → ~235 MB.

## Out of scope

- Real cluster concerns: Ingress controller wiring, cert-manager/TLS, cloud StorageClasses, HPA, PodDisruptionBudget, NetworkPolicy (chart leaves `ingress`/HPA hooks but they're unused here).
- Edge authentication (the app still trusts `X-Account-Id`; production needs auth terminated upstream).
- Actual data migration tooling from SQLite → Postgres (documented as "re-seed / manual" only).
- Multi-arch image builds.
