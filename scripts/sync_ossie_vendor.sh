#!/usr/bin/env bash
# Re-vendor src/lexis/_vendor/ossie from the third_party/ossie git submodule.
#
# `apache-ossie` isn't published to PyPI yet, so we vendor `python/src/ossie/models.py`
# verbatim (see src/lexis/_vendor/ossie/NOTICE.md) instead of depending on it. This
# script copies the submodule's current commit of models.py over the vendored copy and
# regenerates NOTICE.md with that commit's hash, so keeping our Ossie model classes in
# sync with the upstream spec is just:
#
#   git submodule update --remote third_party/ossie
#   scripts/sync_ossie_vendor.sh
#
# `__init__.py` re-exports models.py's public names but is hand-adapted (relative
# import, own docstring) rather than a verbatim copy, so it's not overwritten here -
# this script just warns if models.py has grown a class/name it doesn't re-export yet.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SUBMODULE_DIR="third_party/ossie"
SRC="$SUBMODULE_DIR/python/src/ossie/models.py"
DEST="src/lexis/_vendor/ossie/models.py"
INIT="src/lexis/_vendor/ossie/__init__.py"

if [[ ! -f "$SRC" ]]; then
  echo "error: $SRC not found - run 'git submodule update --init' first" >&2
  exit 1
fi

COMMIT=$(git -C "$SUBMODULE_DIR" rev-parse HEAD)

cp "$SRC" "$DEST"
echo "Copied $SRC -> $DEST (commit $COMMIT)"

cat > src/lexis/_vendor/ossie/NOTICE.md <<EOF
Vendored from https://github.com/apache/ossie
Path: python/src/ossie
Commit: $COMMIT
License: Apache License 2.0 (c) The Apache Software Foundation

This code is vendored (not installed as a dependency) because \`apache-ossie\`
is not yet published to PyPI as of this writing. Once it is published,
replace this vendored copy with a real \`apache-ossie\` dependency in
pyproject.toml and delete this directory.

Kept in sync with the \`third_party/ossie\` git submodule - after bumping it
(\`git submodule update --remote third_party/ossie\`), run
\`scripts/sync_ossie_vendor.sh\` to re-vendor models.py and refresh this file's
commit pin.
EOF
echo "Updated src/lexis/_vendor/ossie/NOTICE.md"

missing=0
while read -r name; do
  [[ -z "$name" ]] && continue
  if ! grep -q "\b${name}\b" "$INIT"; then
    echo "warning: $INIT does not re-export '$name' - update it by hand" >&2
    missing=1
  fi
done < <(grep -oE '^class [A-Za-z_]+' "$SRC" | awk '{print $2}'; grep -oE '^Ossie[A-Za-z]+ = ' "$SRC" | sed 's/ =.*//')

if [[ "$missing" -eq 0 ]]; then
  echo "$INIT already re-exports every models.py class/name - no changes needed"
fi
