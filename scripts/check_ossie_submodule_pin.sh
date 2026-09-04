#!/usr/bin/env bash
# Verify the third_party/ossie submodule points at a commit that actually exists on
# its upstream remote (i.e. some commit reachable from a remote branch), not a
# local-only commit made by accidentally `cd`-ing into the submodule and committing
# there. We don't own that repo, so a superproject commit pinning it to a SHA nobody
# else can fetch would silently break `git submodule update` for every other clone.
#
# Shared by:
#   .githooks/pre-commit               - fast local check, only when the pin changed
#   .github/workflows/check-ossie-submodule.yml - CI backstop, checked on every push/PR
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# When this script runs from a git hook, git has already exported GIT_DIR/
# GIT_INDEX_FILE/etc as paths relative to the superproject root. Any `git -C
# third_party/ossie ...` below would re-resolve those relative paths against the
# submodule's directory instead - and since third_party/ossie/.git is a gitlink
# *file*, not a directory, that blows up with a confusing
# "index file open failed: Not a directory" instead of running the intended
# command. Unset them so each `git -C ...` call below resolves its own repo state.
unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE GIT_PREFIX GIT_OBJECT_DIRECTORY \
  GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true

SUBMODULE_DIR="third_party/ossie"

if [[ ! -e "$SUBMODULE_DIR/.git" ]]; then
  echo "warning: $SUBMODULE_DIR not initialized (git submodule update --init) - skipping pin check" >&2
  exit 0
fi

PINNED_SHA=$(git ls-files -s "$SUBMODULE_DIR" | awk '{print $2}')
if [[ -z "$PINNED_SHA" ]]; then
  echo "error: could not read $SUBMODULE_DIR's gitlink entry from the index" >&2
  exit 1
fi

git -C "$SUBMODULE_DIR" fetch --quiet origin

if git -C "$SUBMODULE_DIR" branch -r --contains "$PINNED_SHA" 2>/dev/null | grep -q .; then
  echo "OK: $SUBMODULE_DIR is pinned to $PINNED_SHA, reachable from upstream origin"
  exit 0
fi

cat >&2 <<EOF
error: $SUBMODULE_DIR is pinned to $PINNED_SHA, which is NOT reachable from any
       remote branch of https://github.com/apache/ossie.

This usually means someone ran 'git commit' *inside* third_party/ossie (creating a
local-only commit) and then 'git add third_party/ossie' in the superproject picked up
that commit's SHA. We don't have push access to that repo, so this pin would be
unreachable for anyone else who clones this repo.

Fix: reset the submodule to a real upstream commit, e.g.
  git -C $SUBMODULE_DIR checkout main
  git -C $SUBMODULE_DIR pull
  git add $SUBMODULE_DIR
or, to go back to whatever this branch currently has recorded:
  git submodule update $SUBMODULE_DIR
EOF
exit 1
