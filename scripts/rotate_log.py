#!/usr/bin/env python3
"""Pipe a subprocess's combined stdout/stderr through a size-capped log file.

Usage: cmd | rotate_log.py path/to/log.log [max_bytes]

Uses the standard library's RotatingFileHandler (rename-and-start-fresh, one
backup kept) rather than a hand-rolled front-truncation scheme - well-tested,
no new dependency. Exists because an unbounded `> log_file` redirect (what
scripts/dev.sh used before this) lets a runaway subprocess (e.g. a proxy
logging a full traceback per failed request in a tight retry loop) fill the
disk with no limit - see git history for the incident that prompted this.
"""

import logging.handlers
import sys

DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB


def main() -> None:
    path = sys.argv[1]
    max_bytes = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MAX_BYTES

    handler = logging.handlers.RotatingFileHandler(path, maxBytes=max_bytes, backupCount=1)
    # Millisecond precision so a tight retry loop (many lines within the same
    # second) is visibly distinguishable from ordinary, spaced-out activity like
    # manual page reloads - that distinction is the whole reason this exists.
    handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S"))
    logger = logging.getLogger("rotate_log")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    for line in sys.stdin:
        logger.info(line.rstrip("\n"))


if __name__ == "__main__":
    main()
