"""Find IPEDS-only records that duplicate a ROR record, and link them.

The dataset build links an IPEDS institution to a ROR record only through a
known unitid (Wikidata's P-number or `extra_unitids.csv`). When that link is
missing, the ROR record keeps `unitid = NA` and the IPEDS institution is added
as a second, ROR-less row, so one institution ends up as two records, each
with half the identifiers. The matcher then resolves a URL or name shared by
both to an arbitrary one of them (`matcher.build.mode`).

This script reads a built dataset (default: the latest release) and flags a
pair when, and only when, all of these hold:

* one row has a unitid and no ror_id, the other a ror_id and no unitid;
* they share a normalized website domain;
* they share a name, once normalized (case, '&', punctuation);
* the country, and for the US the state, agree;
* the pairing is one to one: no other candidate qualifies for either row.

Anything else that shares a domain is reported but left alone. The flagged
pairs are appended to `os_institutions/data/extra_unitids.csv`, so the next
build links them like any other known unitid; nothing is merged behind the
scenes and the links are reviewable in git.

    uv run scripts/find_duplicates.py [--input institutions.parquet]
"""

import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
import typer
from loguru import logger
from os_normalizer.institution import normalize_school_name
from os_normalizer.uri import get_domain_url

from os_institutions import load_dataset
from os_institutions.paths import DATA_DIR

REPORT_COLUMNS = [
    'decision',
    'reason',
    'unitid',
    'ipeds_name',
    'ipeds_url',
    'ror_id',
    'wikidata_id',
    'ror_name',
    'ror_url',
    'domain',
    'state_code',
]


def _missing(value):
    if isinstance(value, (list, tuple)) or hasattr(value, 'tolist'):
        return False
    return value is None or bool(pd.isna(value))


def _as_list(value):
    if _missing(value):
        return []
    if hasattr(value, 'tolist'):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return [v for v in value if not _missing(v)]
    return [value]


def _domains(row):
    """Normalized domains of the row's url and urls."""
    urls = _as_list(row['url']) + _as_list(row['urls'])
    return {d for d in map(get_domain_url, urls) if d}


def _name_keys(row):
    """Comparison keys of the row's names: the os-normalizer form, and a
    plain form that only ignores case, '&' versus 'and', and punctuation."""
    keys = set()
    for name in _as_list(row['name']) + _as_list(row['names']):
        plain = re.sub(r'[^a-z0-9]+', ' ', name.lower().replace('&', ' and '))
        keys |= {normalize_school_name(name), plain.strip()}
    return {k for k in keys if k}


def _same_place(a, b):
    """Same country, and the same state for US institutions."""
    if _missing(a['country_code']) or a['country_code'] != b['country_code']:
        return False
    if a['country_code'] != 'US':
        return True
    if _missing(a['state_code']) or _missing(b['state_code']):
        return False
    return a['state_code'] == b['state_code']


def find_duplicates(df):
    """Classify every (IPEDS-only, ROR-only) pair that shares a domain.

    Returns a list of `(ipeds_index, ror_index, decision, reason)`, where the
    decision is 'merge' or 'skip'.
    """
    ipeds_only = df[df['unitid'].notna() & df['ror_id'].isna()]
    ror_only = df[df['ror_id'].notna() & df['unitid'].isna()]

    by_domain = defaultdict(list)
    for idx, row in ror_only.iterrows():
        for domain in _domains(row):
            by_domain[domain].append(idx)

    pairs = {}  # (ipeds idx, ror idx) -> skip reason, or None to merge
    for i, a in ipeds_only.iterrows():
        a_keys = _name_keys(a)
        candidates = {j for d in _domains(a) for j in by_domain.get(d, ())}
        for j in sorted(candidates):
            b = ror_only.loc[j]
            if not a_keys & _name_keys(b):
                reason = 'name differs'
            elif not _same_place(a, b):
                reason = 'state or country differs'
            else:
                reason = None
            pairs[(i, j)] = reason

    n_ipeds = defaultdict(int)
    n_ror = defaultdict(int)
    for (i, j), reason in pairs.items():
        if reason is None:
            n_ipeds[i] += 1
            n_ror[j] += 1

    out = []
    for (i, j), reason in pairs.items():
        if reason is not None:
            out.append((i, j, 'skip', reason))
        elif n_ipeds[i] > 1 or n_ror[j] > 1:
            out.append((i, j, 'skip', 'ambiguous: several candidates'))
        else:
            out.append((i, j, 'merge', 'same domain, name and place'))
    return out


def report_duplicates(df):
    """One row per candidate pair, merge or skip, for audit."""
    df = df.reset_index(drop=True)
    rows = []
    for i, j, decision, reason in find_duplicates(df):
        a, b = df.loc[i], df.loc[j]
        shared = _domains(a) & _domains(b)
        rows.append(
            {
                'decision': decision,
                'reason': reason,
                'unitid': a['unitid'],
                'ipeds_name': a['name'],
                'ipeds_url': a['url'],
                'ror_id': b['ror_id'],
                'wikidata_id': b['wikidata_id'],
                'ror_name': b['name'],
                'ror_url': b['url'],
                'domain': min(shared),
                'state_code': b['state_code'],
            }
        )
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def new_extra_unitids(report, extra):
    """The (ror_id, unitid) rows of the merge pairs not yet in `extra`.

    A pair is dropped when its ror_id or unitid is already linked, so an
    existing (manual) link is never overridden or duplicated.
    """
    merges = report[report['decision'] == 'merge']
    new = merges[
        ~merges['ror_id'].isin(extra['ror_id'])
        & ~merges['unitid'].isin(extra['unitid'])
    ]
    out = new[['ror_id', 'unitid']].astype({'unitid': 'int64'})
    return out.sort_values('unitid').reset_index(drop=True)


app = typer.Typer()


@app.command()
def main(
    input: Path = typer.Option(
        None, help='Dataset parquet to scan. Default: the latest release.'
    ),
    extra: Path = typer.Option(
        DATA_DIR / 'extra_unitids.csv', help='extra_unitids.csv to extend.'
    ),
    report: Path = typer.Option(
        None, help='Where to write every candidate pair as CSV.'
    ),
    write: bool = typer.Option(
        True, help='Append the new links to extra_unitids.csv.'
    ),
):
    df = pd.read_parquet(input) if input else load_dataset()
    pairs = report_duplicates(df)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        pairs.to_csv(report, index=False)

    current = pd.read_csv(extra)
    new = new_extra_unitids(pairs, current)
    logger.info(
        f'{len(pairs)} candidate pairs, '
        f'{(pairs["decision"] == "merge").sum()} to merge, '
        f'{len(new)} new links'
    )
    if write and len(new):
        pd.concat([current, new]).to_csv(extra, index=False)


if __name__ == '__main__':
    app()
