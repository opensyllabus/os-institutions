"""Find IPEDS-only records that duplicate a ROR record, and link them.

`dataset.merge_ipeds` links an IPEDS institution to a ROR record only through
a known unitid (Wikidata's P-number or `extra_unitids.csv`). When that link is
missing, the ROR record keeps `unitid = NA` and the IPEDS institution is added
as a second, ROR-less row, so one institution ends up as two records, each
with half the identifiers. The matcher then resolves a URL or name shared by
both to an arbitrary one of them (`matcher.build.mode`).

`find_duplicates` flags such a pair when, and only when, all of these hold:

* the IPEDS row has a unitid and no ror_id; the other row has a ror_id and no
  unitid;
* the IPEDS website and a ROR or Wikidata website share the same normalized
  domain;
* the IPEDS name equals, once normalized (case, '&', punctuation), one of
  the other row's names (ROR name or alias, Wikidata name or label,
  Wikipedia title);
* the country, and for the US the state, agree;
* the pairing is one to one: no other candidate qualifies for either row.

Anything else that shares a domain is reported but left alone.

`python -m os_institutions.duplicates` runs this on a built dataset and
appends the flagged pairs to `data/extra_unitids.csv` (ror_id, unitid). The
next build then joins the IPEDS row to the ROR record like any other known
unitid, so nothing is merged behind the scenes and the links are reviewable
in git.
"""

import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
import typer
from loguru import logger
from os_normalizer.institution import normalize_school_name
from os_normalizer.uri import get_domain_url

from os_institutions.paths import DATA_DIR, artifact_path

NON_STATE_STABBR = ('FM', 'MH', 'PW')

REPORT_COLUMNS = [
    'decision',
    'reason',
    'unitid',
    'ipeds_name',
    'ipeds_url',
    'ror_id',
    'wikidata_id',
    'other_name',
    'other_url',
    'domain',
    'state',
]


def _missing(value):
    if isinstance(value, (list, tuple)):
        return False
    return value is None or bool(pd.isna(value))


def _as_list(value):
    if _missing(value):
        return []
    if isinstance(value, (list, tuple)):
        return [v for v in value if not _missing(v)]
    if hasattr(value, 'tolist'):
        return [v for v in value.tolist() if not _missing(v)]
    return [value]


def _domain(url):
    if _missing(url) or not url:
        return None
    return get_domain_url(url)


def _name_keys(name):
    """Comparison keys of a name: the os-normalizer form, and a plain form
    that only ignores case, '&' versus 'and', and punctuation."""
    if _missing(name) or not name:
        return set()
    plain = re.sub(r'[^a-z0-9]+', ' ', name.lower().replace('&', ' and '))
    keys = {normalize_school_name(name), plain.strip()}
    return {k for k in keys if k}


def _ipeds_country(row):
    return (
        row['ipeds_stabbr']
        if row['ipeds_stabbr'] in NON_STATE_STABBR
        else 'US'
    )


def _ror_domains(row):
    return {
        d
        for d in (
            _domain(row.get('ror_url')),
            _domain(row.get('wikidata_url')),
        )
        if d
    }


def _ror_names(row):
    names = [row.get('ror_name'), row.get('wikidata_name')]
    names += _as_list(row.get('ror_aliases'))
    names += _as_list(row.get('wikidata_labels'))
    names.append(row.get('wikipedia_title'))
    return set().union(*map(_name_keys, names))


def _same_place(ipeds, ror):
    """Same country, and the same state for US institutions."""
    country = _ipeds_country(ipeds)
    if ror.get('ror_country_code') != country:
        return False
    if country != 'US':
        return True
    state = ror.get('ror_state_code')
    return not _missing(state) and state == f'US-{ipeds["ipeds_stabbr"]}'


def find_duplicates(df):
    """Classify every (IPEDS-only, ROR-only) pair that shares a domain.

    Returns a list of `(ipeds_index, ror_index, decision, reason)`, where the
    decision is 'merge' or 'skip'.
    """
    ipeds_only = df[df['unitid'].notna() & df['ror_id'].isna()]
    ror_only = df[df['ror_id'].notna() & df['unitid'].isna()]

    by_domain = defaultdict(list)
    for idx, row in ror_only.iterrows():
        for domain in _ror_domains(row):
            by_domain[domain].append(idx)

    pairs = {}  # (ipeds idx, ror idx) -> (domain, reason or None)
    for i, a in ipeds_only.iterrows():
        domain = _domain(a['ipeds_webaddr'])
        if not domain:
            continue
        a_keys = _name_keys(a['ipeds_instnm'])
        for j in by_domain.get(domain, ()):
            b = ror_only.loc[j]
            if not a_keys & _ror_names(b):
                reason = 'name differs'
            elif not _same_place(a, b):
                reason = 'state or country differs'
            else:
                reason = None
            pairs[(i, j)] = reason

    good = [pair for pair, reason in pairs.items() if reason is None]
    n_ror = defaultdict(int)
    n_ipeds = defaultdict(int)
    for i, j in good:
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
        rows.append(
            {
                'decision': decision,
                'reason': reason,
                'unitid': a['unitid'],
                'ipeds_name': a['ipeds_instnm'],
                'ipeds_url': a['ipeds_webaddr'],
                'ror_id': b['ror_id'],
                'wikidata_id': b['wikidata_id'],
                'other_name': b['ror_name'],
                'other_url': b['ror_url'],
                'domain': _domain(a['ipeds_webaddr']),
                'state': b['ror_state_code'],
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
def find(
    input: Path = typer.Option(None, help='Dataset parquet to scan.'),
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
    """Add IPEDS/ROR duplicates of a built dataset to extra unitids."""
    df = pd.read_parquet(input or artifact_path('dataset'))
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
