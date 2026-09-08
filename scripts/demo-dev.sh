#!/usr/bin/env bash
# Thin wrapper around scripts/dev.sh for demoing Lexis: turns on the single-port
# UI proxy (LEXIS_DEV_UI_PROXY=1 - the backend also serves the built UI, so one
# tunnelled port exposes everything) and the demo setup (LEXIS_DEV_SETUP_DEMO=1 -
# startup writes the bundled demo datasets and registers a duckdb_file connection
# for each, so the MCP endpoint / Run tab work with no manual curl).
#
# All arguments and any other LEXIS_* overrides pass straight through, e.g.
#   ./scripts/demo-dev.sh start
#   LEXIS_DEMO_DATA_DIR=/srv/lexis-demo ./scripts/demo-dev.sh restart
set -euo pipefail

# Guard against `source scripts/demo-dev.sh` - sourcing would leak the exports
# below into the interactive shell. `return` only succeeds in a sourced context.
(return 0 2>/dev/null) && { echo "error: run this script, don't source it (e.g. ./scripts/demo-dev.sh start)" >&2; return 1; }

export LEXIS_DEV_UI_PROXY=1
export LEXIS_DEV_SETUP_DEMO=1

exec "$(dirname "${BASH_SOURCE[0]}")/dev.sh" "$@"
