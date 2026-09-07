"""Idempotent startup seeds: the 3 demo users, and the bundled sample models so a
fresh install has something to look at instead of an empty workspace.
"""

from importlib import resources

from sqlalchemy.orm import Session

from lexis.parser import parse_ossie_yaml
from lexis_api.models import Role, SemanticModelRecord, User

_SAMPLE_MODEL_OWNER_ID = 2  # editor1

#: (sample_data resource filename, owner id) for every model seeded on first boot.
_SAMPLE_MODELS: list[tuple[str, int]] = [
    ("tpcds_semantic_model.yaml", _SAMPLE_MODEL_OWNER_ID),
    ("retail_analytics_model.yaml", _SAMPLE_MODEL_OWNER_ID),
]


def seed_default_users(db: Session) -> None:
    if db.query(User).count() > 0:
        return
    db.add_all(
        [
            User(id=1, username="admin", role=Role.ADMIN),
            User(id=2, username="editor1", role=Role.EDITOR),
            User(id=3, username="viewer1", role=Role.VIEWER),
        ]
    )
    db.commit()


def seed_sample_models(db: Session) -> None:
    if db.query(SemanticModelRecord).count() > 0:
        return
    for filename, owner_id in _SAMPLE_MODELS:
        yaml_text = (resources.files("lexis_api.sample_data") / filename).read_text()
        semantic_model = parse_ossie_yaml(yaml_text).semantic_model[0]
        db.add(
            SemanticModelRecord(
                name=semantic_model.name,
                owner_id=owner_id,
                raw_yaml=yaml_text,
            )
        )
    db.commit()
