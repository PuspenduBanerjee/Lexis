"""Validate our OSI fixtures/vendored types against the real upstream spec.

`third_party/OSI` is a git submodule tracking
https://github.com/open-semantic-interchange/OSI - these tests exist so that pulling
in a submodule bump (`git submodule update --remote third_party/OSI`) surfaces any
spec drift here, instead of us silently falling out of sync with upstream.
"""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

OSI_SUBMODULE = Path(__file__).parent.parent / "third_party" / "OSI"
SCHEMA_PATH = OSI_SUBMODULE / "core-spec" / "osi-schema.json"

pytestmark = pytest.mark.skipif(
    not SCHEMA_PATH.exists(),
    reason="third_party/OSI submodule not initialized - run `git submodule update --init`",
)


def test_tpcds_fixture_conforms_to_upstream_schema():
    schema = json.loads(SCHEMA_PATH.read_text())
    document = yaml.safe_load(
        (Path(__file__).parent / "fixtures" / "tpcds_semantic_model.yaml").read_text()
    )
    jsonschema.validate(document, schema)


def test_vendored_models_match_submodule_source():
    vendored = Path(__file__).parent.parent / "src" / "semantica" / "_vendor" / "osi" / "models.py"
    upstream = OSI_SUBMODULE / "python" / "src" / "osi" / "models.py"
    assert vendored.read_text() == upstream.read_text(), (
        "src/semantica/_vendor/osi/models.py has drifted from the third_party/OSI "
        "submodule - run scripts/sync_osi_vendor.sh (after `git submodule update "
        "--remote third_party/OSI` if you meant to pick up an upstream change)"
    )
