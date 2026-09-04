"""Parse and validate Ossie YAML/JSON documents into OssieDocument objects."""

from pathlib import Path

import yaml

from semantica._vendor.ossie import OssieDocument


def parse_ossie_yaml(text: str) -> OssieDocument:
    """Parse Ossie YAML source text into a validated OssieDocument."""
    data = yaml.safe_load(text)
    return OssieDocument.model_validate(data)


def load_ossie_document(path: str | Path) -> OssieDocument:
    """Load and validate an Ossie document from a YAML file on disk."""
    text = Path(path).read_text()
    return parse_ossie_yaml(text)
