import re
from pathlib import Path

import pandas as pd
import pandera as pa
import requests
import typer
from loguru import logger
from pandera.typing import DataFrame, Object, Series

from os_institutions import params, runs
from os_institutions.paths import artifact_path
from os_institutions.schema_model import RORDist
from os_institutions.utils import download_zip_file, write_parquet

STAGE = "ror_dist"

DEFAULTS = {
    "api": (
        "https://zenodo.org/api/records/?communities=ror-data&sort=mostrecent"
    ),
    "release": "latest",
}

app = typer.Typer()


class Schema(RORDist):
    locations: Series[Object]
    established: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    external_ids: Series[Object]
    id: Series[pd.StringDtype] = pa.Field(unique=True)
    domains: Series[Object]
    links: Series[Object]
    names: Series[Object]
    relationships: Series[Object]
    status: Series[pd.StringDtype]
    types: Series[Object]
    admin: Series[Object]


def read(path: Path | None = None):
    path = path or artifact_path(STAGE)
    logger.info(f"Loading {path}")
    return pd.read_parquet(path)


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
    api: str | None = typer.Option(None, help="Zenodo records API URL."),
    release: str | None = typer.Option(
        None,
        help='ROR release label (for example "v2.16"), or "latest".',
    ),
):
    p = params.resolve(STAGE, DEFAULTS, api=api, release=release)
    with runs.start(STAGE, params=p) as run:
        logger.info(f"Fetching records from {p['api']}")
        records = requests.get(p["api"]).json()
        file_url = select_file_url(records, p["release"])
        file_name = get_file_name(file_url)
        run.set_source(
            release=p["release"],
            record=get_record_id(file_url),
            file=file_name.replace(".json", ".zip"),
        )

        logger.info(f"Downloading {file_url}")
        zip_file = download_zip_file(file_url)

        logger.info(f"Loading {file_name}")
        df = pd.read_json(zip_file.open(file_name))
        df = df.convert_dtypes()

        run.log_info(df)

        output = artifact_path(STAGE)
        write_parquet(df, output)
        run.add_output(output)


def list_records(api):
    """Retrieve recent ROR releases"""
    return requests.get(api).json()


def get_most_recent(records):
    """Parse the link to the most recent file"""
    return records["hits"]["hits"][0]["files"][0]["links"]["self"]


def select_file_url(records, release="latest"):
    """Link to the file of a release, like "v2.16" (or the most recent).

    The release label is the start of the file name, for example
    `v2.16-2026-11-19-ror-data.zip`. Only the records on the API's first
    page are searched.
    """
    if release == "latest":
        return get_most_recent(records)

    for hit in records["hits"]["hits"]:
        for file in hit["files"]:
            url = file["links"]["self"]
            name = url.split("/")[-2]
            if name.startswith(release + "-"):
                return url
    raise ValueError(f"No ROR release {release!r} in the API's records")


def get_record_id(file_url):
    """Zenodo record ID of a file link"""
    match = re.search(r"/records/(\d+)/", file_url)
    return match.group(1) if match else None


def get_file_name(file):
    """Get specific target file name"""
    return file.split("/")[-2].replace(".zip", ".json")


if __name__ == "__main__":
    app()
