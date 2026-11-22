import string

from titlecase import titlecase

from os_institutions.normalizer.catalog import (
    _expand_abbr,
    collapse_whitespace,
    keyify,
    regularize,
    remove_cjk_chars,
)

STOPWORDS = {
    'a',
    'an',
    'the',
    'and',
    'of',
}


def remove_punct(text):
    return text.translate(str.maketrans('', '', string.punctuation))


def expand_abbrs(text):
    # TODO: Utilize os_norm_institutions/dictionaries.py
    text = _expand_abbr(text, 'Univ', 'University')
    return text


INSTITUTION_RULES = (
    remove_cjk_chars,
    remove_punct,
    collapse_whitespace,
    titlecase,
    expand_abbrs,
)


def clean_institution(text: str | None):
    if text:
        return regularize(text, INSTITUTION_RULES)


def institution_key(text: str | None):
    if text:
        return keyify(text, STOPWORDS)


def normalize_school_name(text: str | None):
    if text:
        return institution_key(clean_institution(text))
