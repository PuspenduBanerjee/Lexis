"""The per-request access log line (`main.log_request_identity` middleware), which
surfaces the `X-User-Email` / `X-User-Id` / `X-User-Name` headers ngrok's OAuth
traffic policy injects upstream.
"""

import logging

_LOGGER = "lexis_api.access"


def _line(caplog) -> str:
    return next(r.getMessage() for r in caplog.records if r.name == _LOGGER)


def test_logs_identity_headers_when_present(client_as, caplog):
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        resp = client_as("admin").get(
            "/api/models",
            headers={
                "X-User-Email": "alice@gmail.com",
                "X-User-Id": "108451234567890",
                "X-User-Name": "Alice Example",
            },
        )
    assert resp.status_code == 200
    line = _line(caplog)
    assert "GET /api/models -> 200" in line
    assert "X-User-Email=alice@gmail.com" in line
    assert "X-User-Id=108451234567890" in line
    assert "X-User-Name=Alice Example" in line


def test_logs_dash_when_identity_headers_absent(client_as, caplog):
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        client_as("admin").get("/api/models")
    assert "X-User-Email=- X-User-Id=- X-User-Name=-" in _line(caplog)


def test_logs_the_response_status(client_as, caplog):
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        client_as("viewer").post("/api/models", json={"yaml_text": "not: valid: ossie"})
    # viewer can't create models -> 403, and the middleware still logs the line
    assert "POST /api/models -> 403" in _line(caplog)
