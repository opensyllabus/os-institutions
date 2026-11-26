import importlib.util
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location(
    'find_duplicates',
    Path(__file__).parent.parent / 'scripts' / 'find_duplicates.py',
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
find_duplicates = mod.find_duplicates
new_extra_unitids = mod.new_extra_unitids
report_duplicates = mod.report_duplicates

COLUMNS = [
    'unitid',
    'ror_id',
    'wikidata_id',
    'name',
    'names',
    'url',
    'urls',
    'country_code',
    'state_code',
]


def frame(*rows):
    data = [{c: pd.NA for c in COLUMNS} | row for row in rows]
    return pd.DataFrame(data, columns=COLUMNS).astype(object)


def ipeds(unitid, name, url, state='US-NE', **kw):
    return {
        'unitid': unitid,
        'name': name,
        'names': [name],
        'url': url,
        'urls': [url],
        'country_code': 'US',
        'state_code': state,
    } | kw


def ror(ror_id, name, url, state='US-NE', country='US', **kw):
    return {
        'ror_id': ror_id,
        'name': name,
        'names': [name],
        'url': url,
        'urls': [url] if isinstance(url, str) else [],
        'country_code': country,
        'state_code': state,
    } | kw


def links(df):
    """The (ror_id -> unitid) links the duplicates report would add."""
    new = new_extra_unitids(
        report_duplicates(df), pd.DataFrame({'ror_id': [], 'unitid': []})
    )
    return dict(zip(new['ror_id'], new['unitid']))


def test_links_pair():
    df = frame(
        ror(
            '05x0zqa09',
            'Northeast Community College',
            'https://www.northeast.edu/',
        ),
        ipeds(181491, 'Northeast Community College', 'https://northeast.edu/'),
    )
    assert links(df) == {'05x0zqa09': 181491}
    assert list(report_duplicates(df)['decision']) == ['merge']


def test_name_match_ignores_punctuation_and_ampersand():
    df = frame(
        ror(
            'r1',
            'Grossmont Cuyamaca Community College District',
            'https://gcccd.edu',
            state='US-CA',
        ),
        ipeds(
            1,
            'Grossmont-Cuyamaca Community College District',
            'http://www.gcccd.edu/',
            state='US-CA',
        ),
        ror(
            'r2',
            'Acupuncture & Integrative Medicine College',
            'https://aimc.edu',
            state='US-CA',
        ),
        ipeds(
            2,
            'Acupuncture and Integrative Medicine College',
            'https://aimc.edu',
            state='US-CA',
        ),
    )
    assert links(df) == {'r1': 1, 'r2': 2}


def test_name_match_uses_aliases():
    df = frame(
        ror(
            'r1',
            'Universidad X',
            'https://x.edu',
            names=['Universidad X', 'X College'],
        ),
        ipeds(1, 'X College', 'https://x.edu'),
    )
    assert links(df) == {'r1': 1}


def test_different_name_is_not_linked():
    df = frame(
        ror('r1', 'University of Nebraska System', 'https://nebraska.edu'),
        ipeds(
            1,
            'University of Nebraska-Central Administration',
            'https://nebraska.edu',
        ),
    )
    report = report_duplicates(df)
    assert links(df) == {}
    assert list(report['decision']) == ['skip']
    assert report['reason'][0] == 'name differs'


def test_different_state_or_country_is_not_linked():
    df = frame(
        ror('r1', 'Same College', 'https://same.edu', state='US-NE'),
        ipeds(1, 'Same College', 'https://same.edu', state='US-IA'),
        ror(
            'r2',
            'Other College',
            'https://other.edu',
            country='CA',
            state='CA-ON',
        ),
        ipeds(2, 'Other College', 'https://other.edu'),
    )
    assert links(df) == {}
    assert set(report_duplicates(df)['reason']) == {'state or country differs'}


def test_missing_ror_state_is_not_linked():
    df = frame(
        ror('r1', 'Same College', 'https://same.edu', state=pd.NA),
        ipeds(1, 'Same College', 'https://same.edu'),
    )
    assert links(df) == {}


def test_different_domain_is_not_linked():
    df = frame(
        ror('r1', 'Same College', 'https://same.edu'),
        ipeds(1, 'Same College', 'https://elsewhere.edu'),
    )
    assert report_duplicates(df).empty


def test_matches_any_url():
    df = frame(
        ror('r1', 'Same College', pd.NA, urls=['https://same.edu/']),
        ipeds(1, 'Same College', 'https://www.same.edu'),
    )
    assert links(df) == {'r1': 1}


def test_ambiguous_candidates_are_not_linked():
    df = frame(
        ror('r1', 'Unitek College', 'https://unitek.edu'),
        ror('r2', 'Unitek College', 'https://unitek.edu'),
        ipeds(1, 'Unitek College', 'https://unitek.edu'),
        ipeds(2, 'Unitek College', 'https://unitek.edu'),
    )
    assert links(df) == {}
    assert set(report_duplicates(df)['reason']) == {
        'ambiguous: several candidates'
    }


def test_campuses_sharing_a_domain_link_by_name():
    df = frame(
        ror('r1', 'SJVC Visalia', 'https://sjvc.edu'),
        ror('r2', 'SJVC Bakersfield', 'https://sjvc.edu'),
        ipeds(1, 'SJVC Visalia', 'https://sjvc.edu'),
        ipeds(2, 'SJVC Bakersfield', 'https://sjvc.edu'),
    )
    assert links(df) == {'r1': 1, 'r2': 2}


def test_records_that_already_have_both_ids_are_untouched():
    df = frame(
        ror('r1', 'Same College', 'https://same.edu', unitid=5),
        ipeds(1, 'Same College', 'https://same.edu'),
    )
    assert report_duplicates(df).empty


def test_existing_extra_unitids_are_kept():
    df = frame(
        ror('r1', 'A College', 'https://a.edu'),
        ipeds(1, 'A College', 'https://a.edu'),
        ror('r2', 'B College', 'https://b.edu'),
        ipeds(2, 'B College', 'https://b.edu'),
    )
    extra = pd.DataFrame({'ror_id': ['r1'], 'unitid': [9]})
    new = new_extra_unitids(report_duplicates(df), extra)
    assert dict(zip(new['ror_id'], new['unitid'])) == {'r2': 2}


def test_find_duplicates_empty():
    assert find_duplicates(frame()) == []
