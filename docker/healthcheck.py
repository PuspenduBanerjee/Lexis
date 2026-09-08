"""Container healthcheck: exit 0 iff the API answers GET /api/health with 200.

Kept as a file rather than an inline `python -c "import ...; ..."` in
docker-compose.yml because Podman flattens a multi-word exec-form healthcheck and
runs it through a shell, which mangles the `-c` script ("SyntaxError: expected one
or more names after 'import'"). A single-token argv (`python <this file>`) is
handled identically by Docker and Podman.
"""

import sys
import urllib.request

URL = "http://localhost:8000/api/health"

try:
    with urllib.request.urlopen(URL, timeout=3) as resp:  # noqa: S310 - fixed localhost URL
        sys.exit(0 if resp.status == 200 else 1)
except Exception:  # noqa: BLE001 - any failure (connrefused, timeout, non-2xx) = unhealthy
    sys.exit(1)
