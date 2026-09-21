from importlib import resources
from pathlib import Path

import pytest

from lexis.parser import load_ossie_document, parse_ossie_yaml
from lexis.resolved_model import ResolvedModel

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tpcds_document():
    return load_ossie_document(FIXTURES / "tpcds_semantic_model.yaml")


@pytest.fixture
def tpcds_model(tpcds_document):
    return ResolvedModel.build(tpcds_document.semantic_model[0])


@pytest.fixture
def retail_model() -> ResolvedModel:
    """The real bundled `retail_analytics` model (not a test-only fixture copy) -
    two fact tables (fct_store_sales, fct_store_returns) sharing conformed
    dimensions, used for the cross-fact group_by/drill-across tests (tpcds_model
    only has one fact table, so it can't exercise those)."""
    yaml_text = (resources.files("lexis_api.sample_data") / "retail_analytics_model.yaml").read_text()
    return ResolvedModel.build(parse_ossie_yaml(yaml_text).semantic_model[0])


@pytest.fixture
def sml_repo_dir():
    """A small hand-authored SML repo exercising Phase 2's parser: snowflake-free
    dimension attribute flattening, a 2-level hierarchy, a degenerate time
    dimension, a plain metric, a ratio metric_calc, an arbitrary-MDX metric_calc,
    and an unsupported (row_security) object type."""
    return FIXTURES / "sml"
