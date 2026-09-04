Vendored from https://github.com/apache/ossie
Path: python/src/ossie
Commit: ddb19f1b135a61c65603f4823a3526e2fab00cf1
License: Apache License 2.0 (c) The Apache Software Foundation

This code is vendored (not installed as a dependency) because `apache-ossie`
is not yet published to PyPI as of this writing. Once it is published,
replace this vendored copy with a real `apache-ossie` dependency in
pyproject.toml and delete this directory.

Kept in sync with the `third_party/ossie` git submodule - after bumping it
(`git submodule update --remote third_party/ossie`), run
`scripts/sync_ossie_vendor.sh` to re-vendor models.py and refresh this file's
commit pin.
