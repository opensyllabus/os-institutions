import pytest

from os_institutions.normalizer.institution import (
    clean_institution,
    expand_abbrs,
    institution_key,
    remove_punct,
)


@pytest.mark.parametrize(
    'test,result',
    [
        ('U.I.U.C', 'UIUC'),
        ('', ''),
    ],
)
def test_remove_punct(test, result):
    assert remove_punct(test) == result


@pytest.mark.parametrize(
    'test,result',
    [
        ('Univ', 'University'),
        ('', ''),
    ],
)
def test_expand_abbrs(test, result):
    assert expand_abbrs(test) == result


@pytest.mark.parametrize(
    'test,result',
    [('stanford university', 'Stanford University'), ('', None), (None, None)],
)
def test_clean_institution(test, result):
    assert clean_institution(test) == result


@pytest.mark.parametrize(
    'test,result',
    [
        ('Stanford University', 'stanford university'),
        ('University of Illinois', 'university illinois'),
        ('', None),
        (None, None),
    ],
)
def test_institution_key(test, result):
    assert institution_key(test) == result
