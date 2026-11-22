from pathlib import Path

import numpy as np
import pandas as pd
import pandera as pa
import typer
from loguru import logger
from pandera.typing import DataFrame, Object, Series
from tqdm import tqdm

from os_institutions import runs
from os_institutions.paths import artifact_path
from os_institutions.schema_model import Wikidata
from os_institutions.sources import wikidata_dist
from os_institutions.utils import write_parquet

STAGE = "wikidata"

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
    input: Path | None = typer.Option(
        None,
        help="Wikidata query results parquet "
        "(default: the wikidata_dist output).",
    ),
):
    input = input or artifact_path("wikidata_dist")
    with runs.start(STAGE) as run:
        run.add_input(input)
        process(run, input)


def process(run, input):
    df = wikidata_dist.load(input)

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

    run.log_info(df)

    output = artifact_path(STAGE)
    write_parquet(df, output)
    run.add_output(output)


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
