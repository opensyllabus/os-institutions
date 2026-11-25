from functools import partial
from operator import is_not
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd
import pandera.pandas as pa
import typer
from loguru import logger
from pandera.typing.pandas import DataFrame, Object, Series

from os_institutions import runs
from os_institutions.paths import DATA_DIR, artifact_path
from os_institutions.schema_model import Dataset
from os_institutions.sources import ipeds, ror, wikidata, wikipedia
from os_institutions.utils import read_yaml, write_parquet

STAGE = 'dataset'

app = typer.Typer()


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
    ror_input: Path | None = typer.Option(
        None, '--ror', help='ROR parquet (default: the ror output).'
    ),
    wikidata_input: Path | None = typer.Option(
        None,
        '--wikidata',
        help='Wikidata parquet (default: the wikidata output).',
    ),
    wikipedia_input: Path | None = typer.Option(
        None,
        '--wikipedia',
        help='Wikipedia parquet (default: the wikipedia output).',
    ),
    ipeds_input: Path | None = typer.Option(
        None, '--ipeds', help='IPEDS parquet (default: the ipeds output).'
    ),
):
    """Build institutions dataset based on ROR, IPEDS, and Wikidata."""
    inputs = Inputs(
        ror=ror_input or artifact_path('ror'),
        wikidata=wikidata_input or artifact_path('wikidata'),
        wikipedia=wikipedia_input or artifact_path('wikipedia'),
        ipeds=ipeds_input or artifact_path('ipeds'),
    )
    with runs.start(STAGE) as run:
        for path in inputs:
            run.add_input(path)
        process(run, inputs)


class Inputs(NamedTuple):
    """Local paths of the upstream stage outputs."""

    ror: Path
    wikidata: Path
    wikipedia: Path
    ipeds: Path


def process(run, inputs):
    df = get_canonical_dataset(inputs)

    # Blacklist by IDs.
    for path in sorted((DATA_DIR / 'blacklists').glob('*.csv')):
        blacklist = pd.read_csv(path).convert_dtypes()
        df = df[df.unitid.isna() | ~df.unitid.isin(blacklist.unitid)]
        df = df[df.ror_id.isna() | ~df.ror_id.isin(blacklist.ror_id)]
    df = df.reset_index(drop=True)

    # Add extra URLs
    df['extra_match_urls'] = get_extra_match_urls(df)
    df['extra_prefix_urls'] = get_extra_prefix_urls(df)

    # Canonicalize metadata in the order of ROR -> IPEDS -> Wikidata.
    df['city'] = df['ror_city'].combine_first(df['ipeds_city'])
    df['name'] = df['ror_name'].combine_first(df['ipeds_instnm'])

    # ROR coordinates are demoted due to poor precision.
    df["lat"] = (
        df["ipeds_latitude"]
        .combine_first(df["wikidata_lat"])
        .combine_first(df["ror_lat"])
    )
    df["lng"] = (
        df["ipeds_longitud"]
        .combine_first(df["wikidata_lng"])
        .combine_first(df["ror_lng"])
    )
    df['url'] = get_url(df)

    df['country_code'] = get_country_code(df)
    df['country'] = get_country(df)

    df['state_code'] = get_state_code(df)
    df['state'] = get_state(df)

    df['extra_enrollment'] = get_extra_enrollment(df)
    df['enrollment'] = get_enrollment(df)

    # Add institution type based on Carnegie classification.
    df['two_year'] = df['ipeds_c21basic'] < 14
    df['four_year'] = (df['ipeds_c21basic'] >= 15) & (
        df['ipeds_c21basic'] <= 32
    )
    df['graduate'] = (df['ipeds_c21basic'] >= 15) & (
        df['ipeds_c21basic'] <= 20
    )
    df['research'] = (df['ipeds_c21basic'] >= 15) & (
        df['ipeds_c21basic'] <= 16
    )

    # Metadata from Wiki
    df['description'] = df['wikipedia_description'].combine_first(
        df['wikidata_description']
    )
    df['image_url'] = df['wikipedia_image_url'].combine_first(
        df['wikidata_image']
    )
    df['wikipedia_url'] = df['ror_wikipedia_url']

    df = df.fillna(pd.NA)

    # Fields for matcher
    df['urls'] = df.apply(get_urls, axis=1)
    df['names'] = df.apply(get_names, axis=1)

    # TODO: Make this stable across dataset versions.

    df = df[list(Schema.to_schema().columns.keys())]

    # XXX: _id is ignored by pa.DataFrameModel
    df['_id'] = df.index + 1
    df = df.convert_dtypes()

    run.log_info(df)

    output = artifact_path(STAGE)
    write_parquet(df, output)
    run.add_output(output)


def merge_extra_unitids(df):
    logger.info(len(df))

    extra = pd.read_csv(DATA_DIR / 'extra_unitids.csv').convert_dtypes()
    df = pd.merge(df, extra, on='ror_id', how='left')

    logger.info(len(df))
    return df


