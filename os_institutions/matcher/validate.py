from dataclasses import asdict
from pathlib import Path
from pprint import pformat

import pandas as pd
import typer
import wandb
import yaml
from loguru import logger
from tqdm import tqdm

from os_institutions.matcher import (
    ARTIFACT_NAME,
    download_data,
    load_model,
)
from os_institutions.utils import wandb_init

PATH_QA = Path(__file__).parent / "data" / "qa.yml"

app = typer.Typer()
matcher = load_model()


def match_institution(x):
    return matcher(
        url=x.url,
        source_url=x.source_url,
        email=x.email,
        school_name=x.school_name,
    )


@app.command()
def main(
    path: str = typer.Option(
        ..., help="Path or URL of the institution parquet to validate against."
    ),
):
    wandb_init(group="validation", tags=["main"])
    tqdm.pandas()

    logger.info(f"Using {ARTIFACT_NAME} matcher and {path} dataset.")
    df = pd.read_parquet(path)
    df["institution"] = df.progress_apply(match_institution, axis=1)
    df["institution_id"] = df.institution.progress_apply(
        lambda x: x._id if x else None
    )  # noqa

    institutions = (
        df.groupby(df.institution_id)
        .agg({"institution": "first", "count": sum})
        .sort_values(["count"], ascending=False)
    )
    institutions = pd.json_normalize(
        institutions.reset_index().progress_apply(
            lambda x: {"count": x["count"], **asdict(x.institution)}, axis=1
        )
    )
    institutions = institutions.head(10000)

    artifact = wandb.Artifact("validation", type="dataset")
    with artifact.new_file("validation.csv", "wb") as fh:
        institutions.to_csv(fh, index=False)
    wandb.log_artifact(artifact)


@app.command()
def qa():
    wandb_init(group="validation", tags=["qa"])
    tqdm.pandas()

    logger.info(f"Using {ARTIFACT_NAME} matcher.")
    with open(PATH_QA) as fh:
        df = pd.DataFrame(list(yaml.safe_load_all(fh)))

    df["result"] = df.progress_apply(match_institution, axis=1)

    logger.info("institution is null & result is not null")
    logger.info(
        df[df["institution"].isna() & df["result"].notna()].to_records()
    )  # noqa

    logger.info("institution != result")
    names = df["result"].apply(lambda x: x.name if x else None)
    logger.info(
        pformat(
            df[
                df["institution"].notna() & (df["institution"] != names)
            ].to_dict(  # noqa
                orient="records"
            )
        )
    )


@app.command()
def download():
    download_data()


if __name__ == "__main__":
    app()
