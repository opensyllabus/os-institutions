from pathlib import Path

import pandas as pd
import pandera as pa
import requests
import typer
import wandb
from loguru import logger
from pandera.typing import DataFrame, Object, Series

from os_institutions.schema_model import RORDist
from os_institutions.utils import (
    download_zip_file,
    log_info,
    wandb_artifact,
    wandb_init,
)

ARTIFACT = "opensyllabus/institutions/ror-dist:latest"

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


def read(name=ARTIFACT, use_artifact=False):
    logger.info(f"Loading {name}")
    return pd.read_parquet(wandb_artifact(name, use_artifact))


@pa.check_types
def load() -> DataFrame[Schema]:
    return read(use_artifact=True)


@app.command()
def csv(path: Path):
    df = read()
    df.to_csv(path)
    logger.info(f"Wrote {len(df)} rows to {path}")


@app.command()
def check():
    df = read()
    df.info()
    Schema(df)


@app.command()
def build(
    api="https://zenodo.org/api/records/?communities=ror-data&sort=mostrecent",
):
    wandb_init(group="ror-dist")

    logger.info(f"Fetching records from {api}")
    records = requests.get(api).json()
    file_url = get_most_recent(records)
    file_name = get_file_name(file_url)

    logger.info(f"Downloading {file_url}")
    zip_file = download_zip_file(file_url)

    logger.info(f"Loading {file_name}")
    df = pd.read_json(zip_file.open(file_name))
    df = df.convert_dtypes()

    log_info(df)

    artifact = wandb.Artifact("ror-dist", type="dataset")
    with artifact.new_file("ror-dist.parquet", "wb") as fh:
        df.to_parquet(fh)
    wandb.log_artifact(artifact)


def list_records(api):
    """Retrieve recent ROR releases"""
    return requests.get(api).json()


def get_most_recent(records):
    """Parse the link to the most recent file"""
    return records["hits"]["hits"][0]["files"][0]["links"]["self"]


def get_file_name(file):
    """Get specific target file name"""
    return file.split("/")[-2].replace(".zip", ".json")


if __name__ == "__main__":
    app()
