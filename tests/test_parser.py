from lexis._vendor.ossie import OssieDocument


def test_parses_tpcds_fixture_into_ossie_document(tpcds_document):
    assert isinstance(tpcds_document, OssieDocument)

    sm = tpcds_document
    assert sm.name == "tpcds_retail_model"
    assert len(sm.datasets) == 5
    assert len(sm.relationships) == 4
    assert len(sm.metrics) == 5


def test_dataset_names_match_fixture(tpcds_document):
    sm = tpcds_document
    names = {d.name for d in sm.datasets}
    assert names == {"store_sales", "date_dim", "customer", "item", "store"}
