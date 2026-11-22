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
from loguru import logger
from pandera.typing import DataFrame, Object, Series
from SPARQLWrapper import JSON, SPARQLWrapper
from tqdm import tqdm

from os_institutions import params, runs
from os_institutions.paths import artifact_path
from os_institutions.schema_model import WikidataDist
from os_institutions.sources import ror
from os_institutions.utils import write_parquet

STAGE = 'wikidata_dist'

# `snapshot` is a free-form label of when the live source was queried. It is
# not used by the code: bump it in params.yaml to make DVC re-run the stage.
DEFAULTS = {'source': 'wdqs', 'snapshot': None}

app = typer.Typer()


class Schema(WikidataDist):
    wikidata_id: Series[pd.StringDtype] = pa.Field(unique=True)
    results: Series[Object] = pa.Field(nullable=True)


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
    source: str | None = typer.Option(
        None, help='wdqs (live, throttled) or qlever (weekly mirror)'
    ),
    input: Path | None = typer.Option(
        None, help='ROR parquet (default: the ror output).'
    ),
):
    p = params.resolve(STAGE, DEFAULTS, source=source)
    if p['source'] not in SOURCES:
        raise typer.BadParameter(f'source must be one of {list(SOURCES)}')
    input = input or artifact_path('ror')
    with runs.start(STAGE, params=p) as run:
        run.set_source(source=p['source'], api=SOURCES[p['source']][0])
        run.add_input(input)
        process(run, input, p['source'])


def process(run, input, source):
    df = ror.load(input)
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

    run.log_info(df)

    output = artifact_path(STAGE)
    write_parquet(df, output)
    run.add_output(output)


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
