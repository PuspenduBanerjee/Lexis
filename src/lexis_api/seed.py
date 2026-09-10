"""Idempotent startup seeds: the 3 demo users, and the bundled sample models so a
fresh install has something to look at instead of an empty workspace.
"""

import logging
from importlib import resources
from pathlib import Path

from sqlalchemy.orm import Session

from lexis.parser import parse_ossie_yaml
from lexis_api.config import settings
from lexis_api.models import Connection, ConnectionType, Role, SemanticModelRecord, User

_log = logging.getLogger("lexis_api")

_SAMPLE_MODEL_OWNER_ID = 2  # editor1

#: (sample_data resource filename, owner id) for every model seeded on first boot.
_SAMPLE_MODELS: list[tuple[str, int]] = [
    ("tpcds_semantic_model.yaml", _SAMPLE_MODEL_OWNER_ID),
    ("retail_analytics_model.yaml", _SAMPLE_MODEL_OWNER_ID),
]

#: (connection name, demo dataset key, .duckdb filename) for the dev-only demo
#: connections seeded when LEXIS_DEV_SETUP_DEMO is set. Names/filenames match the
#: manual-setup examples in the README.
_DEMO_CONNECTIONS: list[tuple[str, str, str]] = [
    ("tpcds-demo", "tpcds", "tpcds-demo.duckdb"),
    ("retail-demo", "retail", "retail-demo.duckdb"),
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
    """Seed the bundled sample models on a fresh install, and on every boot keep any
    that are still present in sync with the packaged YAML - so a redeploy picks up
    model changes (new fields, `datatype` annotations, `ai_context` fixes) instead
    of serving whatever version first landed on the volume.

    A sample that was deleted stays deleted (we only *add* on a fresh install). The
    bundled models are package-managed: to customise one, create a copy
    (`POST /api/models`) rather than editing it in place - an in-place edit is
    overwritten on the next restart.
    """
    existing = {r.name: r for r in db.query(SemanticModelRecord).all()}
    fresh_install = not existing

    for filename, owner_id in _SAMPLE_MODELS:
        yaml_text = (resources.files("lexis_api.sample_data") / filename).read_text()
        name = parse_ossie_yaml(yaml_text).semantic_model[0].name
        row = existing.get(name)
        if row is None:
            if fresh_install:
                db.add(SemanticModelRecord(name=name, owner_id=owner_id, raw_yaml=yaml_text))
        elif row.raw_yaml != yaml_text:
            row.raw_yaml = yaml_text
            _log.info("seed: refreshed bundled sample model %r to the packaged version", name)

    db.commit()


def seed_demo_connections(db: Session) -> None:
    """Dev-only (LEXIS_DEV_SETUP_DEMO=1): write the bundled demo datasets to real
    .duckdb files under ``settings.demo_data_dir`` and register a ``duckdb_file``
    connection for each, so the MCP endpoint / Run tab work without the manual
    ``curl`` in the README. No-op unless the flag is set.

    Idempotent per item: a dataset file is (re)written only when missing or empty,
    and a connection row is added only when no connection of that name exists - so
    it self-heals after a reboot wipes ``/tmp`` without disturbing anything the
    developer changed by hand.
    """
    if not settings.dev_setup_demo:
        return

    from lexis.demo_data import export_demo_dataset
    from lexis.retail_demo_data import export_retail_demo_dataset

    exporters = {"tpcds": export_demo_dataset, "retail": export_retail_demo_dataset}
    data_dir = Path(settings.demo_data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    for conn_name, dataset, filename in _DEMO_CONNECTIONS:
        path = data_dir / filename
        if not path.is_file() or path.stat().st_size == 0:
            exporters[dataset](path, overwrite=True)

        if db.query(Connection).filter_by(name=conn_name).first() is None:
            db.add(
                Connection(
                    name=conn_name,
                    type=ConnectionType.DUCKDB_FILE,
                    owner_id=_SAMPLE_MODEL_OWNER_ID,
                    config={"path": str(path)},
                )
            )
    db.commit()
