import sys
import time
from collections import deque
from functools import partial
from multiprocessing import Pool
from pathlib import Path

import pandas as pd
import pandera as pa
import requests
import typer
from addict import Dict
from loguru import logger
from pandera.typing import DataFrame, Series
from tqdm import tqdm

from os_institutions import params, runs
from os_institutions.paths import artifact_path
from os_institutions.schema_model import Wikipedia
from os_institutions.sources import ror
from os_institutions.utils import write_parquet

STAGE = "wikipedia"

# `snapshot` is a free-form label of when the live source was queried. It is
# not used by the code: bump it in params.yaml to make DVC re-run the stage.
DEFAULTS = {"api": "https://en.wikipedia.org/w/api.php", "snapshot": None}

MAX_RETRIES = 10
BACKOFF_BASE = 5
BACKOFF_CAP = 300
MAX_MISSING_RATIO = 0.01

app = typer.Typer()


class Schema(Wikipedia):
    wikipedia_url: Series[pd.StringDtype]
    wikipedia_title: Series[pd.StringDtype]
    wikipedia_description: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikipedia_image_url: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikipedia_ror_id: Series[pd.StringDtype] = pa.Field(nullable=True)


def apply_hotfixes(df):
    # This hotfix cannot be applied during build time
    # since the job takes 1.5 hours.
    # HTTP error caused this single row to be dropped off.
    data = {
        "url": "http://en.wikipedia.org/wiki/North_Eastern_Hill_University",  # noqa
        "title": "North-Eastern Hill University",  # noqa
        "description": "North-Eastern Hill University (NEHU) is a Central University established on 19 July 1973 by an Act of the Indian Parliament. The university is in the suburb of Shillong, the state capital of Meghalaya, India. The university has two campuses, in Shillong and Tura. Both campuses are in Meghalaya state. The first pro-vice chancellor was Early Rising Singha\nIt is the University Grants Commission's University with Potential for Excellence (conferred in 2006). It was established as a regional university for the states of northeast India, including Meghalaya, Nagaland, Arunachal Pradesh and Mizoram, and had given birth to Nagaland University in 1994 and Mizoram University in 2001.",  # noqa
        "image_url": "https://upload.wikimedia.org/wikipedia/en/4/48/North-Eastern_Hill_University_Logo.png",  # noqa
    }
    target_idx = df[df.wikipedia_ror_id == "055m2tx54"].index[0]
    df.loc[target_idx, "wikipedia_url"] = data["url"]
    df.loc[target_idx, "wikipedia_title"] = data["title"]
    df.loc[target_idx, "wikipedia_description"] = data["description"]
    df.loc[target_idx, "wikipedia_image_url"] = data["image_url"]
    return df


def read(path: Path | None = None):
    path = path or artifact_path(STAGE)
    logger.info(f"Loading {path}")
    df = pd.read_parquet(path)
    df = apply_hotfixes(df)
    return df


@pa.check_types
def load(path: Path | None = None) -> DataFrame[Schema]:
    return read(path)


@app.command()
def csv(
    path: Path,
    input: Path | None = typer.Option(None, help="Parquet to read."),
):
    df = read(input)
    df.to_csv(path)
    logger.info(f"Wrote {len(df)} rows to {path}")


@app.command()
def check(input: Path | None = typer.Option(None, help="Parquet to read.")):
    df = read(input)
    df.info()
    Schema(df)


@app.command()
def build(
    api: str | None = typer.Option(None, help="MediaWiki API URL."),
    input: Path | None = typer.Option(
        None, help="ROR parquet (default: the ror output)."
    ),
):
    p = params.resolve(STAGE, DEFAULTS, api=api)
    input = input or artifact_path("ror")
    with runs.start(STAGE, params=p) as run:
        run.set_source(api=p["api"])
        run.add_input(input)
        process(run, input, p["api"])


def process(run, input, api):
    df = ror.load(input)
    df = df.rename(columns={"ror_wikipedia_url": "wikipedia_url"})
    df = df[["ror_id", "wikipedia_url"]]
    df = df.dropna()
    df = df.reset_index(drop=True)

    # XXX: Wikimedia introduced blocking & throttling
    # https://phabricator.wikimedia.org/T400119
    # n_cores = cpu_count() // 2
    n_cores = 1
    logger.info(f"Collecting Wikipedia with {n_cores} processes")
    with Pool(n_cores) as pool:
        results = pool.imap(partial(get_result, api=api), df.wikipedia_url)
        df["result"] = deque(tqdm(results, total=len(df.wikipedia_url)))

    check_coverage(df)
    run.log_info(df)

    # Due to null values in the JSON, pyarrow throws an error.
    # So, it must be normalized right away.
    logger.info("Building Wikipedia")

    res = pd.json_normalize(df.result)
    res = res.convert_dtypes()

    res["ror_id"] = df.ror_id
    res = res.add_prefix("wikipedia_")
    run.log_info(res)

    output = artifact_path(STAGE)
    write_parquet(res, output)
    run.add_output(output)


def get_title(url):
    """Parse Wikipedia page title from URL."""
    return url.split("/")[-1].replace("_", " ")


def get_image_url(url):
    """Use the stable upload host without the API's tracking query.

    Since 2026-11 the pageimages API returns thumb.wikimedia.org URLs with
    utm_* parameters for some pages; both hosts serve the same file.
    """
    if not isinstance(url, str):
        return url
    url = url.split("?")[0]
    return url.replace(
        "https://thumb.wikimedia.org/", "https://upload.wikimedia.org/", 1
    )


def get_agent():
    info = sys.version_info
    contact = "(https://opensyllabus.org; contact@opensyllabus.org)"
    return f"Open Syllabus/{info[0]}.{info[1]} {contact}"


class Unavailable(Exception):
    """Wikipedia was unreachable (DNS, timeouts) after all retries."""


def get_response(api, params, timeout):
    """GET with backoff on connection errors, so an outage aborts the build
    instead of leaving null rows."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return requests.get(
                api,
                params=params,
                timeout=timeout,
                headers={"User-Agent": get_agent()},
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == MAX_RETRIES:
                msg = f"{type(e).__name__} after {attempt} retries"
                raise Unavailable(msg) from None
            wait = min(BACKOFF_BASE * 2**attempt, BACKOFF_CAP)
            logger.warning(f"{type(e).__name__}, retry in {wait}s")
            time.sleep(wait)


def check_coverage(df):
    missing = df["result"].isna().sum()
    if missing > len(df) * MAX_MISSING_RATIO:
        raise RuntimeError(f"{missing} of {len(df)} pages have no result")


def get_result(url, api="https://en.wikipedia.org/w/api.php", timeout=30):
    if url:
        title = get_title(url)
        params = dict(
            titles=title,
            action="query",
            format="json",
            redirects=True,
            prop="pageimages|extracts",
            pithumbsize=500,  # Max pixels
            pilimit=1,  # Max number of pages
            pilicense="any",  # Allow non-free / fair use images
            exintro=True,  # Limit length of the extracts
            explaintext=True,  # Prevent malformed text
        )

        try:
            resp = get_response(api, params, timeout)
            data = Dict(resp.json())

            if pages := data.query.pages:
                # Use iterator to access the first item in the
                # dictionary since the key is unknown.
                page = pages[next(iter(pages))]

                return dict(
                    url=url,
                    title=page.title,
                    description=page.extract,
                    image_url=get_image_url(page.thumbnail.source),
                )

        except Unavailable:
            raise
        except Exception as e:
            logger.warning(e)
            logger.info(url)


if __name__ == "__main__":
    app()
