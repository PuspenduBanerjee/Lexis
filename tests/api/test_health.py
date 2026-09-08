"""The unauthenticated liveness probe (routers/health.py), used by the Docker
healthcheck."""


def test_health_returns_200_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_needs_no_auth_header(client):
    # no X-Account-Id, and it must not fall through to the user lookup
    resp = client.get("/api/health", headers={"X-Account-Id": "999999"})
    assert resp.status_code == 200
