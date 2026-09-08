"""Liveness probe: unauthenticated, no DB access, always 200 while the process is
up. Used by the Docker healthcheck (see docker-compose.yml) instead of a real
endpoint like /api/users/me, so a transient DB/seed issue doesn't get the
container killed and restarted.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
