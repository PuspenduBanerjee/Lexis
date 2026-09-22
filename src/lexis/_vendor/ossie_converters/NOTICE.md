Vendored converter packages from https://github.com/apache/ossie (converters/*)
License: Apache License 2.0 (c) The Apache Software Foundation

Vendored (not installed as dependencies) because none of these are published to
PyPI yet. Each package's `from ossie import ...` / `from ossie.X import ...` is
rewritten to `from lexis._vendor.ossie import ...` on vendor (see this script's
header) - everything else is copied verbatim.

Kept in sync with the `third_party/ossie` git submodule - after bumping it
(`git submodule update --remote third_party/ossie`), run
`scripts/sync_ossie_converters_vendor.sh` to re-vendor and refresh this file's
commit pins.

- ossie_snowflake (from converters/snowflake) - commit 6d37d7b61183f6405e3a4e65ec883b10ebe0ce2c
