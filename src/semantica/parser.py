"""Parse and validate OSI YAML/JSON documents into OSIDocument objects."""

from pathlib import Path

import yaml

from semantica._vendor.osi import OSIDocument


def parse_osi_yaml(text: str) -> OSIDocument:
    """Parse OSI YAML source text into a validated OSIDocument."""
    data = yaml.safe_load(text)
    return OSIDocument.model_validate(data)


def load_osi_document(path: str | Path) -> OSIDocument:
    """Load and validate an OSI document from a YAML file on disk."""
    text = Path(path).read_text()
    return parse_osi_yaml(text)
