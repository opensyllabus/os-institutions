import pytest

from os_institutions.sources.ror_dist import (
    get_file_name,
    get_record_id,
    select_file_url,
)


def link(record, name):
    return f'https://zenodo.org/api/records/{record}/files/{name}/content'


def hit(record, name):
    return {'files': [{'links': {'self': link(record, name)}}]}


RECORDS = {
    'hits': {
        'hits': [
            hit(3, 'v2.16-2026-11-19-ror-data.zip'),
            hit(2, 'v2.1-2025-01-02-ror-data.zip'),
            hit(1, 'v2.0-2024-12-01-ror-data.zip'),
        ]
    }
}


def test_select_latest():
    assert select_file_url(RECORDS).endswith(
        'v2.16-2026-11-19-ror-data.zip/content'
    )
    assert select_file_url(RECORDS, 'latest') == select_file_url(RECORDS)


def test_select_release():
    url = select_file_url(RECORDS, 'v2.1')
    assert get_file_name(url) == 'v2.1-2025-01-02-ror-data.json'
    assert get_record_id(url) == '2'


def test_select_release_is_not_a_prefix_match():
    # "v2.1" must not pick "v2.16-..."; "v2" does not name a release.
    assert get_record_id(select_file_url(RECORDS, 'v2.1')) == '2'
    with pytest.raises(ValueError):
        select_file_url(RECORDS, 'v2')


def test_select_full_file_label():
    url = select_file_url(RECORDS, 'v2.0-2024-12-01')
    assert get_record_id(url) == '1'


def test_get_record_id():
    assert get_record_id('https://example.org/nothing') is None
