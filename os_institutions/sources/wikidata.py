from pathlib import Path

import numpy as np
import pandas as pd
import pandera as pa
import typer
import wandb
from loguru import logger
from pandera.typing import DataFrame, Object, Series
from tqdm import tqdm

from os_institutions.schema_model import Wikidata
from os_institutions.sources import wikidata_dist
from os_institutions.utils import log_info, wandb_artifact, wandb_init

ARTIFACT = "opensyllabus/institutions/wikidata:latest"

app = typer.Typer()


class Schema(Wikidata):
    wikidata_enrollment: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    wikidata_grid_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikidata_image: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikidata_description: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikidata_name: Series[pd.StringDtype]
    wikidata_ror_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikidata_url: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikidata_logo: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikidata_unitid: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    wikidata_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    wikidata_labels: Series[Object] = pa.Field(nullable=True)
    wikidata_lat: Series[pd.Float64Dtype] = pa.Field(nullable=True)
    wikidata_lng: Series[pd.Float64Dtype] = pa.Field(nullable=True)


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
def build():
    wandb_init(group="wikidata")

    df = wikidata_dist.load()

    tqdm.pandas(desc="Parsing results")
    df = df.results.progress_apply(parse_results)
    df = pd.json_normalize(df.dropna())

    df["id"] = get_identifier(df)
    df["labels"] = get_labels(df)
    df["enrollment"] = get_enrollment(df)
    df["ipeds"] = pd.to_numeric(df.ipeds)
    df["location"] = get_location(df)
    df["lat"] = get_lat(df)
    df["lng"] = get_lng(df)

    df = df.drop(columns=["item", "itemAltLabel", "location"])
    df = df.rename(
        columns={
            "itemLabel": "name",
            "itemDescription": "description",
            "ipeds": "unitid",
            "ror": "ror_id",
            "grid": "grid_id",
        }
    )

    df = apply_hotfix(df)

    df = df.add_prefix("wikidata_")
    df = df.convert_dtypes()

    log_info(df)

    artifact = wandb.Artifact(type="dataset", name="wikidata")
    with artifact.new_file("wikidata.parquet", "wb") as fh:
        df.to_parquet(fh)
    wandb.log_artifact(artifact)


def apply_hotfix(df):
    # Wikimedia URL in the GRID field
    target_idx = df[df.id == "Q10873002"].index[0]
    df.loc[target_idx, "grid_id"] = pd.NA
    return df


def extract_values(result: dict):
    """Flatten Wikidata dictionary, so that it can be ingested
    into Pandas dataframe.

    ie) {'item': {'type': 'uri', 'value': 'http://www.wikidata.org/'}
    has a nested dict with 'value' key. This becomes the following:
    {'item': 'http://www.wikidata.org/'}
    """
    d = dict()

    for key in result.keys():
        if result[key]:
            d[key] = result[key]["value"]

    return d


def parse_results(results):
    """XXX: Keep only the first for simplicity, but it will be worth
    the effort to group multiple URLs and names.
    """
    if results is not None:
        return extract_values(results[0])


def get_identifier(df):
    """Extract Wikidata identifier string from URL"""
    return df.item.apply(lambda x: x.split("/")[-1])


def get_labels(df):
    return df.itemAltLabel.str.split(",")


def get_enrollment(df):
    return np.floor(pd.to_numeric(df.enrollment, errors="coerce"))


def get_location(df):
    """Extract longitude, latitude from location Point(x, y) strin

    (0,0) is used as NA value to avoid null checks downstream.
    """
    return (
        df.location.str.replace("Point", "")
        .str.replace(" ", ",")
        .fillna("(0,0)")
        .apply(eval)
    )


def get_lng(df):
    """Extract longitude from location (x, y)"""
    return df.location.apply(lambda x: float(x[0])).replace(0.0, None)


def get_lat(df):
    """Extract latitude from location (x, y)"""
    return df.location.apply(lambda x: float(x[1])).replace(0.0, None)


if __name__ == "__main__":
    app()
