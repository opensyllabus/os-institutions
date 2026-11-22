import io
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import requests
import yaml
from loguru import logger


def write_parquet(df, path):
    """Write a stage output, creating its directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    logger.info(f'Wrote {len(df)} rows to {path}')


def read_yaml(path: str, columns=None, dtype=None, pandas=True):
    """Convert a YAML string to pandas object."""
    with open(path) as fh:
        data = yaml.safe_load(fh)

        if not pandas:
            return data

        df = pd.DataFrame(data.items(), columns=columns)

        if dtype:
            df = df.astype(dtype)

        return df


def download_zip_file(file_url):
    logger.info(f'Downloading {file_url}')
    resp = requests.get(file_url)

    zip_file = ZipFile(io.BytesIO(resp.content))
    logger.info(zip_file.namelist())

    return zip_file
