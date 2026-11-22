import pickle

import pandas as pd
import pytest
import requests
from addict import Dict

from os_institutions.sources import wikipedia

THUMB = (
    "https://thumb.wikimedia.org/wikipedia/en/thumb/6/60/Logo.svg/"
    "500px-Logo.svg.png?utm_source=en.wikipedia.org&utm_campaign=api"
)
UPLOAD = (
    "https://upload.wikimedia.org/wikipedia/en/thumb/6/60/Logo.svg/"
    "500px-Logo.svg.png"
)


def test_thumb_url_is_rewritten_to_upload_without_tracking_query():
    assert wikipedia.get_image_url(THUMB) == UPLOAD


def test_upload_url_is_unchanged():
    assert wikipedia.get_image_url(UPLOAD) == UPLOAD


def test_missing_thumbnail_is_passed_through():
    missing = Dict().thumbnail.source
    assert wikipedia.get_image_url(missing) == missing


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


PAGE = {
    "query": {
        "pages": {
            "1": {"title": "T", "extract": "d", "thumbnail": {"source": THUMB}}
        }
    }
}


@pytest.fixture
def sleeps(monkeypatch):
    waits = []
    monkeypatch.setattr(wikipedia.time, "sleep", waits.append)
    return waits


def test_connection_errors_retry_then_succeed(monkeypatch, sleeps):
    outcomes = [requests.ConnectionError("dns"), requests.Timeout("slow")]

    def get(*args, **kwargs):
        if outcomes:
            raise outcomes.pop(0)
        return FakeResponse(PAGE)

    monkeypatch.setattr(wikipedia.requests, "get", get)
    result = wikipedia.get_result("https://en.wikipedia.org/wiki/T")
    assert result["image_url"] == UPLOAD
    assert sleeps == [5, 10]


def test_raises_when_wikipedia_stays_unreachable(monkeypatch, sleeps):
    calls = []

    def get(*args, **kwargs):
        calls.append(1)
        raise requests.ConnectionError("dns")

    monkeypatch.setattr(wikipedia.requests, "get", get)
    with pytest.raises(wikipedia.Unavailable) as excinfo:
        wikipedia.get_result("https://en.wikipedia.org/wiki/T")
    pickle.loads(pickle.dumps(excinfo.value))
    assert len(calls) == wikipedia.MAX_RETRIES + 1
    assert max(sleeps) <= wikipedia.BACKOFF_CAP


def test_coverage_check():
    ok = pd.DataFrame({"result": [{"a": 1}] * 99 + [None]})
    wikipedia.check_coverage(ok)
    bad = pd.DataFrame({"result": [{"a": 1}] * 90 + [None] * 10})
    with pytest.raises(RuntimeError):
        wikipedia.check_coverage(bad)
