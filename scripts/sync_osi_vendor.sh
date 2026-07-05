#!/usr/bin/env bash
# Re-vendor src/semantica/_vendor/osi from the third_party/OSI git submodule.
#
# `osi-python` isn't published to PyPI yet, so we vendor `python/src/osi/models.py`
# verbatim (see src/semantica/_vendor/osi/NOTICE.md) instead of depending on it. This
# script copies the submodule's current commit of models.py over the vendored copy and
# regenerates NOTICE.md with that commit's hash, so keeping our OSI model classes in
# sync with the upstream spec is just:
#
#   git submodule update --remote third_party/OSI
#   scripts/sync_osi_vendor.sh
#
# `__init__.py` re-exports models.py's public names but is hand-adapted (relative
# import, own docstring) rather than a verbatim copy, so it's not overwritten here -
# this script just warns if models.py has grown a class/name it doesn't re-export yet.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SUBMODULE_DIR="third_party/OSI"
SRC="$SUBMODULE_DIR/python/src/osi/models.py"
DEST="src/semantica/_vendor/osi/models.py"
INIT="src/semantica/_vendor/osi/__init__.py"

if [[ ! -f "$SRC" ]]; then
  echo "error: $SRC not found - run 'git submodule update --init' first" >&2
  exit 1
fi

COMMIT=$(git -C "$SUBMODULE_DIR" rev-parse HEAD)

cp "$SRC" "$DEST"
echo "Copied $SRC -> $DEST (commit $COMMIT)"

cat > src/semantica/_vendor/osi/NOTICE.md <<EOF
Vendored from https://github.com/open-semantic-interchange/OSI
Path: python/src/osi
Commit: $COMMIT
License: Apache License 2.0 (c) Open Semantic Interchange contributors

This code is vendored (not installed as a dependency) because \`osi-python\`
is not yet published to PyPI as of this writing. Once it is published,
replace this vendored copy with a real \`osi-python\` dependency in
pyproject.toml and delete this directory.

Kept in sync with the \`third_party/OSI\` git submodule - after bumping it
(\`git submodule update --remote third_party/OSI\`), run
\`scripts/sync_osi_vendor.sh\` to re-vendor models.py and refresh this file's
commit pin.
EOF
echo "Updated src/semantica/_vendor/osi/NOTICE.md"

missing=0
while read -r name; do
  [[ -z "$name" ]] && continue
  if ! grep -q "\b${name}\b" "$INIT"; then
    echo "warning: $INIT does not re-export '$name' - update it by hand" >&2
    missing=1
  fi
done < <(grep -oE '^class [A-Za-z_]+' "$SRC" | awk '{print $2}'; grep -oE '^OSI[A-Za-z]+ = ' "$SRC" | sed 's/ =.*//')

if [[ "$missing" -eq 0 ]]; then
  echo "$INIT already re-exports every models.py class/name - no changes needed"
fi
