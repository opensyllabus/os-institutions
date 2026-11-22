import sys
import time
import urllib.error
from collections import deque
from functools import partial
from multiprocessing import Pool, cpu_count
from pathlib import Path

import pandas as pd
import pandera as pa
import typer
import wandb
from loguru import logger
from pandera.typing import DataFrame, Object, Series
from SPARQLWrapper import JSON, SPARQLWrapper
from tqdm import tqdm

from os_institutions.schema_model import WikidataDist
from os_institutions.sources import ror
from os_institutions.utils import log_info, wandb_artifact, wandb_init

ARTIFACT = 'opensyllabus/institutions/wikidata-dist:latest'

app = typer.Typer()


class Schema(WikidataDist):
    wikidata_id: Series[pd.StringDtype] = pa.Field(unique=True)
    results: Series[Object] = pa.Field(nullable=True)


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
def build(
    source: str = typer.Option(
        'wdqs', help='wdqs (live, throttled) or qlever (weekly mirror)'
    ),
):
    if source not in SOURCES:
        raise typer.BadParameter(f'source must be one of {list(SOURCES)}')
    wandb_init(group='wikidata-dist')

    df = ror.load()
    df = df.rename(columns={'ror_wikidata_id': 'wikidata_id'})
    df = df[['wikidata_id']]
    df = df.dropna()
    df = df.drop_duplicates()
    df = df.reset_index(drop=True)

    ids = df['wikidata_id'].tolist()
    batches = [ids[i : i + BATCH_SIZE] for i in range(0, len(ids), BATCH_SIZE)]

    n_cores = min(cpu_count() // 2, MAX_PROCESSES)
    logger.info(
        f'Collecting {len(ids)} Wikidata items in {len(batches)} batches '
        f'with {n_cores} processes'
    )
    with Pool(n_cores) as pool:
        batch_results = deque(
            tqdm(
                pool.imap(partial(get_results, source=source), batches),
                total=len(batches),
            )
        )

    results = {}
    for batch in batch_results:
        results.update(batch)
    df['results'] = df['wikidata_id'].map(results)
    check_coverage(df)

    df = df[['wikidata_id', 'results']]
    df = df.convert_dtypes()
    df = df.dropna()
    df = df.reset_index(drop=True)

    log_info(df)

    artifact = wandb.Artifact(type='dataset', name='wikidata-dist')
    with artifact.new_file('wikidata-dist.parquet', 'wb') as fh:
        df.to_parquet(fh)
    wandb.log_artifact(artifact)


def check_coverage(df):
    missing = df['results'].isna().sum()
    if missing > len(df) * MAX_MISSING_RATIO:
        raise RuntimeError(
            f'{missing} of {len(df)} Wikidata items have no results'
        )


def get_query(wikidata_ids):
    template = """
    SELECT
        ?item
        ?itemLabel
        ?itemAltLabel
        ?itemDescription
        ?ror
        ?grid
        ?ipeds
        ?url
        ?logo
        ?image
        ?enrollment
        ?location
    WHERE {
        VALUES ?item { %s }
        OPTIONAL { ?item wdt:P2427 ?grid . }
        OPTIONAL { ?item wdt:P6782 ?ror . }
        OPTIONAL { ?item wdt:P1771 ?ipeds . }
        OPTIONAL { ?item wdt:P856 ?url . }
        OPTIONAL { ?item wdt:P154 ?logo . }
        OPTIONAL { ?item wdt:P18 ?image . }
        OPTIONAL { ?item wdt:P625 ?location . }
        OPTIONAL { ?item wdt:P2196 ?enrollment . }
        OPTIONAL { ?item wdt:P2196 ?enrollment; wdt:P585 ?enrollmentTime . }
        SERVICE wikibase:label {
            bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en".
        }
    }
    ORDER BY DESC(?enrollmentTime)
    """

    items = ' '.join(f'wd:{x}' for x in wikidata_ids)
    return template % items


def get_qlever_query(wikidata_ids):
    """Same fields as get_query, for QLever, which has no label service."""
    template = """
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX schema: <http://schema.org/>
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
    SELECT
        ?item
        ?itemLabel
        ?itemAltLabel
        ?itemDescription
        ?ror
        ?grid
        ?ipeds
        ?url
        ?logo
        ?image
        ?enrollment
        ?location
    WHERE {
        VALUES ?item { %(items)s }
        OPTIONAL {
            ?item rdfs:label ?itemLabel .
            FILTER(LANG(?itemLabel) = "en")
        }
        OPTIONAL {
            ?item schema:description ?itemDescription .
            FILTER(LANG(?itemDescription) = "en")
        }
        OPTIONAL {
            SELECT ?item (GROUP_CONCAT(?alt; separator=", ") AS ?itemAltLabel)
            WHERE {
                VALUES ?item { %(items)s }
                ?item skos:altLabel ?alt .
                FILTER(LANG(?alt) = "en")
            }
            GROUP BY ?item
        }
        OPTIONAL { ?item wdt:P2427 ?grid . }
        OPTIONAL { ?item wdt:P6782 ?ror . }
        OPTIONAL { ?item wdt:P1771 ?ipeds . }
        OPTIONAL { ?item wdt:P856 ?url . }
        OPTIONAL { ?item wdt:P154 ?logo . }
        OPTIONAL { ?item wdt:P18 ?image . }
        OPTIONAL { ?item wdt:P625 ?location . }
        OPTIONAL { ?item wdt:P2196 ?enrollment . }
    }
    """

    items = ' '.join(f'wd:{x}' for x in wikidata_ids)
    return template % {'items': items}


SOURCES = {
    'wdqs': ('https://query.wikidata.org/sparql', get_query),
    'qlever': ('https://qlever.dev/api/wikidata', get_qlever_query),
}


def normalize_qlever(wikidata_id, bindings):
    """Make QLever bindings look like WDQS ones for wikidata.py.

    WDQS writes POINT as Point and falls back to the Q-id as the label.
    """
    for b in bindings:
        if 'location' in b:
            b['location']['value'] = b['location']['value'].replace(
                'POINT', 'Point'
            )
        if 'itemLabel' not in b:
            b['itemLabel'] = {'type': 'literal', 'value': wikidata_id}
    return bindings


def get_agent():
    info = sys.version_info
    return f'Open Syllabus. Python/{info[0]}.{info[1]}'


BATCH_SIZE = 50
MAX_PROCESSES = 2
MAX_RETRIES = 10
MAX_MISSING_RATIO = 0.01
BACKOFF_BASE = 5
BACKOFF_CAP = 300


class Unavailable(Exception):
    """Wikidata kept rate-limiting or was unreachable after all retries."""


def get_backoff(error, attempt):
    """Seconds to wait: Retry-After if given, else exponential."""
    headers = getattr(error, 'headers', None)
    retry_after = headers.get('Retry-After') if headers else None
    if retry_after and retry_after.isdigit():
        return min(int(retry_after), BACKOFF_CAP)
    return min(BACKOFF_BASE * 2**attempt, BACKOFF_CAP)


def query_bindings(wikidata_ids, source):
    """One SPARQL query for a batch.

    Retries 429s and connection errors (DNS, timeouts) with backoff, then
    raises Unavailable. Other HTTP errors propagate.
    """
    api, make_query = SOURCES[source]
    sparql = SPARQLWrapper(api, agent=get_agent())
    sparql.setQuery(make_query(wikidata_ids))
    sparql.setReturnFormat(JSON)

    for attempt in range(MAX_RETRIES + 1):
        try:
            return sparql.query().convert()['results']['bindings']
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            error = e
        except OSError as e:
            error = e
        if attempt == MAX_RETRIES:
            msg = (
                f'{error!r} on {len(wikidata_ids)} ids after {attempt} retries'
            )
            raise Unavailable(msg) from None
        wait = get_backoff(error, attempt)
        logger.warning(f'{error!r}, retry in {wait}s')
        time.sleep(wait)


def get_results(wikidata_ids, source='wdqs'):
    """
    Returns {wikidata_id: bindings} for a batch of IDs.

    A 429 or connection error that outlasts the retries raises, so a
    rate-limited or offline build aborts instead of silently dropping rows.
    Any other failure splits the batch in half and retries, down to a single
    ID, which maps to None if it fails.

    TODO: Implement retries for JSONDecodeError.
    `JSONDecodeError: Invalid control character at: line _ column _ (char _)`
    """
    wikidata_ids = [x for x in wikidata_ids if x]
    if not wikidata_ids:
        return {}

    try:
        bindings = query_bindings(wikidata_ids, source)
    except Unavailable:
        raise
    except Exception as e:
        logger.warning(e)
        return split_results(wikidata_ids, source)

    results = {x: [] for x in wikidata_ids}
    for binding in bindings:
        wikidata_id = binding['item']['value'].rsplit('/', 1)[-1]
        if wikidata_id in results:
            results[wikidata_id].append(binding)
    if source == 'qlever':
        for wikidata_id, rows in results.items():
            normalize_qlever(wikidata_id, rows)
    return results


def split_results(wikidata_ids, source):
    if len(wikidata_ids) == 1:
        return {wikidata_ids[0]: None}
    mid = len(wikidata_ids) // 2
    return {
        **get_results(wikidata_ids[:mid], source),
        **get_results(wikidata_ids[mid:], source),
    }


if __name__ == '__main__':
    app()
