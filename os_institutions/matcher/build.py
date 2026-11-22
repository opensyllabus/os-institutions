import pickle
from collections import Counter
from functools import partial
from itertools import chain
from operator import is_not

import pandas as pd
import wandb
from loguru import logger
from tqdm import tqdm

from os_institutions import dataset
from os_institutions.matcher import ARTIFACT_NAME
from os_institutions.normalizer.institution import normalize_school_name
from os_institutions.normalizer.uri import get_domain_url, get_full_url
from os_institutions.utils import wandb_artifact, wandb_init

not_na = partial(is_not, pd.NA)
not_none = partial(is_not, None)
not_empty = partial(is_not, "")


def read(name=ARTIFACT_NAME, use_artifact=False):
    logger.info(f"Loading {name}")

    file = wandb_artifact(name, use_artifact) + "/matcher.pickle"

    with open(file, "rb") as fh:
        return pickle.load(fh)


def normalize_urls(urls):
    full_urls = map(get_full_url, urls)
    domain_urls = map(get_domain_url, urls)
    urls = filter(not_none, chain(full_urls, domain_urls))
    return list(urls)


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


def main():
    wandb_init(group="matcher")

    df = dataset.load()

    logger.info("Building institution lookup table")
    table = build_table(df)

    artifact = wandb.Artifact(type="model", name="matcher")
    with artifact.new_file("matcher.pickle", "wb") as fh:
        pickle.dump(table, fh)
    wandb.log_artifact(artifact)


if __name__ == "__main__":
    main()
