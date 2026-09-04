"""Shared types for Semantica transpilers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    """A single emitted output file: a name and its text content."""

    filename: str
    content: str
