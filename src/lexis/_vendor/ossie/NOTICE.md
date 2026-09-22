Vendored from https://github.com/apache/ossie
Path: python/src/ossie
Commit: 6d37d7b61183f6405e3a4e65ec883b10ebe0ce2c
License: Apache License 2.0 (c) The Apache Software Foundation

This code is vendored (not installed as a dependency) because `apache-ossie`
is not yet published to PyPI as of this writing. Once it is published,
replace this vendored copy with a real `apache-ossie` dependency in
pyproject.toml and delete this directory.

Kept in sync with the `third_party/ossie` git submodule - after bumping it
(`git submodule update --remote third_party/ossie`), run
`scripts/sync_ossie_vendor.sh` to re-vendor models.py and refresh this file's
commit pin.
