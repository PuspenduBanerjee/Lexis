"""Seeding behavior: uses its own throwaway DB (not the shared `client`/`client_as`
fixtures' DB from conftest.py), since those intentionally start with zero models -
other tests rely on that to assert exact model counts after their own creates.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from lexis_api import seed as seed_module
from lexis_api.db import Base
from lexis_api.models import Connection, ConnectionType, SemanticModelRecord, User
from lexis_api.seed import seed_default_users, seed_demo_connections, seed_sample_models

_EXPECTED_MODEL_NAMES = {"tpcds_retail_model", "retail_analytics"}
_DEMO_CONNECTION_NAMES = {"tpcds-demo", "retail-demo"}


def _fresh_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_seed_sample_models_creates_the_bundled_models_owned_by_editor():
    db = _fresh_session()
    seed_default_users(db)
    seed_sample_models(db)

    records = db.query(SemanticModelRecord).all()
    assert {r.name for r in records} == _EXPECTED_MODEL_NAMES
    assert all(r.owner.username == "editor1" for r in records)


def test_seed_sample_models_is_idempotent():
    db = _fresh_session()
    seed_default_users(db)
    seed_sample_models(db)
    seed_sample_models(db)

    assert db.query(SemanticModelRecord).count() == len(_EXPECTED_MODEL_NAMES)


def test_seed_sample_models_does_not_add_samples_to_a_non_empty_workspace():
    db = _fresh_session()
    seed_default_users(db)
    db.add(SemanticModelRecord(name="pre-existing", owner_id=1, raw_yaml="version: '0.1.1'\nsemantic_model: []"))
    db.commit()

    seed_sample_models(db)

    assert db.query(SemanticModelRecord).count() == 1
    assert db.query(SemanticModelRecord).first().name == "pre-existing"


def test_seed_sample_models_refreshes_a_stale_bundled_model():
    db = _fresh_session()
    seed_default_users(db)
    seed_sample_models(db)

    # simulate an older packaged version that landed on the volume first
    stale = db.query(SemanticModelRecord).filter_by(name="retail_analytics").one()
    packaged_yaml = stale.raw_yaml
    stale.raw_yaml = packaged_yaml.replace("datatype: Date", "# datatype removed")
    db.commit()

    seed_sample_models(db)

    refreshed = db.query(SemanticModelRecord).filter_by(name="retail_analytics").one()
    assert refreshed.raw_yaml == packaged_yaml
    assert db.query(SemanticModelRecord).count() == len(_EXPECTED_MODEL_NAMES)


def test_seed_sample_models_does_not_resurrect_a_deleted_sample():
    db = _fresh_session()
    seed_default_users(db)
    seed_sample_models(db)
    db.query(SemanticModelRecord).filter_by(name="retail_analytics").delete()
    db.commit()

    seed_sample_models(db)

    names = {r.name for r in db.query(SemanticModelRecord).all()}
    assert names == {"tpcds_retail_model"}


def test_seed_default_users_still_idempotent_alongside_sample_models():
    db = _fresh_session()
    seed_default_users(db)
    seed_sample_models(db)
    seed_default_users(db)

    assert db.query(User).count() == 3


@pytest.fixture()
def demo_setup(monkeypatch, tmp_path):
    """Turn LEXIS_DEV_SETUP_DEMO on and point demo_data_dir at a scratch dir."""
    monkeypatch.setattr(seed_module.settings, "dev_setup_demo", True)
    monkeypatch.setattr(seed_module.settings, "demo_data_dir", str(tmp_path))
    return tmp_path


def test_seed_demo_connections_is_a_noop_when_the_flag_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(seed_module.settings, "dev_setup_demo", False)
    monkeypatch.setattr(seed_module.settings, "demo_data_dir", str(tmp_path))
    db = _fresh_session()
    seed_default_users(db)

    seed_demo_connections(db)

    assert db.query(Connection).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_seed_demo_connections_writes_datasets_and_connections(demo_setup):
    db = _fresh_session()
    seed_default_users(db)

    seed_demo_connections(db)

    conns = db.query(Connection).all()
    assert {c.name for c in conns} == _DEMO_CONNECTION_NAMES
    for c in conns:
        assert c.type is ConnectionType.DUCKDB_FILE
        assert c.owner.username == "editor1"
        path = demo_setup / f"{c.name}.duckdb"
        assert c.config == {"path": str(path)}
        assert path.is_file() and path.stat().st_size > 0


def test_seed_demo_connections_is_idempotent(demo_setup):
    db = _fresh_session()
    seed_default_users(db)

    seed_demo_connections(db)
    mtimes = {p.name: p.stat().st_mtime_ns for p in demo_setup.iterdir()}
    seed_demo_connections(db)

    assert db.query(Connection).count() == len(_DEMO_CONNECTION_NAMES)
    # existing files are left untouched on the second run
    assert {p.name: p.stat().st_mtime_ns for p in demo_setup.iterdir()} == mtimes


def test_seed_demo_connections_reexports_a_missing_file(demo_setup):
    db = _fresh_session()
    seed_default_users(db)
    seed_demo_connections(db)

    (demo_setup / "retail-demo.duckdb").unlink()
    seed_demo_connections(db)

    assert (demo_setup / "retail-demo.duckdb").is_file()
    # the connection row was not duplicated
    assert db.query(Connection).filter_by(name="retail-demo").count() == 1
