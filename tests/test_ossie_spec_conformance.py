"""Validate our Ossie fixtures/vendored types against the real upstream spec.

`third_party/ossie` is a git submodule tracking
https://github.com/apache/ossie - these tests exist so that pulling
in a submodule bump (`git submodule update --remote third_party/ossie`) surfaces any
spec drift here, instead of us silently falling out of sync with upstream.
"""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

OSSIE_SUBMODULE = Path(__file__).parent.parent / "third_party" / "ossie"
SCHEMA_PATH = OSSIE_SUBMODULE / "core-spec" / "ossie-schema.json"

pytestmark = pytest.mark.skipif(
    not SCHEMA_PATH.exists(),
    reason="third_party/ossie submodule not initialized - run `git submodule update --init`",
)


def test_tpcds_fixture_conforms_to_upstream_schema():
    schema = json.loads(SCHEMA_PATH.read_text())
    document = yaml.safe_load(
        (Path(__file__).parent / "fixtures" / "tpcds_semantic_model.yaml").read_text()
    )
    jsonschema.validate(document, schema)


def test_vendored_models_match_submodule_source():
    vendored = Path(__file__).parent.parent / "src" / "semantica" / "_vendor" / "ossie" / "models.py"
    upstream = OSSIE_SUBMODULE / "python" / "src" / "ossie" / "models.py"
    assert vendored.read_text() == upstream.read_text(), (
        "src/semantica/_vendor/ossie/models.py has drifted from the third_party/ossie "
        "submodule - run scripts/sync_ossie_vendor.sh (after `git submodule update "
        "--remote third_party/ossie` if you meant to pick up an upstream change)"
    )
