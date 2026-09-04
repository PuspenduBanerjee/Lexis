import json

from lexis.transpilers.dbt_ossie import DBT_EMIT_VERSION, emit_dbt_ossie_document


def test_emits_dbt_supported_version_regardless_of_source_version(tpcds_document):
    result = emit_dbt_ossie_document(tpcds_document)
    data = json.loads(result.artifact.content)
    assert data["version"] == DBT_EMIT_VERSION == "0.1.1"


def test_warns_when_source_version_is_not_dbt_supported(tpcds_document):
    assert tpcds_document.version == "0.2.0.dev0"
    result = emit_dbt_ossie_document(tpcds_document)
    assert any("not dbt-supported" in w for w in result.warnings)


def test_artifact_targets_osi_directory_by_default(tpcds_document):
    result = emit_dbt_ossie_document(tpcds_document)
    assert result.artifact.filename.startswith("osi/")


def test_document_shape_preserved_datasets_and_metrics(tpcds_document):
    result = emit_dbt_ossie_document(tpcds_document)
    data = json.loads(result.artifact.content)
    sm = data["semantic_model"][0]
    assert len(sm["datasets"]) == 5
    assert len(sm["metrics"]) == 5
