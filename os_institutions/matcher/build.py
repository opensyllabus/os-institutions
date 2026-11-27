from collections import Counter
from functools import partial
from itertools import chain
from operator import is_not
from pathlib import Path

import pandas as pd
import typer
from loguru import logger
from os_normalizer.institution import normalize_school_name
from os_normalizer.uri import (
    get_domain_url,
    get_full_url,
    repair_google_sites_url,
)
from tqdm import tqdm

from os_institutions import loader, runs
from os_institutions.matcher import format
from os_institutions.matcher.denylist import google_site_key, is_shared_host
from os_institutions.paths import artifact_path

STAGE = "matcher"

not_na = partial(is_not, pd.NA)
not_none = partial(is_not, None)
not_empty = partial(is_not, "")


def read(path: Path | None = None):
    path = path or artifact_path(STAGE)
    logger.info(f"Loading {path}")

    return format.load(path)


def repair_site_url(url):
    """`sites.google.com/a/<domain>/x` is a site of `<domain>`, as the
    matcher reads it at query time (`repair_url`)."""
    if url and 'sites.google.com/a/' in url.lower():
        return repair_google_sites_url(url.lower())
    return url


def normalize_urls(urls):
    urls = list(urls)
    site_urls = map(google_site_key, urls)
    urls = [repair_site_url(url) for url in urls]
    full_urls = map(get_full_url, urls)
    domain_urls = map(get_domain_url, urls)
    urls = filter(not_none, chain(site_urls, full_urls, domain_urls))
    # Keys on shared hosts (facebook.com, ...) would match every page there
    return [url for url in urls if not is_shared_host(url)]


def normalize_names(names):
    names = map(normalize_school_name, names)
    names = filter(not_empty, names)
    return list(names)


def mode(xs):
    if xs:
        xs = filter(pd.notna, xs)
        xs = (tuple(x) if isinstance(x, list) else x for x in xs)

        if counts := Counter(xs).most_common():
            return counts[0][0]


def build_url_references(df):
    """Build canonical URL references for institutions."""
    tqdm.pandas(desc="Normalize URLs")
    refs = df.urls.progress_apply(normalize_urls)

    # Explode and groupby ie) url: [idx, idx, idx]
    refs = (
        refs.explode()
        .reset_index()
        .groupby(by="urls")
        .agg({"index": list})
        .reset_index()
    ).rename(columns={"index": "idxs", "urls": "ref"})

    tqdm.pandas(desc="Modal URL index")
    refs["idx"] = refs["idxs"].progress_apply(mode).astype("Int64")
    refs = refs[["idx", "ref"]]

    return refs


def build_name_references(df):
    """Build canonical name references for institutions."""
    tqdm.pandas(desc="Normalize names")
    refs = df.names.progress_apply(normalize_names)

    # Explode and groupby ie) name: [idx, idx, idx]
    refs = (
        refs.explode()
        .reset_index()
        .groupby(by="names")
        .agg({"index": list})
        .reset_index()
    ).rename(columns={"index": "idxs", "names": "ref"})

    tqdm.pandas(desc="Modal name index")
    refs["idx"] = refs["idxs"].progress_apply(mode).astype("Int64")
    refs = refs[["idx", "ref"]]

    return refs


def build_id_references(df, id_column):
    """Build references for institution IDs.
    (wikidata_id, ror_id, grid_id, unitid).
    """
    refs = df[df[id_column].notna()][id_column]
    refs = refs.reset_index()
    refs = refs.rename(columns={"index": "idx", id_column: "ref"})

    # For unitid, convert to string for the lookup table
    if id_column == 'unitid':
        refs['ref'] = refs['ref'].astype(str)

    refs = refs[["idx", "ref"]]

    # Drop both rows if there's a conflict
    refs = refs.drop_duplicates(subset=["ref"], keep=False)

    return refs


def build_table(df):
    """Build a key-value mapping of a variety of references
    to an institution index."""
    # Create references for all ID types and other attributes
    refs_list = [
        build_url_references(df),
        build_name_references(df),
    ]

    # Add all available ID columns for lookup
    for id_col in ['wikidata_id', 'ror_id', 'grid_id', 'unitid']:
        if id_col in df.columns:
            refs_list.append(build_id_references(df, id_col))

    refs = pd.concat(refs_list)

    # Create an array of institution data
    institutions = (
        df.drop(columns=["urls", "names"])
        .replace({pd.NA: None})
        .to_dict(orient="index")
    )

    # Convert to list for indexed access
    institutions_array = []
    for idx in sorted(institutions.keys()):
        institutions_array.append(institutions[idx])

    # Build a lookup table that maps references to indices in the array
    lookup_table = {}
    for _, row in tqdm(refs.iterrows(), desc="Build lookup table"):
        lookup_table[row.ref] = int(row.idx)

    return {"institutions": institutions_array, "lookup": lookup_table}


def main(
    input: Path | None = typer.Option(
        None, help="Institutions parquet (default: the dataset output)."
    ),
):
    input = input or artifact_path("dataset")
    with runs.start(STAGE) as run:
        run.add_input(input)
        df = loader.load(input)

        logger.info("Building institution lookup table")
        table = build_table(df)
        run.summarize(
            institutions=len(table["institutions"]),
            references=len(table["lookup"]),
        )

        output = artifact_path(STAGE)
        output.parent.mkdir(parents=True, exist_ok=True)
        format.save(table, output)
        logger.info(f"Wrote matcher to {output}")
        run.add_output(output)


if __name__ == "__main__":
    typer.run(main)
