"""Seeding behavior: uses its own throwaway DB (not the shared `client`/`client_as`
fixtures' DB from conftest.py), since those intentionally start with zero models -
other tests rely on that to assert exact model counts after their own creates.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from lexis_api.db import Base
from lexis_api.models import SemanticModelRecord, User
from lexis_api.seed import seed_default_users, seed_sample_models

_EXPECTED_MODEL_NAMES = {"tpcds_retail_model", "retail_analytics"}


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


def test_seed_sample_models_skips_if_models_already_exist():
    db = _fresh_session()
    seed_default_users(db)
    db.add(SemanticModelRecord(name="pre-existing", owner_id=1, raw_yaml="version: '0.1.1'\nsemantic_model: []"))
    db.commit()

    seed_sample_models(db)

    assert db.query(SemanticModelRecord).count() == 1
    assert db.query(SemanticModelRecord).first().name == "pre-existing"


def test_seed_default_users_still_idempotent_alongside_sample_models():
    db = _fresh_session()
    seed_default_users(db)
    seed_sample_models(db)
    seed_default_users(db)

    assert db.query(User).count() == 3
