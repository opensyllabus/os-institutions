import pandas as pd

from os_institutions.duplicates import find_duplicates, merge_duplicates

COLUMNS = [
    'unitid',
    'ror_id',
    'wikidata_id',
    'grid_id',
    'ror_name',
    'ror_url',
    'ror_aliases',
    'ror_state_code',
    'ror_country_code',
    'wikidata_url',
    'wikidata_name',
    'wikidata_labels',
    'wikipedia_title',
    'ipeds_unitid',
    'ipeds_instnm',
    'ipeds_webaddr',
    'ipeds_stabbr',
    'ipeds_ialias',
    'ipeds_c21basic',
]


def frame(*rows):
    data = [{c: pd.NA for c in COLUMNS} | row for row in rows]
    return pd.DataFrame(data, columns=COLUMNS).astype(object)


def ipeds(unitid, name, url, state='NE', **kw):
    return {
        'unitid': unitid,
        'ipeds_unitid': unitid,
        'ipeds_instnm': name,
        'ipeds_webaddr': url,
        'ipeds_stabbr': state,
        'ipeds_c21basic': 3,
    } | kw


def ror(ror_id, name, url, state='US-NE', country='US', **kw):
    return {
        'ror_id': ror_id,
        'ror_name': name,
        'ror_url': url,
        'ror_state_code': state,
        'ror_country_code': country,
    } | kw


def test_merges_pair_and_keeps_all_ids():
    df = frame(
        ror(
            '05x0zqa09',
            'Northeast Community College',
            'https://www.northeast.edu/',
            wikidata_id='Q1',
            grid_id='grid.1',
        ),
        ipeds(181491, 'Northeast Community College', 'https://northeast.edu/'),
    )
    out, report = merge_duplicates(df)

    assert len(out) == 1
    row = out.iloc[0]
    assert row['ror_id'] == '05x0zqa09'
    assert row['wikidata_id'] == 'Q1'
    assert row['grid_id'] == 'grid.1'
    assert row['unitid'] == 181491
    assert row['ipeds_instnm'] == 'Northeast Community College'
    assert row['ror_name'] == 'Northeast Community College'
    assert list(report['decision']) == ['merge']


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
            state='CA',
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
            state='CA',
        ),
    )
    out, _ = merge_duplicates(df)
    assert len(out) == 2
    assert out['unitid'].notna().all() and out['ror_id'].notna().all()


def test_name_match_uses_aliases():
    df = frame(
        ror('r1', 'Universidad X', 'https://x.edu', ror_aliases=['X College']),
        ipeds(1, 'X College', 'https://x.edu'),
    )
    out, _ = merge_duplicates(df)
    assert len(out) == 1


def test_different_name_is_not_merged():
    df = frame(
        ror('r1', 'University of Nebraska System', 'https://nebraska.edu'),
        ipeds(
            1,
            'University of Nebraska-Central Administration',
            'https://nebraska.edu',
        ),
    )
    out, report = merge_duplicates(df)
    assert len(out) == 2
    assert list(report['decision']) == ['skip']
    assert report['reason'][0] == 'name differs'


def test_different_state_or_country_is_not_merged():
    df = frame(
        ror('r1', 'Same College', 'https://same.edu', state='US-NE'),
        ipeds(1, 'Same College', 'https://same.edu', state='IA'),
        ror(
            'r2',
            'Other College',
            'https://other.edu',
            country='CA',
            state='CA-ON',
        ),
        ipeds(2, 'Other College', 'https://other.edu', state='NE'),
    )
    out, report = merge_duplicates(df)
    assert len(out) == 4
    assert set(report['reason']) == {'state or country differs'}


def test_missing_ror_state_is_not_merged():
    df = frame(
        ror('r1', 'Same College', 'https://same.edu', state=pd.NA),
        ipeds(1, 'Same College', 'https://same.edu'),
    )
    out, _ = merge_duplicates(df)
    assert len(out) == 2


def test_different_domain_is_not_merged():
    df = frame(
        ror('r1', 'Same College', 'https://same.edu'),
        ipeds(1, 'Same College', 'https://elsewhere.edu'),
    )
    out, report = merge_duplicates(df)
    assert len(out) == 2
    assert report.empty


def test_matches_wikidata_url():
    df = frame(
        ror('r1', 'Same College', pd.NA, wikidata_url='https://same.edu/'),
        ipeds(1, 'Same College', 'https://www.same.edu'),
    )
    out, _ = merge_duplicates(df)
    assert len(out) == 1


def test_ambiguous_candidates_are_not_merged():
    df = frame(
        ror('r1', 'Unitek College', 'https://unitek.edu'),
        ror('r2', 'Unitek College', 'https://unitek.edu'),
        ipeds(1, 'Unitek College', 'https://unitek.edu'),
        ipeds(2, 'Unitek College', 'https://unitek.edu'),
    )
    out, report = merge_duplicates(df)
    assert len(out) == 4
    assert set(report['reason']) == {'ambiguous: several candidates'}


def test_campuses_sharing_a_domain_stay_separate():
    df = frame(
        ror('r1', 'SJVC Visalia', 'https://sjvc.edu'),
        ror('r2', 'SJVC Bakersfield', 'https://sjvc.edu'),
        ipeds(1, 'SJVC Visalia', 'https://sjvc.edu'),
        ipeds(2, 'SJVC Bakersfield', 'https://sjvc.edu'),
    )
    out, _ = merge_duplicates(df)
    assert len(out) == 2
    assert out['unitid'].notna().all()
    assert out.set_index('ror_name')['unitid'].to_dict() == {
        'SJVC Visalia': 1,
        'SJVC Bakersfield': 2,
    }


def test_records_that_already_have_both_ids_are_untouched():
    df = frame(
        ror('r1', 'Same College', 'https://same.edu', unitid=5),
        ipeds(1, 'Same College', 'https://same.edu'),
    )
    out, report = merge_duplicates(df)
    assert len(out) == 2
    assert report.empty


def test_merged_ids_stay_unique():
    df = frame(
        ror('r1', 'A College', 'https://a.edu', wikidata_id='Q1'),
        ipeds(1, 'A College', 'https://a.edu'),
        ror('r2', 'B College', 'https://b.edu', wikidata_id='Q2'),
        ipeds(2, 'B College', 'https://b.edu'),
    )
    out, _ = merge_duplicates(df)
    for col in ('unitid', 'ror_id', 'wikidata_id'):
        assert out[col].is_unique


def test_find_duplicates_empty():
    assert find_duplicates(frame()) == []
