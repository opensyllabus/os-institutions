"""Load the institutions dataset and check it against its schema.

This is the only dataset code the library needs, so it stays free of the
pipeline dependencies (typer, loguru, ...); the CLI imports typer lazily.
"""

import logging
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import DataFrame

from os_institutions.paths import artifact_path
from os_institutions.schema_model import Schema

logger = logging.getLogger(__name__)

STAGE = 'dataset'


def read(path: Path | None = None):
    path = path or artifact_path(STAGE)
    logger.info(f'Loading {path}')
    return pd.read_parquet(path)


@pa.check_types
def load(path: Path | None = None) -> DataFrame[Schema]:
    return read(path)


def to_csv(path: Path, input: Path | None = None):
    df = read(input)
    df.to_csv(path)
    logger.info(f'Wrote {len(df)} rows to {path}')


def check(input: Path | None = None):
    df = read(input)
    df.info()
    Schema(df)


if __name__ == '__main__':
    import typer

    logging.basicConfig(level=logging.INFO)
    app = typer.Typer()

    @app.command()
    def csv(
        path: Path,
        input: Path | None = typer.Option(None, help='Parquet to read.'),
    ):
        to_csv(path, input)

    @app.command(name='check')
    def check_command(
        input: Path | None = typer.Option(None, help='Parquet to read.'),
    ):
        check(input)

    app()
