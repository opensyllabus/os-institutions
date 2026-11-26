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

Pairs that share a domain but not a name, or that are ambiguous, get a second
look on Wikidata (the QLever mirror, `--no-wikidata` to skip). The name
check then also uses every label, alias, official name, short name and
predecessor or successor name of the ROR record's Wikidata item and of the
item that carries the IPEDS unitid (P1771), and an ambiguous pair is settled
when the ROR record's item names exactly one of the candidate unitids.

Anything else that shares a domain is reported but left alone. The flagged
pairs are appended to `os_institutions/data/extra_unitids.csv` with a `notes`
column that records why, so the next build links them like any other known
unitid; nothing is merged behind the scenes and the links are reviewable in
git.

    uv run scripts/find_duplicates.py [--input institutions.parquet]
"""

import re
import time
import urllib.error
from collections import defaultdict
from pathlib import Path

import pandas as pd
import typer
from loguru import logger
from os_normalizer.institution import normalize_school_name
from os_normalizer.uri import get_domain_url
from SPARQLWrapper import JSON, SPARQLWrapper

from os_institutions import load_dataset
from os_institutions.paths import DATA_DIR

REPORT_COLUMNS = [
    'decision',
    'reason',
    'notes',
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

# The QLever mirror of Wikidata (weekly), as in the wikidata_dist stage: WDQS
# throttles to one request a minute.
WIKIDATA = 'https://qlever.dev/api/wikidata'
WIKIDATA_AGENT = 'os-institutions-find-duplicates/0.1'
WIKIDATA_BATCH = 50
WIKIDATA_RETRIES = 5

# One Wikidata name per (item, kind, value) row.
NAMES_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?item ?ipeds ?kind ?value WHERE {
  %s
  { ?item rdfs:label ?value . BIND("label" AS ?kind) }
  UNION { ?item skos:altLabel ?value . BIND("alias" AS ?kind) }
  UNION { ?item wdt:P1448 ?value . BIND("official name" AS ?kind) }
  UNION { ?item wdt:P1813 ?value . BIND("short name" AS ?kind) }
  UNION { ?item wdt:P2561 ?value . BIND("name" AS ?kind) }
  UNION { ?item wdt:P1449 ?value . BIND("nickname" AS ?kind) }
  UNION {
    ?item (wdt:P1365|wdt:P1366) ?other .
    ?other rdfs:label ?value .
    FILTER(LANG(?value) = "en")
    BIND("predecessor or successor name" AS ?kind)
  }
  OPTIONAL { ?item wdt:P1771 ?ipeds }
}
"""


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


def _name_keys(row, extra=()):
    """Comparison keys of the row's names, each with `(name, source)`.

    The keys are the os-normalizer form, and a plain form that only ignores
    case, '&' versus 'and', and punctuation. `extra` adds `(source, name)`
    pairs, such as Wikidata aliases.
    """
    names = [
        ('dataset names', n)
        for n in _as_list(row['name']) + _as_list(row['names'])
    ]
    keys = {}
    for source, name in names + list(extra):
        plain = re.sub(r'[^a-z0-9]+', ' ', name.lower().replace('&', ' and '))
        for key in (normalize_school_name(name), plain.strip()):
            if key:
                keys.setdefault(key, (name, source))
    return keys


def _name_match(a_keys, b_keys):
    """`(ipeds name, ror name, source)` of a shared name, else None."""
    shared = sorted(a_keys.keys() & b_keys.keys())
    if not shared:
        return None
    # Prefer a match that needs no Wikidata.
    shared.sort(key=lambda k: 'Wikidata' in a_keys[k][1] + b_keys[k][1])
    key = shared[0]
    source = ' / '.join(
        sorted({a_keys[key][1], b_keys[key][1]} - {'dataset names'})
        or ['dataset names']
    )
    return a_keys[key][0], b_keys[key][0], source


def _same_place(a, b):
    """Same country, and the same state for US institutions."""
    if _missing(a['country_code']) or a['country_code'] != b['country_code']:
        return False
    if a['country_code'] != 'US':
        return True
    if _missing(a['state_code']) or _missing(b['state_code']):
        return False
    return a['state_code'] == b['state_code']


