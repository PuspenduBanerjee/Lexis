"""Test setup for the API: a throwaway SQLite file (env var set before any
`lexis_api` import so `config.settings`/`db.engine` point at it), reset to a
fresh, freshly-seeded schema before every test for full isolation.
"""

import os
import tempfile

import pytest

_tmp_fd, _tmp_path = tempfile.mkstemp(suffix=".db")
os.close(_tmp_fd)
os.environ["LEXIS_DATABASE_URL"] = f"sqlite:///{_tmp_path}"

from fastapi.testclient import TestClient  # noqa: E402

from lexis_api.db import Base, SessionLocal, engine  # noqa: E402
from lexis_api.main import app  # noqa: E402
from lexis_api.seed import seed_default_users  # noqa: E402

ROLE_TO_ID = {"admin": 1, "editor": 2, "viewer": 3}


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_default_users(db)
    finally:
        db.close()
    yield


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def client_as(client: TestClient):
    def _make(role: str) -> TestClient:
        client.headers.update({"X-Account-Id": str(ROLE_TO_ID[role])})
        return client

    return _make


@pytest.fixture()
def tpcds_yaml() -> str:
    from pathlib import Path

    return (Path(__file__).parent.parent / "fixtures" / "tpcds_semantic_model.yaml").read_text()
