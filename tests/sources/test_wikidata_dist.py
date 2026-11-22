import pickle
import urllib.error
from email.message import Message

import pandas as pd
import pytest

from os_institutions.sources import wikidata_dist


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after:
        headers['Retry-After'] = retry_after
    return urllib.error.HTTPError('url', code, 'msg', headers, None)


def binding(wikidata_id, label='x'):
    return {
        'item': {
            'type': 'uri',
            'value': f'http://www.wikidata.org/entity/{wikidata_id}',
        },
        'itemLabel': {'type': 'literal', 'value': label},
    }


class FakeSparql:
    """Stands in for SPARQLWrapper; `handler(query)` returns bindings."""

    def __init__(self, handler):
        self.handler = handler
        self.queries = []
        self.calls = 0
        self._query = None

    def __call__(self, *args, **kwargs):
        return self

    def setQuery(self, query):
        self._query = query
        self.queries.append(query)

    def setReturnFormat(self, fmt):
        pass

    def query(self):
        self.calls += 1
        self._bindings = self.handler(self._query)
        return self

    def convert(self):
        return {'results': {'bindings': self._bindings}}


def ids_in(query):
    values = query.split('VALUES ?item { ')[1].split(' }')[0]
    return [x.split(':')[1] for x in values.split()]


@pytest.fixture
def sleeps(monkeypatch):
    waits = []
    monkeypatch.setattr(wikidata_dist.time, 'sleep', waits.append)
    return waits


def patch_sparql(monkeypatch, handler):
    fake = FakeSparql(handler)
    monkeypatch.setattr(wikidata_dist, 'SPARQLWrapper', fake)
    return fake


def test_query_lists_every_id():
    query = wikidata_dist.get_query(['Q1', 'Q2', 'Q3'])
    assert 'VALUES ?item { wd:Q1 wd:Q2 wd:Q3 }' in query


def test_groups_bindings_by_item(monkeypatch, sleeps):
    def handler(query):
        return [binding('Q1', 'a'), binding('Q2'), binding('Q1', 'b')]

    patch_sparql(monkeypatch, handler)
    results = wikidata_dist.get_results(['Q1', 'Q2', 'Q3'])
    assert [b['itemLabel']['value'] for b in results['Q1']] == ['a', 'b']
    assert len(results['Q2']) == 1
    assert results['Q3'] == []


def test_empty_batch_makes_no_query(monkeypatch, sleeps):
    fake = patch_sparql(monkeypatch, lambda q: [])
    assert wikidata_dist.get_results([None, '']) == {}
    assert fake.queries == []


def test_retries_429_then_succeeds(monkeypatch, sleeps):
    outcomes = [http_error(429), http_error(429, '7')]

    def handler(query):
        if outcomes:
            raise outcomes.pop(0)
        return [binding('Q1')]

    patch_sparql(monkeypatch, handler)
    assert len(wikidata_dist.get_results(['Q1'])['Q1']) == 1
    assert sleeps == [5, 7]


def test_raises_when_429_persists(monkeypatch, sleeps):
    def handler(query):
        raise http_error(429)

    fake = patch_sparql(monkeypatch, handler)
    with pytest.raises(wikidata_dist.Unavailable) as excinfo:
        wikidata_dist.get_results(['Q1', 'Q2'])
    pickle.loads(pickle.dumps(excinfo.value))
    assert fake.calls == wikidata_dist.MAX_RETRIES + 1
    assert max(sleeps) <= wikidata_dist.BACKOFF_CAP


def test_retries_connection_errors_then_succeeds(monkeypatch, sleeps):
    outcomes = [
        urllib.error.URLError(OSError(-2, "Name or service not known"))
    ]

    def handler(query):
        if outcomes:
            raise outcomes.pop(0)
        return [binding("Q1")]

    patch_sparql(monkeypatch, handler)
    assert len(wikidata_dist.get_results(["Q1", "Q2"])["Q1"]) == 1
    assert sleeps == [5]


def test_raises_when_offline_instead_of_dropping_ids(monkeypatch, sleeps):
    def handler(query):
        raise urllib.error.URLError(OSError(-2, "Name or service not known"))

    fake = patch_sparql(monkeypatch, handler)
    with pytest.raises(wikidata_dist.Unavailable):
        wikidata_dist.get_results(["Q1", "Q2", "Q3"])
    assert fake.calls == wikidata_dist.MAX_RETRIES + 1


def test_coverage_check():
    ok = pd.DataFrame({"results": [[1]] * 99 + [None]})
    wikidata_dist.check_coverage(ok)
    bad = pd.DataFrame({"results": [[1]] * 90 + [None] * 10})
    with pytest.raises(RuntimeError):
        wikidata_dist.check_coverage(bad)


def test_bad_id_is_isolated_by_splitting(monkeypatch, sleeps):
    def handler(query):
        ids = ids_in(query)
        if 'Q3' in ids:
            raise http_error(500)
        return [binding(x) for x in ids]

    patch_sparql(monkeypatch, handler)
    results = wikidata_dist.get_results(['Q1', 'Q2', 'Q3', 'Q4', 'Q5'])
    assert results['Q3'] is None
    for wikidata_id in ['Q1', 'Q2', 'Q4', 'Q5']:
        assert len(results[wikidata_id]) == 1
    assert sleeps == []


def test_non_http_errors_also_split(monkeypatch, sleeps):
    def handler(query):
        ids = ids_in(query)
        if len(ids) > 1:
            raise ValueError('bad json')
        return [binding(ids[0])]

    patch_sparql(monkeypatch, handler)
    results = wikidata_dist.get_results(['Q1', 'Q2'])
    assert all(len(v) == 1 for v in results.values())


def test_qlever_query_lists_every_id_in_both_places():
    query = wikidata_dist.get_qlever_query(['Q1', 'Q2'])
    assert query.count('VALUES ?item { wd:Q1 wd:Q2 }') == 2
    assert 'SERVICE' not in query


def test_qlever_results_are_normalized_like_wdqs(monkeypatch, sleeps):
    def handler(query):
        return [
            {
                **binding('Q1'),
                'location': {'type': 'literal', 'value': 'POINT(1.5 2.5)'},
            },
            {
                'item': binding('Q2')['item'],
            },
        ]

    fake = patch_sparql(monkeypatch, handler)
    results = wikidata_dist.get_results(['Q1', 'Q2'], source='qlever')
    assert results['Q1'][0]['location']['value'] == 'Point(1.5 2.5)'
    assert results['Q2'][0]['itemLabel']['value'] == 'Q2'
    assert 'PREFIX wdt:' in fake.queries[0]


def test_wdqs_results_are_left_alone(monkeypatch, sleeps):
    row = {'item': binding('Q1')['item']}
    patch_sparql(monkeypatch, lambda q: [row])
    results = wikidata_dist.get_results(['Q1'])
    assert 'itemLabel' not in results['Q1'][0]