def wikidata_lookup(qids, unitids):
    """Names and unitids Wikidata holds for ROR items and IPEDS unitids.

    Returns `(by_qid, by_unitid, unitids_of_qid)`: `(source, name)` lists
    keyed by Wikidata id and by unitid, and the P1771 unitids of each item.
    """
    sparql = SPARQLWrapper(WIKIDATA, agent=WIKIDATA_AGENT)
    sparql.setReturnFormat(JSON)

    def fetch(bind):
        sparql.setQuery(NAMES_QUERY % bind)
        for attempt in range(1, WIKIDATA_RETRIES + 1):
            try:
                return sparql.query().convert()['results']['bindings']
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == WIKIDATA_RETRIES:
                    raise
                time.sleep(5 * attempt)

    by_qid = defaultdict(list)
    by_unitid = defaultdict(list)
    unitids_of_qid = defaultdict(set)
    qids, unitids = sorted(qids), sorted(unitids)
    batches = []
    for i in range(0, len(qids), WIKIDATA_BATCH):
        items = ' '.join(f'wd:{q}' for q in qids[i : i + WIKIDATA_BATCH])
        batches.append(f'VALUES ?item {{ {items} }}')
    for i in range(0, len(unitids), WIKIDATA_BATCH):
        ids = ' '.join(f'"{u}"' for u in unitids[i : i + WIKIDATA_BATCH])
        batches.append(f'VALUES ?ipeds {{ {ids} }} ?item wdt:P1771 ?ipeds .')
    for bind in batches:
        try:
            rows = fetch(bind)
        except Exception as e:  # network or WDQS limits: degrade, don't crash
            logger.warning(f'Wikidata lookup failed: {e}')
            continue
        for row in rows:
            qid = row['item']['value'].rsplit('/', 1)[-1]
            entry = (f'Wikidata {row["kind"]["value"]}', row['value']['value'])
            by_qid[qid].append(entry)
            if 'ipeds' in row:
                unitid = row['ipeds']['value']
                by_unitid[unitid].append(entry)
                unitids_of_qid[qid].add(unitid)
    return by_qid, by_unitid, unitids_of_qid


def find_duplicates(df, lookup=None):
    """Classify every (IPEDS-only, ROR-only) pair that shares a domain.

    Returns a list of `(ipeds_index, ror_index, decision, reason, notes)`,
    where the decision is 'merge' or 'skip'. `lookup` is `wikidata_lookup` or
    a stand-in; without it Wikidata is not consulted.
    """
    ipeds_only = df[df['unitid'].notna() & df['ror_id'].isna()]
    ror_only = df[df['ror_id'].notna() & df['unitid'].isna()]

    by_domain = defaultdict(list)
    for idx, row in ror_only.iterrows():
        for domain in _domains(row):
            by_domain[domain].append(idx)

    pairs = {}  # (ipeds idx, ror idx) -> (reason or None, notes)
    for i, a in ipeds_only.iterrows():
        a_keys = _name_keys(a)
        domains = _domains(a)
        candidates = {j for d in domains for j in by_domain.get(d, ())}
        for j in sorted(candidates):
            b = ror_only.loc[j]
            shared = min(domains & _domains(b))
            match = _name_match(a_keys, _name_keys(b))
            pairs[(i, j)] = _judge(a, b, match, shared)

    if lookup:
        pairs = _second_look(df, pairs, lookup)

    n_ipeds = defaultdict(int)
    n_ror = defaultdict(int)
    for (i, j), (reason, _) in pairs.items():
        if reason is None:
            n_ipeds[i] += 1
            n_ror[j] += 1

    out = []
    for (i, j), (reason, notes) in pairs.items():
        if reason is not None:
            out.append((i, j, 'skip', reason, notes))
        elif n_ipeds[i] > 1 or n_ror[j] > 1:
            out.append((i, j, 'skip', 'ambiguous: several candidates', notes))
        else:
            out.append((i, j, 'merge', 'same domain, name and place', notes))
    return out


