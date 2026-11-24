import pandas as pd

from os_institutions.sources.ror import apply_hotfixes, is_active, is_education


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


def test_apply_hotfixes_clears_child_grid_id_but_keeps_parent():
    df = pd.DataFrame(
        {
            "id": ["04yr81d29", "02fvjvv74", "03r6hpz93"],
            "grid_id": ["Q123", "grid.445690.a", "grid.445690.a"],
            "wikidata_id": [pd.NA, pd.NA, pd.NA],
        }
    )

    out = apply_hotfixes(df).set_index("id")

    # The child (02fvjvv74) borrowed its parent's GRID ID; only the child's
    # is cleared.
    assert pd.isna(out.loc["02fvjvv74", "grid_id"])
    assert out.loc["03r6hpz93", "grid_id"] == "grid.445690.a"
    # The earlier hotfix still runs on its fixture row.
    assert out.loc["04yr81d29", "wikidata_id"] == "Q123"
    assert pd.isna(out.loc["04yr81d29", "grid_id"])
