"""Exercise the actual Alembic path against a fresh temp SQLite file.

The rest of the API test suite intentionally uses Base.metadata.create_all (see
conftest.py) for speed/isolation, so this is the one place that actually proves
`alembic upgrade head` itself works and produces the expected schema.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def test_alembic_upgrade_head_creates_expected_tables(tmp_path):
    db_path = tmp_path / "migration_test.db"
    env = {**os.environ, "LEXIS_DATABASE_URL": f"sqlite:///{db_path}"}

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    con = sqlite3.connect(db_path)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"users", "semantic_models", "alembic_version"} <= tables