def merge_wikidata(df, path=None):
    logger.info(len(df))

    df = pd.merge(
        df,
        wikidata.load(path),
        left_on='ror_id',
        right_on='wikidata_ror_id',
        how='left',
    )
    df['unitid'] = df['unitid'].combine_first(df['wikidata_unitid'])

    logger.info(len(df))
    return df


def merge_wikipedia(df, path=None):
    logger.info(len(df))

    df = pd.merge(
        df,
        wikipedia.load(path).drop(columns=['wikipedia_url']),
        left_on='ror_id',
        right_on='wikipedia_ror_id',
        how='left',
    )

    logger.info(len(df))
    return df


def merge_ipeds(df, path=None):
    logger.info(len(df))

    is_ipeds = df['unitid'].notna()
    df_ipeds = df[is_ipeds]
    df_non_ipeds = df[~is_ipeds]

    df = pd.merge(
        ipeds.load(path),
        df_ipeds,
        left_on='ipeds_unitid',
        right_on='unitid',
        how='left',
    )
    df['unitid'] = df['unitid'].combine_first(df['ipeds_unitid'])

    df = pd.concat([df_non_ipeds, df], join='outer')

    logger.info(len(df))
    return df


def get_canonical_dataset(inputs):
    """Build a canonical dataset by merging ROR, IPEDS, and Wikidata."""
    df = ror.load(inputs.ror)
    # Legacy identifier, kept for backwards compatibility. Sourced directly
    # from ROR's own provenance data, not used as a join/lookup key here.
    df['grid_id'] = df['ror_grid_id']

    df = merge_extra_unitids(df)
    df = merge_wikidata(df, inputs.wikidata)
    df = merge_wikipedia(df, inputs.wikipedia)
    df = merge_ipeds(df, inputs.ipeds)

    df = df.reset_index(drop=True)
    df = df.convert_dtypes()

    return df


def combine_url_lists(l1, l2):
    if l1 is pd.NA and l2 is pd.NA:
        return pd.NA
    elif l1 is pd.NA:
        return l2
    elif l2 is pd.NA:
        return l1
    else:
        # Keep first-seen order: a set would reorder with the per-process
        # string hash seed, so a rebuild would not reproduce the same file.
        return list(dict.fromkeys(l1 + l2))


def get_extra_match_urls(df):
    """Get extra match URLs for institution matching."""
    ipeds_extra = read_yaml(
        DATA_DIR / 'ipeds_match_urls.yml',
        columns=('unitid', 'extra_ipeds_urls'),
    ).convert_dtypes()
    ror_extra = read_yaml(
        DATA_DIR / 'ror_match_urls.yml', columns=('ror_id', 'extra_ror_urls')
    ).convert_dtypes()
    wikidata_extra = read_yaml(
        DATA_DIR / 'wikidata_match_urls.yml',
        columns=('wikidata_id', 'extra_wikidata_urls'),
    ).convert_dtypes()

    ids = df[['unitid', 'ror_id', 'wikidata_id']]
    ids = (
        ids.join(ipeds_extra.set_index('unitid'), on='unitid', how='left')
        .join(ror_extra.set_index('ror_id'), on='ror_id', how='left')
        .join(
            wikidata_extra.set_index('wikidata_id'),
            on='wikidata_id',
            how='left',
        )
    ).replace({np.nan: pd.NA})

    extra_urls = (
        ids['extra_ipeds_urls']
        .combine(ids['extra_ror_urls'], combine_url_lists)
        .combine(ids['extra_wikidata_urls'], combine_url_lists)
    )

    return extra_urls


def get_extra_prefix_urls(df):
    """Get extra prefix URLs for institution matching."""
    ror_extra = read_yaml(
        DATA_DIR / 'ror_prefix_urls.yml',
        columns=('ror_id', 'extra_ror_urls'),
    ).convert_dtypes()
    ipeds_extra = read_yaml(
        DATA_DIR / 'ipeds_prefix_urls.yml',
        columns=('unitid', 'extra_ipeds_urls'),
    ).convert_dtypes()

    ids = df[['unitid', 'ror_id', 'wikidata_id']]
    ids = (
        ids.join(ror_extra.set_index('ror_id'), on='ror_id', how='left').join(
            ipeds_extra.set_index('unitid'), on='unitid', how='left'
        )
    ).replace({np.nan: pd.NA})

    extra_urls = ids['extra_ror_urls'].combine(
        ids['extra_ipeds_urls'], combine_url_lists
    )

    return extra_urls


def get_country_code(df):
    """Get country code from GRID, IPEDS, otherwise 'US'.

    If the institution was found in the IPEDS or Carnegie sets, we
    can almost always assume that the institution is in the US.  The
    exceptions are a handful of states freely associated with the US,
    which are also tracked in IPEDS/Carnegie.  We treat the STABBR
    for those states as country codes.
    """
    return pd.Series(
        np.select(
            condlist=[
                df['ror_country_code'].notna(),
                df['ipeds_stabbr'].isin(['FM', 'MH', 'PW']),
                df['unitid'].notna(),
            ],
            choicelist=[df['ror_country_code'], df['ipeds_stabbr'], 'US'],
            default=pd.NA,
        )
    ).convert_dtypes()


