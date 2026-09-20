"""Google-identity auth path: X-User-Email (ngrok's oauth traffic-policy action) or
Cf-Access-Authenticated-User-Email (Cloudflare Access in front of a cloudflared
tunnel) takes priority over the X-Account-Id dev stub, auto-provisions a viewer on
first sign-in, and can be made mandatory by turning the dev stub off.
"""

from lexis_api.config import settings


def test_new_google_identity_is_auto_provisioned_as_viewer(client):
    resp = client.get(
        "/api/users/me",
        headers={"X-User-Email": "new.person@example.com", "X-User-Name": "New Person"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "new.person@example.com"
    assert body["username"] == "New Person"
    assert body["role"] == "viewer"


def test_same_email_resolves_to_the_same_user_on_repeat_requests(client):
    first = client.get("/api/users/me", headers={"X-User-Email": "same@example.com"})
    second = client.get("/api/users/me", headers={"X-User-Email": "same@example.com"})
    assert first.json()["id"] == second.json()["id"]


def test_username_collision_with_a_dev_stub_user_is_disambiguated(client):
    # "admin" is already taken by the seeded dev-stub user (id 1).
    resp = client.get(
        "/api/users/me",
        headers={"X-User-Email": "admin@example.com", "X-User-Name": "admin"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] != "admin"
    assert body["email"] == "admin@example.com"


def test_google_identity_header_overrides_the_dev_account_id_header(client):
    resp = client.get(
        "/api/users/me",
        headers={"X-User-Email": "wins@example.com", "X-Account-Id": "1"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "wins@example.com"


def test_cloudflare_access_header_also_authenticates(client):
    resp = client.get(
        "/api/users/me",
        headers={"Cf-Access-Authenticated-User-Email": "cf.person@example.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "cf.person@example.com"
    assert body["role"] == "viewer"
    # Cloudflare Access has no "display name" header - falls back to the email.
    assert body["username"] == "cf.person@example.com"


def test_cloudflare_access_header_overrides_the_dev_account_id_header(client):
    resp = client.get(
        "/api/users/me",
        headers={"Cf-Access-Authenticated-User-Email": "cf.wins@example.com", "X-Account-Id": "1"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "cf.wins@example.com"


def test_dev_stub_can_be_disabled_once_google_auth_is_in_place(client):
    settings.dev_auth_header_enabled = False
    try:
        resp = client.get("/api/users/me", headers={"X-Account-Id": "1"})
        assert resp.status_code == 401

        resp = client.get("/api/users/me")  # no headers at all
        assert resp.status_code == 401

        # Google identity still works regardless of the stub being off, either way in.
        resp = client.get("/api/users/me", headers={"X-User-Email": "still.works@example.com"})
        assert resp.status_code == 200
        resp = client.get(
            "/api/users/me", headers={"Cf-Access-Authenticated-User-Email": "cf.still.works@example.com"}
        )
        assert resp.status_code == 200
    finally:
        settings.dev_auth_header_enabled = True