def _judge(a, b, match, domain):
    """`(skip reason or None, notes)` of one candidate pair."""
    if not match:
        return 'name differs', ''
    if not _same_place(a, b):
        return 'state or country differs', ''
    ipeds_name, ror_name, source = match
    place = b['state_code'] if b['country_code'] == 'US' else b['country_code']
    return None, (
        f"Same domain {domain} and place {place}; "
        f"IPEDS '{ipeds_name}' = ROR '{ror_name}' ({source})"
    )


def _second_look(df, pairs, lookup):
    """Re-judge name mismatches and ambiguities with Wikidata names."""
    good = defaultdict(set)  # ror idx -> ipeds idx with a name match
    for (i, j), (reason, _) in pairs.items():
        if reason is None:
            good[j].add(i)
    retry = {
        (i, j)
        for (i, j), (reason, _) in pairs.items()
        if reason == 'name differs' or len(good[j]) > 1
    }
    if not retry:
        return pairs

    by_qid, by_unitid, unitids_of_qid = lookup(
        {df.at[j, 'wikidata_id'] for _, j in retry} - {pd.NA, None},
        {str(int(df.at[i, 'unitid'])) for i, _ in retry},
    )
    out = dict(pairs)
    for i, j in retry:
        a, b = df.loc[i], df.loc[j]
        unitid = str(int(a['unitid']))
        qid = b['wikidata_id']
        if pairs[(i, j)][0] == 'name differs':
            match = _name_match(
                _name_keys(a, by_unitid.get(unitid, ())),
                _name_keys(b, by_qid.get(qid, ())),
            )
            domain = min(_domains(a) & _domains(b))
            out[(i, j)] = _judge(a, b, match, domain)
    # An ambiguous ROR record is settled when its Wikidata item names exactly
    # one of the candidate unitids (P1771).
    for j, ipeds_idx in good.items():
        if len(ipeds_idx) < 2:
            continue
        qid = df.at[j, 'wikidata_id']
        named = {
            i
            for i in ipeds_idx
            if str(int(df.at[i, 'unitid'])) in unitids_of_qid.get(qid, ())
        }
        if len(named) == 1:
            keep = named.pop()
            for i in ipeds_idx - {keep}:
                out[(i, j)] = (
                    'ambiguous: Wikidata names another unitid',
                    '',
                )
            reason, notes = out[(keep, j)]
            out[(keep, j)] = (
                reason,
                notes
                + f'; Wikidata {qid} lists unitid {df.at[keep, "unitid"]}',
            )
    return out


def report_duplicates(df, lookup=None):
    """One row per candidate pair, merge or skip, for audit."""
    df = df.reset_index(drop=True)
    rows = []
    for i, j, decision, reason, notes in find_duplicates(df, lookup):
        a, b = df.loc[i], df.loc[j]
        rows.append(
            {
                'decision': decision,
                'reason': reason,
                'notes': notes,
                'unitid': a['unitid'],
                'ipeds_name': a['name'],
                'ipeds_url': a['url'],
                'ror_id': b['ror_id'],
                'wikidata_id': b['wikidata_id'],
                'ror_name': b['name'],
                'ror_url': b['url'],
                'domain': min(_domains(a) & _domains(b)),
                'state_code': b['state_code'],
            }
        )
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def new_extra_unitids(report, extra):
    """The (ror_id, unitid, notes) rows of the merge pairs not yet in `extra`.

    A pair is dropped when its ror_id or unitid is already linked, so an
    existing (manual) link is never overridden or duplicated.
    """
    merges = report[report['decision'] == 'merge']
    new = merges[
        ~merges['ror_id'].isin(extra['ror_id'])
        & ~merges['unitid'].isin(extra['unitid'])
    ]
    out = new[['ror_id', 'unitid', 'notes']].astype({'unitid': 'int64'})
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
    wikidata: bool = typer.Option(
        True, help='Check name mismatches and ambiguities on Wikidata.'
    ),
):
    df = pd.read_parquet(input) if input else load_dataset()
    pairs = report_duplicates(df, wikidata_lookup if wikidata else None)
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