def get_country(df):
    """Get full country name from GRID, otherwise as 'United States'."""
    # XXX: 'FM', 'MH', 'PW' are non US states that are part of IPEDS.
    # There might be a better way to handle these exceptions.
    to_country = {
        'FM': 'Federated States of Micronesia',
        'MH': 'Marshall Islands',
        'PW': 'Palau',
    }
    return pd.Series(
        np.select(
            condlist=[
                df['ror_country_name'].notna(),
                df['ipeds_stabbr'].isin(['FM', 'MH', 'PW']),
                df['unitid'].notna(),
            ],
            choicelist=[
                df['ror_country_name'],
                df['ipeds_stabbr'].apply(lambda x: to_country.get(x)),
                'United States',
            ],
            default=pd.NA,
        )
    ).convert_dtypes()


def get_state_code(df):
    """Get state code from GRID, IPEDS, where IPEDS state code are
    prefixed with 'US-'.

    Per ISO standard (or one of them, anyway) state codes in
    'ror_state_code' also have the country code prepended, e.g.,
    'US-', 'RU-'.  Adopt this style when falling back to other
    sources, and since we know they're US only, we can almost always
    append "US-".  The exceptions are a handful of states freely
    associated with the US, which are also tracked in IPEDS/Carnegie.
    In those cases, we don't have a canonical state code.
    """
    return pd.Series(
        np.select(
            condlist=[
                df['ror_state_code'].notna(),
                df['ipeds_stabbr'].isin(['FM', 'MH', 'PW']),
                df['ipeds_stabbr'].notna(),
            ],
            choicelist=[
                df['ror_state_code'],
                pd.NA,
                'US-' + df['ipeds_stabbr'],
            ],
            default=pd.NA,
        )
    ).convert_dtypes()


def get_state(df, state_file='usa_state_codes_to_names.csv'):
    """Get full names of US states."""
    code_to_name = pd.read_csv(
        DATA_DIR / state_file, usecols=['iso_code', 'state']
    ).convert_dtypes()

    state_code = df['state_code']
    state_code = pd.merge(
        state_code,
        code_to_name,
        how='left',
        left_on='state_code',
        right_on='iso_code',
    ).drop('iso_code', axis=1)

    return state_code['state'].combine_first(df['ror_state'])


def get_url(df):
    """Get institutional URLs from GRID, IPEDS, and Wikidata."""
    return pd.Series(
        np.select(
            condlist=[
                df['ror_url'].notna(),
                df['ipeds_webaddr'].notna(),
                df['wikidata_url'].notna(),
            ],
            choicelist=[
                df['ror_url'],
                df['ipeds_webaddr'],
                df['wikidata_url'],
            ],
            default=pd.NA,
        )
    ).convert_dtypes()


def get_extra_enrollment(df, extra_file='extra_enrollment_data.csv'):
    """Get extra enrollment data."""
    extra = pd.read_csv(DATA_DIR / extra_file).convert_dtypes()

    ror_id = df[['ror_id']]
    ror_id = pd.merge(ror_id, extra, on='ror_id', how='left')
    return ror_id['extra_enrollment']


def get_enrollment(df):
    """Get enrollment data from IPEDS, Wikidata, and extra."""
    return (
        df["ipeds_efytotlt"]
        .combine_first(df["wikidata_enrollment"])
        .combine_first(df["extra_enrollment"])
    )


not_na = partial(is_not, pd.NA)
not_none = partial(is_not, None)


def yield_urls(x):
    if not_na(x.ipeds_webaddr):
        yield x.ipeds_webaddr
    if not_na(x.wikidata_url):
        yield x.wikidata_url
    if not_na(x.ror_url):
        yield x.ror_url
    if not_na(x.extra_match_urls):
        yield from filter(not_none, x.extra_match_urls)
    if not_na(x.extra_prefix_urls):
        yield from filter(not_none, x.extra_prefix_urls)


def yield_names(x):
    if not_na(x.ror_name):
        yield x.ror_name
    if not_na(x.wikidata_name):
        yield x.wikidata_name
    if not_na(x.ipeds_instnm):
        yield x.ipeds_instnm
    if not_na(x.wikipedia_title):
        yield x.wikipedia_title
    if not_na(x.ror_aliases):
        yield from filter(not_none, x.ror_aliases)
    if not_na(x.wikidata_labels):
        yield from filter(not_none, x.wikidata_labels)
    if not_na(x.ipeds_ialias):
        yield from x.ipeds_ialias


def get_urls(x):
    return [x for x in yield_urls(x) if x]


def get_names(x):
    return [x for x in yield_names(x) if x]


if __name__ == '__main__':
    app()
