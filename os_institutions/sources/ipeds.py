from pathlib import Path

import pandas as pd
import pandera as pa
import typer
from loguru import logger
from os_normalizer.uri import repair_scheme
from pandera.typing import DataFrame, Object, Series

from os_institutions import params, runs
from os_institutions.paths import artifact_path
from os_institutions.schema_model import IPEDS
from os_institutions.utils import download_zip_file, write_parquet

STAGE = 'ipeds'

DEFAULTS = {'year': 2024}

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


def read(path: Path | None = None):
    path = path or artifact_path(STAGE)
    logger.info(f'Loading {path}')
    return pd.read_parquet(path)


@pa.check_types
def load(path: Path | None = None) -> DataFrame[Schema]:
    return read(path)


@app.command()
def csv(
    path: Path,
    input: Path | None = typer.Option(None, help='Parquet to read.'),
):
    df = read(input)
    df.to_csv(path)
    logger.info(f'Wrote {len(df)} rows to {path}')


@app.command()
def check(input: Path | None = typer.Option(None, help='Parquet to read.')):
    df = read(input)
    df.info()
    Schema(df)


@app.command()
def build(
    year: int | None = typer.Option(None, help='IPEDS data year.'),
):
    """IPEDS provides multiple CSV files for different data files.
    Therefore, they are loaded separately and merged on UNITID.
    """
    p = params.resolve(STAGE, DEFAULTS, year=year)
    with runs.start(STAGE, params=p) as run:
        run.set_source(
            year=p['year'],
            files=[f'HD{p["year"]}.zip', f'EFFY{p["year"]}.zip'],
        )
        process(run, p['year'])


def process(run, year):
    # There might be multiple rows representing the same school in IPEDS
    # because of EFFY data, which is broken out into rows by level:
    # '4' for EFFY data on graduate students, '2' for EFFY data
    # on undergraduate students, '1' for total students.  Since total
    # students is what we're interested in, filter for that, also allowing
    # null values.
    hd = get_hd(year)
    effy = get_effy(year)

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

    run.log_info(df)

    output = artifact_path(STAGE)
    write_parquet(df, output)
    run.add_output(output)


def get_hd(year):
    file_url = f'https://nces.ed.gov/ipeds/datacenter/data/HD{year}.zip'
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


def get_effy(year):
    file_url = f'https://nces.ed.gov/ipeds/datacenter/data/EFFY{year}.zip'
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
