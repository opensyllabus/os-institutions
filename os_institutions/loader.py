"""Load the institutions dataset and check it against its schema.

This is the only dataset code the library needs, so it stays free of the
pipeline dependencies (typer, loguru, ...).
"""

import logging
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import DataFrame, Object, Series

from os_institutions.paths import artifact_path
from os_institutions.schema_model import Dataset

logger = logging.getLogger(__name__)

STAGE = 'dataset'


class Schema(Dataset):
    # _id cannot be used w/ Pandera
    ror_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    grid_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikidata_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    unitid: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    city: Series[pd.StringDtype]
    name: Series[pd.StringDtype]
    lat: Series[pd.Float64Dtype] = pa.Field(nullable=True)
    lng: Series[pd.Float64Dtype] = pa.Field(nullable=True)
    url: Series[pd.StringDtype] = pa.Field(nullable=True)
    country_code: Series[pd.StringDtype]
    country: Series[pd.StringDtype]
    state_code: Series[pd.StringDtype] = pa.Field(nullable=True)
    state: Series[pd.StringDtype] = pa.Field(nullable=True)
    enrollment: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    two_year: Series[pd.BooleanDtype] = pa.Field(nullable=True)
    four_year: Series[pd.BooleanDtype] = pa.Field(nullable=True)
    graduate: Series[pd.BooleanDtype] = pa.Field(nullable=True)
    research: Series[pd.BooleanDtype] = pa.Field(nullable=True)
    wikipedia_url: Series[pd.StringDtype] = pa.Field(nullable=True)
    description: Series[pd.StringDtype] = pa.Field(nullable=True)
    image_url: Series[pd.StringDtype] = pa.Field(nullable=True)
    names: Series[Object]
    urls: Series[Object]


def read(path: Path | None = None):
    path = path or artifact_path(STAGE)
    logger.info(f'Loading {path}')
    return pd.read_parquet(path)


@pa.check_types
def load(path: Path | None = None) -> DataFrame[Schema]:
    return read(path)
