from pathlib import Path

import pandas as pd
import pandera as pa
import typer
import wandb
from loguru import logger
from pandera.typing import DataFrame, Object, Series

from os_institutions.paths import DATA_DIR
from os_institutions.schema_model import ROR
from os_institutions.sources import ror_dist
from os_institutions.utils import log_info, wandb_artifact, wandb_init

ARTIFACT = "opensyllabus/institutions/ror:latest"

app = typer.Typer()


class Schema(ROR):
    ror_id: Series[pd.StringDtype] = pa.Field(unique=True)
    ror_name: Series[pd.StringDtype]
    ror_aliases: Series[Object]
    ror_url: Series[pd.StringDtype] = pa.Field(nullable=True)
    ror_wikipedia_url: Series[pd.StringDtype] = pa.Field(nullable=True)
    ror_established: Series[pd.Int64Dtype] = pa.Field(nullable=True)
    ror_city: Series[pd.StringDtype]
    ror_state_code: Series[pd.StringDtype] = pa.Field(nullable=True)
    ror_state: Series[pd.StringDtype] = pa.Field(nullable=True)
    ror_country_code: Series[pd.StringDtype]
    ror_country_name: Series[pd.StringDtype]
    ror_lat: Series[pd.Float64Dtype] = pa.Field(nullable=True)
    ror_lng: Series[pd.Float64Dtype] = pa.Field(nullable=True)
    ror_grid_id: Series[pd.StringDtype] = pa.Field(nullable=True)
    ror_wikidata_id: Series[pd.StringDtype] = pa.Field(nullable=True)


def read(name=ARTIFACT, use_artifact=False):
    logger.info(f"Loading {name}")
    return pd.read_parquet(wandb_artifact(name, use_artifact))


@app.command()
def csv(path: Path):
    df = read()
    df.to_csv(path)
    logger.info(f"Wrote {len(df)} rows to {path}")


@pa.check_types
def load() -> DataFrame[Schema]:
    return read(use_artifact=True)


@app.command()
def check():
    df = read()
    df.info()
    Schema(df)


@app.command()
def build():
    wandb_init(group="ror")

    logger.info("Building ROR dataset")
    df = ror_dist.load()

    df = df[is_active(df) & (is_education(df) | is_extra_institution(df))]
    df = df.reset_index(drop=True)
    df = df.drop(columns=["types", "status"])

    # XXX: Apply() is slow but simple to read
    df["id"] = df.id.apply(lambda x: x.split("/")[-1])
    df["name"] = df.names.apply(
        lambda xs: [x["value"] for x in xs if "ror_display" in x["types"]]
    ).str[0]
    df["aliases"] = df.names.apply(
        lambda xs: [x["value"] for x in xs if "ror_display" not in x["types"]]
    )
    df["grid_id"] = df.external_ids.apply(
        lambda xs: [get_preferred(x) for x in xs if x["type"] == "grid"]
    ).str[0]
    df["wikidata_id"] = df.external_ids.apply(
        lambda xs: [get_preferred(x) for x in xs if x["type"] == "wikidata"]
    ).str[0]
    df["url"] = df.links.apply(
        lambda xs: [x["value"] for x in xs if x["type"] == "website"]
    ).str[0]
    df["wikipedia_url"] = df.links.apply(
        lambda xs: [x["value"] for x in xs if x["type"] == "wikipedia"]
    ).str[0]

    df = df.merge(
        get_location(df), how="left", left_index=True, right_index=True
    )

    # Add US prefix to state code for ISO standard.
    df.loc[df["country_code"] == "US", "state_code"] = df["state_code"].apply(
        lambda x: (
            f"US-{x}"
            if pd.notna(x)
            and len(str(x)) == 2
            and not str(x).startswith("US-")
            else x
        )
    )

    # State code should not contain numbers
    df["state_code"] = df["state_code"].where(
        ~df["state_code"].str.contains(r"\d", na=False)
    )

    df = df.drop(
        columns=[
            "names",
            "locations",
            "external_ids",
            "relationships",
            "links",
            "domains",
        ]
    )

    df = apply_hotfixes(df)

    df = df.add_prefix("ror_")
    df = df.convert_dtypes()

    logger.info("Finished processing ROR dataset")
    log_info(df)

    artifact = wandb.Artifact(type="dataset", name="ror")
    with artifact.new_file("ror.parquet", "wb") as fh:
        df.to_parquet(fh)
    wandb.log_artifact(artifact)


def apply_hotfixes(df):
    # Wikidata ID is misplaced into GRID ID field
    target_idx = df[df.id == "04yr81d29"].index[0]
    df.loc[target_idx, "wikidata_id"] = df.loc[target_idx, "grid_id"]
    df.loc[target_idx, "grid_id"] = pd.NA

    # GRID ID is the parent's (03r6hpz93), stored as a URL
    df.loc[df.id == "02fvjvv74", "grid_id"] = pd.NA
    return df


def is_active(df):
    """Filter active institutions"""
    return df.status == "active"


def is_education(df):
    """Filter educational institutions"""
    return df.types.apply(lambda xs: "education" in xs)


def is_extra_institution(df):
    extra = set(pd.read_csv(DATA_DIR / "ror_extra_institutions.csv").id)
    return df.id.isin(extra)


def get_location(
    df,
    columns=[
        "city",
        "country_code",
        "country_name",
        "state_code",
        "state",
        "lat",
        "lng",
    ],
    renames={
        "name": "city",
        "country_subdivision_code": "state_code",
        "country_subdivision_name": "state",
    },
):
    """Lift city, country & state code for first address."""
    location = df.locations.str[0]
    location = pd.json_normalize(location, max_level=0)
    location = pd.json_normalize(location.geonames_details, max_level=0)
    location = location.rename(columns=renames)
    return location[columns]


def get_preferred(external_id: dict):
    if preferred := external_id["preferred"]:
        return preferred
    else:
        return external_id["all"][0]


if __name__ == "__main__":
    app()
