import pandas as pd

from os_institutions.dataset import (
    combine_url_lists,
    get_country,
    get_country_code,
    get_enrollment,
    get_extra_enrollment,
    get_state,
    get_state_code,
    get_url,
)


def test_get_country_code():
    df = pd.DataFrame(
        {
            'ror_country_code': ['KR', pd.NA, pd.NA, pd.NA],
            'ipeds_stabbr': [pd.NA, 'NY', 'FM', pd.NA],
            'unitid': [pd.NA, 1, 2, pd.NA],
        },
        dtype='string',
    )
    res = pd.Series(['KR', 'US', 'FM', pd.NA], dtype='string')

    assert (res == get_country_code(df)).all()


def test_get_country():
    df = pd.DataFrame(
        {
            'ror_country_name': ['Republic of Korea', pd.NA, pd.NA, pd.NA],
            'ipeds_stabbr': [pd.NA, 'NY', 'FM', pd.NA],
            'unitid': [pd.NA, 1, 2, pd.NA],
        },
        dtype='string',
    )
    res = pd.Series(
        [
            'Republic of Korea',
            'United States',
            'Federated States of Micronesia',
            pd.NA,
        ],
        dtype='string',
    )

    assert (res == get_country(df)).all()


def test_get_state_code():
    df = pd.DataFrame(
        {
            'ror_state_code': ['KR', pd.NA, pd.NA, pd.NA],
            'ipeds_stabbr': [pd.NA, 'NY', 'FM', pd.NA],
        },
        dtype='string',
    )
    res = pd.Series(['KR', 'US-NY', 'FM', pd.NA], dtype='string')

    assert (res == get_state_code(df)).all()


def test_get_state():
    df = pd.DataFrame(
        {
            'state_code': ['KR', 'US-NY', 'FM', pd.NA, pd.NA],
            'ror_state': [pd.NA, pd.NA, pd.NA, pd.NA, 'New York'],
        },
        dtype='string',
    )
    res = pd.Series(
        [pd.NA, 'New York', pd.NA, pd.NA, 'New York'], dtype='string'
    )

    assert (res == get_state(df)).all()


def test_get_url():
    df = pd.DataFrame(
        {
            'ror_url': [
                'http://example.com',
                'http://example.com/a',
                pd.NA,
                pd.NA,
                pd.NA,
                pd.NA,
            ],
            'ipeds_webaddr': [
                pd.NA,
                pd.NA,
                pd.NA,
                'http://example.com/ipeds',
                pd.NA,
                pd.NA,
            ],
            'wikidata_url': [
                pd.NA,
                pd.NA,
                pd.NA,
                pd.NA,
                'http://example.com/wikidata',
                pd.NA,
            ],
        }
    )
    res = pd.Series(
        [
            'http://example.com',
            'http://example.com/a',
            pd.NA,
            'http://example.com/ipeds',
            'http://example.com/wikidata',
            pd.NA,
        ],
        dtype='string',
    )

    assert (res == get_url(df)).all()


def test_get_extra_enrollment():
    # XXX: Use extra_file fixture to prevent test from failing
    # due to changes in the extra_file.
    df = pd.DataFrame(
        {'ror_id': ['00839we02', '0131d6623']},
        dtype='string',
    )
    extra = get_extra_enrollment(df)

    assert df.index.size == extra.index.size
    assert extra.notna().all()
    assert extra.dtype == 'Int64'


def test_get_enrollment():
    df = pd.DataFrame(
        {
            'ipeds_efytotlt': [1, pd.NA, pd.NA, pd.NA],
            'wikidata_enrollment': [2, 2, pd.NA, pd.NA],
            'extra_enrollment': [3, 3, 3, pd.NA],
        },
        dtype='Int64',
    )
    res = pd.Series([1, 2, 3, pd.NA], dtype='Int64')

    assert (res == get_enrollment(df)).all()
    assert res.dtype == 'Int64'


def test_combine_url_lists_dedupes_in_stable_order():
    res = combine_url_lists(
        ['http://b/', 'http://a/'], ['http://a/', 'http://c/']
    )

    assert res == ['http://b/', 'http://a/', 'http://c/']
    assert combine_url_lists(pd.NA, pd.NA) is pd.NA
    assert combine_url_lists(['http://a/'], pd.NA) == ['http://a/']
