Vendored from https://github.com/open-semantic-interchange/OSI
Path: python/src/osi
Commit: 056b5aadc555c0af123af26720324e940a7ee92d
License: Apache License 2.0 (c) Open Semantic Interchange contributors

This code is vendored (not installed as a dependency) because `osi-python`
is not yet published to PyPI as of this writing. Once it is published,
replace this vendored copy with a real `osi-python` dependency in
pyproject.toml and delete this directory.

Kept in sync with the `third_party/OSI` git submodule - after bumping it
(`git submodule update --remote third_party/OSI`), run
`scripts/sync_osi_vendor.sh` to re-vendor models.py and refresh this file's
commit pin.
