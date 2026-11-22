from functools import reduce

import regex
from nltk.tokenize.util import is_cjk
from titlecase import titlecase
from unidecode import unidecode

TITLE_AUTHOR_STOPWORDS = {'a', 'an', 'the'}

PUBLISHER_STOPWORDS = {
    'the',
    'and',
    'of',
    'press',
    'corp',
    'corporation',
    'book',
    'books',
    'univ',
    'university',
    'company',
    'co',
    'publishers',
    'publishing',
    'publications',
    'publ',
    'pte',
    'lt',
    'pbks',
    'limited',
}

PUBLISHER_EXCLUDE_KEYS = {'s n'}

# http://jkorpela.fi/dashes.html
HYPHENS = {'\u002d', '\u2010', '\u2011', '\u2212', '\ufe63'}

QUOTES = (('“', '"'), ('”', '"'), ('‘', "'"), ('’', "'"), ("''", '"'))


def add_spaces_around_char(text, char):
    """Pad spaces around a character."""
    text = regex.sub(rf'([^\s]){char}', rf'\1 {char}', text)
    text = regex.sub(rf'{char}([^\s])', rf'{char} \1', text)

    return text


def add_spaces_around_dash(text):
    return add_spaces_around_char(text, '-')


def add_spaces_around_slash(text):
    return add_spaces_around_char(text, '/')


def add_space_after_period(text):
    return regex.sub(r'\.([^\s])', r'. \1', text)


def add_period_after_initial(text):
    return regex.sub(r'\b([a-z])(?![\.a-z])', r'\1.', text, flags=regex.I)


def collapse_whitespace(text):
    """Strip left/right; collapse 2+ whitespace -> 1 space;
    strip line breaks.
    """
    text = regex.sub(r'[\n\r\u009c]', ' ', text.strip())
    text = regex.sub(r'\s{2,}', ' ', text)

    return text


def collapse_space_before_colon(text):
    """Get rid of whitespace before colons."""
    return regex.sub(r'\s+:', ':', text)


def collapse_space_before_colon_and_semicolon(text):
    return regex.sub(r'\s+([:;])', r'\1', text)


def convert_ampersand_to_and(text):
    return regex.sub(r'([\s])&([\s])', r'\1and\2', text)


def convert_hyphens_to_dashes(text, char='-'):
    """Hyphen variants -> "-"."""
    for h in HYPHENS:
        text = text.replace(h, '-')

    return text


def convert_quotes(text):
    """Curly -> straight."""
    for special, standard in QUOTES:
        text = text.replace(special, standard)

    return text


def _expand_abbr(text, abbr, expanded):
    return regex.sub(rf'\b{abbr}\b\.?', expanded, text)


def expand_abbrs(text):
    text = _expand_abbr(text, 'Pub', 'Publishing')
    text = _expand_abbr(text, 'Publ', 'Publishing')
    text = _expand_abbr(text, 'Co', 'Company')
    text = _expand_abbr(text, 'Univ', 'University')
    text = _expand_abbr(text, 'Corp', 'Corporation')
    text = _expand_abbr(text, 'Bros', 'Brothers')
    text = _expand_abbr(text, 'Pr', 'Press')
    return text


def remove_cjk_chars(text):
    """Strip CJK characters."""
    return ''.join([char for char in text if not is_cjk(char)])


def remove_phd(text):
    return regex.sub(r' ph\.?\s?d\.?', '', text, flags=regex.I)


def remove_years(text):
    return regex.sub(r'[0-9]{4}-?', '', text)


def _remove_acronym(text, acronym):
    return regex.sub(rf'\b{acronym}\.?\b', '', text, flags=regex.I)


def remove_legal(text):
    text = _remove_acronym(text, 'ltd')
    text = _remove_acronym(text, 'llc')
    text = _remove_acronym(text, 'inc')
    text = _remove_acronym(text, 'pte')
    text = _remove_acronym(text, 'lt')
    return text


def strip_punct(text, match=r'[^\p{L}]*'):
    """Strip unicode from start / end."""
    text = regex.sub(f'{match}$', '', text)
    text = regex.sub(f'^{match}', '', text)
    return text


