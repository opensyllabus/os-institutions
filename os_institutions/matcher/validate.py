from dataclasses import asdict
from pathlib import Path
from pprint import pformat

import pandas as pd
import typer
import yaml
from loguru import logger
from tqdm import tqdm

from os_institutions.matcher import load_model, model_path
from os_institutions.paths import validation_path

PATH_QA = Path(__file__).parent / "data" / "qa.yml"

app = typer.Typer()

MATCHER_OPTION = typer.Option(
    None, help="Matcher pickle (default: the matcher output)."
)


def match_institution(matcher, x):
    return matcher(
        url=x.url,
        source_url=x.source_url,
        email=x.email,
        school_name=x.school_name,
    )


def read_input(path: Path):
    """Read the institution inputs from a parquet or CSV file.

    The matcher expects missing values as None, not NaN.
    """
    if path.is_dir() or path.suffix == ".parquet":
        return pd.read_parquet(path)

    df = pd.read_csv(path)
    return df.astype(object).where(df.notna(), None)


def institutions_table(df):
    """Count per matched institution, from rows with `institution`
    (an Institution or None) and `count` columns, largest first."""
    df = df.assign(
        institution_id=df.institution.apply(lambda x: x._id if x else None)
    )
    institutions = (
        df.groupby(df.institution_id)
        .agg({"institution": "first", "count": sum})
        .sort_values(["count"], ascending=False)
    )
    institutions = pd.json_normalize(
        institutions.reset_index().apply(
            lambda x: {"count": x["count"], **asdict(x.institution)}, axis=1
        )
    )
    return institutions.head(10000)


@app.command()
def main(
    path: Path = typer.Option(
        ...,
        help="Local parquet or CSV of institution inputs to validate "
        "against, with url, source_url, email, school_name, and count "
        "columns.",
    ),
    output: Path | None = typer.Option(
        None, help="Where to write the table (default: the validation path)."
    ),
    matcher: Path | None = MATCHER_OPTION,
):
    tqdm.pandas()
    output = output or validation_path()
    matcher_path = matcher or model_path()
    model = load_model(matcher_path)

    logger.info(f"Using {matcher_path} matcher and {path} dataset.")
    df = read_input(path)
    df["institution"] = df.progress_apply(
        lambda x: match_institution(model, x), axis=1
    )
    institutions = institutions_table(df)

    output.parent.mkdir(parents=True, exist_ok=True)
    institutions.to_csv(output, index=False)
    logger.info(f"Wrote {len(institutions)} rows to {output}")


@app.command()
def qa(matcher: Path | None = MATCHER_OPTION):
    tqdm.pandas()
    matcher_path = matcher or model_path()
    model = load_model(matcher_path)

    logger.info(f"Using {matcher_path} matcher.")
    with open(PATH_QA) as fh:
        df = pd.DataFrame(list(yaml.safe_load_all(fh)))

    df["result"] = df.progress_apply(
        lambda x: match_institution(model, x), axis=1
    )

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


if __name__ == "__main__":
    app()
