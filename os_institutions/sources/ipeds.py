from pathlib import Path

import pandas as pd
import pandera as pa
import typer
import wandb
from loguru import logger
from pandera.typing import DataFrame, Object, Series

from os_institutions.normalizer.uri import repair_scheme
from os_institutions.schema_model import IPEDS
from os_institutions.utils import (
    download_zip_file,
    log_info,
    wandb_artifact,
    wandb_init,
)

ARTIFACT = 'opensyllabus/institutions/ipeds:latest'

app = typer.Typer()


class Schema(IPEDS):
    ipeds_unitid: Series[pd.Int64Dtype] = pa.Field(unique=True)
    ipeds_instnm: Series[pd.StringDtype]
    ipeds_ialias: Series[Object] = pa.Field(nullable=True)
    ipeds_city: Series[pd.StringDtype]
    ipeds_stabbr: Series[pd.StringDtype]
    ipeds_webaddr: Series[pd.StringDtype] = pa.Field(nullable=True)
    ipeds_control: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    ipeds_hbcu: Series[pd.BooleanDtype]
    ipeds_tribal: Series[pd.BooleanDtype]
    ipeds_c21basic: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    ipeds_longitud: Series[pd.Float64Dtype]
    ipeds_latitude: Series[pd.Float64Dtype]
    ipeds_effylev: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    ipeds_efytotlt: Series[pd.Int64Dtype] = pa.Field(nullable=True)


def read(name=ARTIFACT, use_artifact=False):
    logger.info(f'Loading {name}')
    return pd.read_parquet(wandb_artifact(name, use_artifact))


@pa.check_types
def load() -> DataFrame[Schema]:
    return read(use_artifact=True)


@app.command()
def csv(path: Path):
    df = read()
    df.to_csv(path)
    logger.info(f'Wrote {len(df)} rows to {path}')


@app.command()
def check():
    df = read()
    df.info()
    Schema(df)


@app.command()
def build():
    """IPEDS provides multiple CSV files for different data files.
    Therefore, they are loaded separately and merged on UNITID.
    """
    # There might be multiple rows representing the same school in IPEDS
    # because of EFFY data, which is broken out into rows by level:
    # '4' for EFFY data on graduate students, '2' for EFFY data
    # on undergraduate students, '1' for total students.  Since total
    # students is what we're interested in, filter for that, also allowing
    # null values.
    wandb_init(group='ipeds')

    hd = get_hd()
    effy = get_effy()

    df = pd.merge(hd, effy, how='left', on='UNITID')
    df = df[
        [
            'UNITID',
            # HD
            'INSTNM',  # Institution (entity) name
            'IALIAS',  # Alias (acronyms, alternative names)
            'CITY',  # City location of institution
            'STABBR',  # State abbreviation
            'WEBADDR',  # Institution's internet website address
            'CONTROL',  # Control of institution
            'HBCU',  # Historically Black College or University
            'TRIBAL',  # Tribal college
            'C21BASIC',  # Carnegie 2021: Basic
            'LONGITUD',  # Longitude
            'LATITUDE',  # Latitude
            # EFFY
            'EFFYLEV',  # Level of student
            'EFYTOTLT',  # Grand total
        ]
    ]

    # IPEDS encodes 1 as True and 2 as False.
    # Sadly, df.astype(bool) can't be used here.
    df['HBCU'] = df['HBCU'] == 1
    df['TRIBAL'] = df['TRIBAL'] == 1
    df['IALIAS'] = df['IALIAS'].apply(parse_alias)
    df['UNITID'] = df['UNITID']
    df['WEBADDR'] = df['WEBADDR'].apply(
        lambda x: repair_scheme(x) if pd.notna(x) else pd.NA
    )

    df.columns = df.columns.str.lower()
    df = df.add_prefix('ipeds_')
    df = df.convert_dtypes()

    log_info(df)

    artifact = wandb.Artifact('ipeds', type='dataset')
    with artifact.new_file('ipeds.parquet', 'wb') as fh:
        df.to_parquet(fh)
    wandb.log_artifact(artifact)


def get_hd():
    file_url = 'https://nces.ed.gov/ipeds/datacenter/data/HD2024.zip'
    zip_file = download_zip_file(file_url)
    file_name = zip_file.namelist()[0]

    na_values = {
        'WEBADDR': ' ',
        'IALIAS': ' ',
        'CONTROL': -3,
        'C21BASIC': -2,
    }

    df = pd.read_csv(
        zip_file.open(file_name), encoding='utf-8', na_values=na_values
    )
    return df.convert_dtypes()


def get_effy():
    file_url = 'https://nces.ed.gov/ipeds/datacenter/data/EFFY2024.zip'
    zip_file = download_zip_file(file_url)
    file_name = zip_file.namelist()[0]

    df = pd.read_csv(zip_file.open(file_name))
    df = df[(df['EFFYLEV'] == 1) | df['EFFYLEV'].isnull()]

    return df.convert_dtypes()


def parse_alias(string):
    """IPEDS IALIAS is delimited by many different kinds of character(s)"""
    if string is not pd.NA and string:
        alias = []
        if '  ' in string:
            alias = string.split('  ')
        elif '|' in string:
            alias = string.split('|')
        elif ',' in string:
            alias = string.split(',')
        elif '/' in string:
            alias = string.split('/')
        else:
            alias = [string]

        alias = [x.strip() for x in alias if x and x != ' ']
        return alias
    else:
        return []


if __name__ == '__main__':
    app()