def strip_punct_except_numbers_and_bangs(text):
    """Strip unicode that isn't 0-9 and !?."""
    return strip_punct(text, r'[^\p{L}0-9!\?\)\]]*')


def strip_punct_except_round_and_square_brackets(text):
    """Strip unicode that isn't () []."""
    return strip_punct(text, r'[^\p{L}\(\)\[\]]*')


def strip_outer_brackets(text):
    """Strip () [] brackets around the whole string."""
    return regex.sub(r'^[\(\[](.*)[\)\]]$', r'\1', text)


def strip_trailing_brackets(text):
    """Strip trailing parens + brackets."""
    return regex.sub(r'[\(\[].*[\)\]]', ' ', text)


TITLE_RULES = (
    remove_cjk_chars,
    strip_punct_except_numbers_and_bangs,
    collapse_space_before_colon,
    collapse_whitespace,
    convert_ampersand_to_and,
    convert_quotes,
    titlecase,
)

AUTHOR_RULES = (
    strip_punct,
    add_space_after_period,
    add_period_after_initial,
    remove_phd,
    remove_years,
    collapse_whitespace,
    titlecase,
)

PUBLISHER_RULES = (
    remove_cjk_chars,
    strip_punct_except_round_and_square_brackets,
    strip_outer_brackets,
    strip_punct_except_round_and_square_brackets,
    strip_trailing_brackets,
    strip_punct_except_round_and_square_brackets,
    remove_legal,
    strip_punct_except_round_and_square_brackets,
    expand_abbrs,
    collapse_space_before_colon_and_semicolon,
    add_spaces_around_slash,
    collapse_whitespace,
)


def regularize(text, func):
    """Apply given regex rules and string manipluations.

    Empty string should always return None even after the
    rules are applied.
    """
    if text and (text := reduce(lambda t, f: f(t), func, text)):
        return text


def clean_title(text):
    return regularize(text, TITLE_RULES)


def clean_author(text):
    return regularize(text, AUTHOR_RULES)


def clean_publisher(text):
    return regularize(text, PUBLISHER_RULES)


def keyify(text, stopwords={}):
    """Keep (unicode) word characters and digits."""
    if text:
        ascii_text = unidecode(text)
        tokens = regex.findall(r'[\p{L}0-9]+', ascii_text.lower())
        return ' '.join(t for t in tokens if t not in stopwords)


def title_key(text):
    return keyify(text, TITLE_AUTHOR_STOPWORDS)


def author_key(text):
    return keyify(text, TITLE_AUTHOR_STOPWORDS)


def isbn10_to_isbn13(digits):
    """Convert a valid ISBN-10 to its ISBN-13 form (978 prefix + new check
    digit). Returns None if `digits` has a bad ISBN-10 checksum."""
    body, check = digits[:9], digits[9]
    if not body.isdigit():
        return None
    total = sum((10 - i) * int(d) for i, d in enumerate(body))
    total += 10 if check == 'X' else int(check) if check.isdigit() else -99
    if total % 11:
        return None
    stem = '978' + body
    weighted = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(stem))
    return stem + str((10 - weighted % 10) % 10)


def isbn_key(text):
    """Normalize an ISBN-10/13 for exact-match lookup: strip hyphens/spaces
    and keep only digits and the ISBN-10 check digit 'X', uppercased.

    ISBN-10s are converted to ISBN-13, which is the only form the catalog
    side indexes. An ISBN-10 that fails its checksum can't be converted
    and is returned unchanged.

    Rejects anything that isn't 10 or 13 digits long after stripping, so a
    garbled span the model parsed as an "ISBN" doesn't get treated as one.
    """
    if text:
        digits = regex.sub(r'[^0-9Xx]', '', text).upper()
        if len(digits) == 10:
            return isbn10_to_isbn13(digits) or digits
        if len(digits) == 13:
            return digits


def publisher_key(text):
    return keyify(text, PUBLISHER_STOPWORDS)
