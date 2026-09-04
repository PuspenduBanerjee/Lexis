from pathlib import Path

import pytest

from lexis.parser import load_ossie_document
from lexis.resolved_model import ResolvedModel

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tpcds_document():
    return load_ossie_document(FIXTURES / "tpcds_semantic_model.yaml")


@pytest.fixture
def tpcds_model(tpcds_document):
    return ResolvedModel.build(tpcds_document.semantic_model[0])
