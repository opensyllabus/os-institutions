import pandas as pd

from os_institutions.sources.ror import is_active, is_education


def test_is_active():
    df = pd.DataFrame({"status": ["active", "redirected", "obsolete"]})
    assert df[is_active(df)].size == 1


def test_is_education():
    df = pd.DataFrame({"types": [["education"], ["company"], ["healthcare"]]})
    assert df[is_education(df)].size == 1


def test_is_education_mixed():
    df = pd.DataFrame(
        {"types": [["company", "education"], ["company"], ["healthcare"]]}
    )
    assert df[is_education(df)].size == 1
