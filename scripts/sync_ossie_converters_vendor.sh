#!/usr/bin/env bash
# Re-vendor the "ported" converters listed in scripts/ossie_converters_manifest.json
# from the third_party/ossie git submodule into src/lexis/_vendor/ossie_converters/.
#
# Same rationale as sync_ossie_vendor.sh (see that script's header): none of
# apache/ossie's converter packages are published to PyPI yet, so we vendor each
# "ported" one's source verbatim instead of depending on it. Keeping them in sync
# with upstream is:
#
#   git submodule update --remote third_party/ossie
#   scripts/sync_ossie_converters_vendor.sh
#
# One deviation from a byte-for-byte copy: several converters (e.g. ossie_dbt,
# ossie_sigma, ossie_wisdom) do `from ossie import ...` / `from ossie.X import
# ...`, expecting the real `apache-ossie` package to be installed. Since Lexis
# vendors that package under `lexis._vendor.ossie` instead (see
# src/lexis/_vendor/ossie/__init__.py), this script rewrites those imports to
# point there. `ossie_<name>` imports (a converter's own package, or another
# converter's) are left untouched - only the bare `ossie` package name is
# rewritten. tests/test_ossie_spec_conformance.py checks vendored output against
# the submodule source with this same rewrite applied, so drift still fails loudly.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

MANIFEST="scripts/ossie_converters_manifest.json"
CONVERTERS_DIR="third_party/ossie/converters"
VENDOR_DIR="src/lexis/_vendor/ossie_converters"

if [[ ! -d "$CONVERTERS_DIR" ]]; then
  echo "error: $CONVERTERS_DIR not found - run 'git submodule update --init' first" >&2
  exit 1
fi

python3 - "$MANIFEST" "$CONVERTERS_DIR" "$VENDOR_DIR" <<'PYEOF'
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

manifest_path, converters_dir, vendor_dir = (Path(p) for p in sys.argv[1:4])
manifest = json.loads(manifest_path.read_text())["converters"]

# Only rewrite `ossie` the bare top-level package - never `ossie_<anything>`.
_OSSIE_IMPORT_RE = re.compile(r"^(from|import) ossie\b(?!_)", re.MULTILINE)


def rewrite(text: str) -> str:
    def repl(m: re.Match) -> str:
        return f"{m.group(1)} lexis._vendor.ossie"

    return _OSSIE_IMPORT_RE.sub(repl, text)


vendor_dir.mkdir(parents=True, exist_ok=True)
notice_lines = [
    "Vendored converter packages from https://github.com/apache/ossie (converters/*)",
    "License: Apache License 2.0 (c) The Apache Software Foundation",
    "",
    "Vendored (not installed as dependencies) because none of these are published to",
    "PyPI yet. Each package's `from ossie import ...` / `from ossie.X import ...` is",
    "rewritten to `from lexis._vendor.ossie import ...` on vendor (see this script's",
    "header) - everything else is copied verbatim.",
    "",
    "Kept in sync with the `third_party/ossie` git submodule - after bumping it",
    "(`git submodule update --remote third_party/ossie`), run",
    "`scripts/sync_ossie_converters_vendor.sh` to re-vendor and refresh this file's",
    "commit pins.",
    "",
]

submodule_commit = subprocess.run(
    ["git", "-C", "third_party/ossie", "rev-parse", "HEAD"],
    capture_output=True, text=True, check=True,
).stdout.strip()

ported = {name: info for name, info in manifest.items() if info["status"] == "ported"}
if not ported:
    print("no converters marked status=ported in the manifest - nothing to vendor")
else:
    for name in sorted(ported):
        info = ported[name]
        if info["language"] != "python":
            print(f"warning: {name!r} is status=ported but language={info['language']!r}, not 'python' - skipping (this script only vendors Python source)", file=sys.stderr)
            continue
        package = info["package"]
        src_pkg_dir = converters_dir / name / "src" / package
        if not src_pkg_dir.is_dir():
            print(f"error: {src_pkg_dir} not found for converter {name!r}", file=sys.stderr)
            sys.exit(1)

        dest_pkg_dir = vendor_dir / package
        if dest_pkg_dir.exists():
            shutil.rmtree(dest_pkg_dir)
        shutil.copytree(
            src_pkg_dir, dest_pkg_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

        rewritten = 0
        for py_file in dest_pkg_dir.rglob("*.py"):
            original = py_file.read_text()
            updated = rewrite(original)
            if updated != original:
                py_file.write_text(updated)
                rewritten += 1

        print(f"Copied {src_pkg_dir} -> {dest_pkg_dir} (commit {submodule_commit}, rewrote imports in {rewritten} file(s))")
        notice_lines.append(f"- {package} (from converters/{name}) - commit {submodule_commit}")

(vendor_dir / "NOTICE.md").write_text("\n".join(notice_lines) + "\n")
print(f"Updated {vendor_dir / 'NOTICE.md'}")
PYEOF
