import pandas as pd

from os_institutions import loader
from os_institutions.schema_model import Schema


def test_to_crosswalk_writes_identifier_columns(tmp_path):
    df = pd.DataFrame(
        {
            'ror_id': pd.array(['01kpzv902', None], dtype='string'),
            'grid_id': pd.array(['grid.1014.4', None], dtype='string'),
            'wikidata_id': pd.array(['Q15575', 'Q1'], dtype='string'),
            'unitid': pd.array([None, 123456], dtype='Int64'),
            'name': pd.array(['Flinders University', 'Example College']),
            'url': ['https://flinders.edu.au', 'https://example.edu'],
        }
    )
    parquet = tmp_path / 'institutions.parquet'
    df.to_parquet(parquet)

    out = tmp_path / 'crosswalk.csv'
    loader.to_crosswalk(out, parquet)

    assert out.read_text().splitlines() == [
        'ror_id,grid_id,wikidata_id,unitid,name',
        '01kpzv902,grid.1014.4,Q15575,,Flinders University',
        ',,Q1,123456,Example College',
    ]


def test_crosswalk_columns_are_in_the_schema():
    assert set(loader.CROSSWALK_COLUMNS) <= set(Schema.to_schema().columns)
