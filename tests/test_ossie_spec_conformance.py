"""Validate our Ossie fixtures/vendored types against the real upstream spec.

`third_party/ossie` is a git submodule tracking
https://github.com/apache/ossie - these tests exist so that pulling
in a submodule bump (`git submodule update --remote third_party/ossie`) surfaces any
spec drift here, instead of us silently falling out of sync with upstream.
"""

import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
OSSIE_SUBMODULE = REPO_ROOT / "third_party" / "ossie"
SCHEMA_PATH = OSSIE_SUBMODULE / "core-spec" / "ossie-schema.json"
CONVERTERS_DIR = OSSIE_SUBMODULE / "converters"
CONVERTERS_MANIFEST_PATH = REPO_ROOT / "scripts" / "ossie_converters_manifest.json"
VENDORED_CONVERTERS_DIR = REPO_ROOT / "src" / "lexis" / "_vendor" / "ossie_converters"

pytestmark = pytest.mark.skipif(
    not SCHEMA_PATH.exists(),
    reason="third_party/ossie submodule not initialized - run `git submodule update --init`",
)

# Must match the rewrite scripts/sync_ossie_converters_vendor.sh applies when
# vendoring: only the bare top-level `ossie` package is rewritten, never a
# converter's own `ossie_<name>` package.
_OSSIE_IMPORT_RE = re.compile(r"^(from|import) ossie\b(?!_)", re.MULTILINE)


def _rewrite_ossie_imports(text: str) -> str:
    return _OSSIE_IMPORT_RE.sub(lambda m: f"{m.group(1)} lexis._vendor.ossie", text)


def test_tpcds_fixture_conforms_to_upstream_schema():
    schema = json.loads(SCHEMA_PATH.read_text())
    document = yaml.safe_load(
        (Path(__file__).parent / "fixtures" / "tpcds_semantic_model.yaml").read_text()
    )
    jsonschema.validate(document, schema)


def test_bundled_retail_analytics_model_conforms_to_upstream_schema():
    from importlib import resources

    schema = json.loads(SCHEMA_PATH.read_text())
    document = yaml.safe_load(
        (resources.files("lexis_api.sample_data") / "retail_analytics_model.yaml").read_text()
    )
    jsonschema.validate(document, schema)


def test_vendored_models_match_submodule_source():
    vendored = Path(__file__).parent.parent / "src" / "lexis" / "_vendor" / "ossie" / "models.py"
    upstream = OSSIE_SUBMODULE / "python" / "src" / "ossie" / "models.py"
    assert vendored.read_text() == upstream.read_text(), (
        "src/lexis/_vendor/ossie/models.py has drifted from the third_party/ossie "
        "submodule - run scripts/sync_ossie_vendor.sh (after `git submodule update "
        "--remote third_party/ossie` if you meant to pick up an upstream change)"
    )


def test_converter_directory_set_matches_manifest():
    """Every third_party/ossie/converters/<name> directory must have an entry in
    scripts/ossie_converters_manifest.json, and vice versa. This is the trip wire
    for 'upstream added/removed/renamed a converter' on a submodule bump - update
    the manifest (and, for a new converter, port it - see
    scripts/sync_ossie_converters_vendor.sh's docstring for the pattern)."""
    manifest = json.loads(CONVERTERS_MANIFEST_PATH.read_text())["converters"]
    actual = {p.name for p in CONVERTERS_DIR.iterdir() if p.is_dir()}
    assert actual == set(manifest), (
        "third_party/ossie/converters/ has drifted from scripts/ossie_converters_manifest.json:\n"
        f"  new upstream, not yet in the manifest: {sorted(actual - set(manifest))}\n"
        f"  in the manifest but no longer upstream: {sorted(set(manifest) - actual)}"
    )


def test_ported_converters_match_submodule_source():
    """Every manifest entry with status "ported" must have a vendored copy that
    matches its submodule source exactly, modulo the `from ossie import` ->
    `from lexis._vendor.ossie import` rewrite scripts/sync_ossie_converters_vendor.sh
    applies when vendoring (see that script's docstring)."""
    manifest = json.loads(CONVERTERS_MANIFEST_PATH.read_text())["converters"]
    ported = {name: info for name, info in manifest.items() if info["status"] == "ported"}
    for name, info in sorted(ported.items()):
        assert info["language"] == "python", (
            f"converter {name!r} is status=ported but language={info['language']!r} - "
            "only python converters can be vendored source-verbatim"
        )
        package = info["package"]
        src_dir = CONVERTERS_DIR / name / "src" / package
        dest_dir = VENDORED_CONVERTERS_DIR / package
        assert dest_dir.is_dir(), (
            f"{dest_dir} is missing - run scripts/sync_ossie_converters_vendor.sh"
        )

        src_files = {p.relative_to(src_dir) for p in src_dir.rglob("*.py")}
        dest_files = {p.relative_to(dest_dir) for p in dest_dir.rglob("*.py")}
        assert src_files == dest_files, (
            f"vendored file set for {package!r} doesn't match converters/{name}/src/{package} "
            "- run scripts/sync_ossie_converters_vendor.sh"
        )

        for rel in sorted(src_files):
            expected = _rewrite_ossie_imports((src_dir / rel).read_text())
            actual = (dest_dir / rel).read_text()
            assert actual == expected, (
                f"src/lexis/_vendor/ossie_converters/{package}/{rel} has drifted from "
                f"third_party/ossie/converters/{name}/src/{package}/{rel} - run "
                "scripts/sync_ossie_converters_vendor.sh (after `git submodule update "
                "--remote third_party/ossie` if you meant to pick up an upstream change)"
            )
