"""Lexis: Ossie-native semantic layer transpiler."""

from importlib.metadata import PackageNotFoundError, version

try:
    # The installed package's real version - set from the git tag at release time
    # (see .github/workflows/publish.yml), from pyproject.toml otherwise.
    __version__ = version("lexis-cli")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0.dev0"
