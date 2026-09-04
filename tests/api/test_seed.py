"""Seeding behavior: uses its own throwaway DB (not the shared `client`/`client_as`
fixtures' DB from conftest.py), since those intentionally start with zero models -
other tests rely on that to assert exact model counts after their own creates.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from lexis_api.db import Base
from lexis_api.models import SemanticModelRecord, User
from lexis_api.seed import seed_default_users, seed_sample_model


def _fresh_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_seed_sample_model_creates_one_model_owned_by_editor():
    db = _fresh_session()
    seed_default_users(db)
    seed_sample_model(db)

    records = db.query(SemanticModelRecord).all()
    assert len(records) == 1
    assert records[0].name == "tpcds_retail_model"
    assert records[0].owner.username == "editor1"


def test_seed_sample_model_is_idempotent():
    db = _fresh_session()
    seed_default_users(db)
    seed_sample_model(db)
    seed_sample_model(db)

    assert db.query(SemanticModelRecord).count() == 1


def test_seed_sample_model_skips_if_models_already_exist():
    db = _fresh_session()
    seed_default_users(db)
    db.add(SemanticModelRecord(name="pre-existing", owner_id=1, raw_yaml="version: '0.1.1'\nsemantic_model: []"))
    db.commit()

    seed_sample_model(db)

    assert db.query(SemanticModelRecord).count() == 1
    assert db.query(SemanticModelRecord).first().name == "pre-existing"


def test_seed_default_users_still_idempotent_alongside_sample_model():
    db = _fresh_session()
    seed_default_users(db)
    seed_sample_model(db)
    seed_default_users(db)

    assert db.query(User).count() == 3
