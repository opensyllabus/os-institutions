import ast
import gzip
import json
import warnings
from pathlib import Path

import os_normalizer
import pytest

import os_institutions
from os_institutions.matcher import format

TABLE = {
    'institutions': [
        {
            '_id': 1,
            'name': 'Ünïversity of Exämple "quoted"',
            'unitid': None,
            'lat': 0.0,
            'lng': -122.30000000000001,
            'enrollment': 12345,
            'research': True,
            'graduate': False,
        },
        {'_id': 2, 'name': None, 'unitid': 7, 'lat': 1e-7, 'lng': 1.5},
    ],
    'lookup': {'example.edu': 0, 'ünï.edu': 1, '': 0},
}


def write_gz(path, document):
    with gzip.open(path, 'wt', encoding='utf-8') as fh:
        json.dump(document, fh)


def test_round_trip_keeps_values_and_types(tmp_path):
    path = tmp_path / 'matcher.json.gz'
    format.save(TABLE, path)
    loaded = format.load(path)

    assert loaded == TABLE
    for before, after in zip(TABLE['institutions'], loaded['institutions']):
        for key, value in before.items():
            assert type(after[key]) is type(value), key


def test_save_is_deterministic(tmp_path):
    a, b = tmp_path / 'a.json.gz', tmp_path / 'b.json.gz'
    format.save(TABLE, a)
    reordered = {**TABLE, 'lookup': dict(reversed(TABLE['lookup'].items()))}
    format.save(reordered, b)

    assert a.read_bytes() == b.read_bytes()


def test_save_records_normalizer_version(tmp_path):
    path = tmp_path / 'matcher.json.gz'
    format.save(TABLE, path)
    with gzip.open(path, 'rt', encoding='utf-8') as fh:
        document = json.load(fh)

    assert document['format'] == format.FORMAT
    assert document['normalizer_version'] == os_normalizer.__version__


def test_save_rejects_nan(tmp_path):
    table = {'institutions': [{'lat': float('nan')}], 'lookup': {}}
    with pytest.raises(ValueError):
        format.save(table, tmp_path / 'matcher.json.gz')


def test_load_rejects_unknown_format(tmp_path):
    path = tmp_path / 'matcher.json.gz'
    write_gz(path, {'format': 99, 'institutions': [], 'lookup': {}})
    with pytest.raises(ValueError, match='unsupported matcher format 99'):
        format.load(path)


@pytest.mark.parametrize(
    'content',
    [
        b'not gzip at all',
        gzip.compress(b'{"format": 1, '),
        gzip.compress(b'[1, 2, 3]'),
        gzip.compress(b'{"format": 1, "institutions": {}, "lookup": []}'),
    ],
)
def test_load_rejects_malformed_files(tmp_path, content):
    path = tmp_path / 'matcher.json.gz'
    path.write_bytes(content)
    with pytest.raises(ValueError):
        format.load(path)


def test_load_warns_on_normalizer_version_mismatch(tmp_path, monkeypatch):
    path = tmp_path / 'matcher.json.gz'
    monkeypatch.setattr(os_normalizer, '__version__', '0.0.1')
    format.save(TABLE, path)
    monkeypatch.setattr(os_normalizer, '__version__', '0.0.2')

    with pytest.warns(UserWarning, match='0.0.1.*0.0.2'):
        assert format.load(path) == TABLE


def test_load_is_quiet_when_versions_match(tmp_path):
    path = tmp_path / 'matcher.json.gz'
    format.save(TABLE, path)
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        format.load(path)


def test_package_does_not_import_pickle():
    package = Path(os_institutions.__file__).parent
    for source in package.rglob('*.py'):
        for node in ast.walk(ast.parse(source.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            assert 'pickle' not in names, source
