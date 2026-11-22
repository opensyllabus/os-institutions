import pytest

from os_institutions.normalizer.catalog import (
    HYPHENS,
    QUOTES,
    add_spaces_around_slash,
    author_key,
    clean_author,
    clean_publisher,
    clean_title,
    collapse_whitespace,
    convert_ampersand_to_and,
    convert_hyphens_to_dashes,
    convert_quotes,
    isbn_key,
    publisher_key,
    title_key,
)


@pytest.mark.parametrize(
    'text,clean',
    [
        # Single space unchanged.
        ('token token', 'token token'),
        # Strip left/right whitespace.
        (' token token ', 'token token'),
        ('\n\r token token \n\r', 'token token'),
        # 2+ spaces removed.
        ('token  token', 'token token'),
        ('token   token', 'token token'),
        # 2+ linebreaks removed.
        ('token\n\ntoken', 'token token'),
        ('token\n\n\ntoken', 'token token'),
        # Single linebreak removed.
        ('token\ntoken', 'token token'),
        ('token\rtoken', 'token token'),
        # Phantom unicode chars removed.
        ('token\u009c token', 'token token'),
    ],
)
def test_collapse_whitespace(text, clean):
    assert collapse_whitespace(text) == clean


@pytest.mark.parametrize(
    'text,clean',
    [
        # Don't change hyphens.
        ('token - token', 'token - token'),
        # Convert unicode dashes to hyphens.
        *[(f'token {hyphen} token', 'token - token') for hyphen in HYPHENS],
    ],
)
def test_convert_hyphens_to_dashes(text, clean):
    assert convert_hyphens_to_dashes(text) == clean


@pytest.mark.parametrize(
    'text,clean',
    [
        ('token / token', 'token / token'),
        ('token/token', 'token / token'),
        ('token/ token', 'token / token'),
        ('token /token', 'token / token'),
    ],
)
def test_add_spaces_around_slash(text, clean):
    assert add_spaces_around_slash(text) == clean


@pytest.mark.parametrize(
    'text,clean',
    [
        # Don't change straight single/double quotes.
        ('token "quote" token', 'token "quote" token'),
        ("token 'quote' token", "token 'quote' token"),
        # Straighten curly quotes.
        *[
            (f'token {c}quote{c} token', f'token {s}quote{s} token')
            for c, s in QUOTES
        ],
    ],
)
def test_convert_quotes(text, clean):
    assert convert_quotes(text) == clean


@pytest.mark.parametrize(
    'text,clean',
    [
        # & -> and when surrounded by spaces.
        ('token & token', 'token and token'),
        ('token  &  token', 'token  and  token'),
        # & -> and when surrounded by linebreaks.
        ('token\n&\ntoken', 'token\nand\ntoken'),
        ('token\n\n&\n\ntoken', 'token\n\nand\n\ntoken'),
        # Keep & when adjacent non-whitespace char.
        ('AT&T', 'AT&T'),
        ('AT& T', 'AT& T'),
        ('AT &T', 'AT &T'),
    ],
)
def test_convert_ampersand_to_and(text, clean):
    assert convert_ampersand_to_and(text) == clean


@pytest.mark.parametrize(
    'text,clean',
    [
        # Unchanged.
        ('The City of God', 'The City of God'),
        # Titlecase.
        ('the city of god', 'The City of God'),
        ('THE CITY OF GOD', 'The City of God'),
        # Strip punctuation from both sides.
        ('The City of God.', 'The City of God'),
        ('The City of God...', 'The City of God'),
        ('The City of God /', 'The City of God'),
        ('The City of God :', 'The City of God'),
        ('The City of God,', 'The City of God'),
        ('The City of God.,', 'The City of God'),
        (', The City of God', 'The City of God'),
        ('/ The City of God', 'The City of God'),
        ('... The City of God', 'The City of God'),
        # Leave closing ) and ].
        ('The City of (God)', 'The City of (God)'),
        ('The City of [God]', 'The City of [God]'),
        # Keep "interior" punctuation.
        ('S/Z', 'S/Z'),
        (
            'Landlords Without Land: The U. P. Zamindars Today',
            'Landlords Without Land: The U. P. Zamindars Today',
        ),
        # Keep ! and ?
        ('The City of God!', 'The City of God!'),
        ('The City of God?', 'The City of God?'),
        # Collapse whitespace.
        ('  The City of God  ', 'The City of God'),
        ('The City  of   God', 'The City of God'),
        ('The City \t\n of God', 'The City of God'),
        ('The\u009c Handmaid\'s Tale', 'The Handmaid\'s Tale'),
        # & -> and.
        ('Art & fear', 'Art and Fear'),
        # Don't change abbreviations.
        ('Richard III', 'Richard III'),
        ('Make Room for TV', 'Make Room for TV'),
        ('US Foreign Policy', 'US Foreign Policy'),
        (
            'Discovering Statistics Using IBM SPSS Statistics',
            'Discovering Statistics Using IBM SPSS Statistics',
        ),
        # Remove CJK chars.
        ('公司理财 : 理论與实务 = Corporate Finance', 'Corporate Finance'),
        # Collapse extra spaces before :
        (
            'Promoting Health : Practical Guide',
            'Promoting Health: Practical Guide',
        ),
        (
            'Promoting Health   : Practical Guide',
            'Promoting Health: Practical Guide',
        ),
        # Strip quotes around whole title.
        ('"Silence of the Lambs"', 'Silence of the Lambs'),
        ('"Bentham"', 'Bentham'),
        ('“Bentham”', 'Bentham'),
        # TODO: Leave in interior quotes.
        # TODO: Strip single-quote wrap quotes.
        # TODO: Downcase all-caps tokens, but not abbreviations (?)
    ],
)
def test_clean_title(text, clean):
    assert clean_title(text) == clean


@pytest.mark.parametrize(
    'text,clean',
    [
        # Normalize case.
        ('David', 'David'),
        ('DAVID', 'David'),
        ('david', 'David'),
        ('David William', 'David William'),
        ('david william', 'David William'),
        ('David William,', 'David William'),
        # Keep internal case.
        ('McClure', 'McClure'),
        # Strip punctuation.
        ('Homer.', 'Homer'),
        ('Homer,', 'Homer'),
        ('Homer /', 'Homer'),
        ('/ Homer', 'Homer'),
        # Keep hyphens.
        ('McClure-Weisman', 'McClure-Weisman'),
        # Collapse whitespace.
        ('David    William,', 'David William'),
        (' David William ', 'David William'),
        ('David\nWilliam', 'David William'),
        # Strip birth/death years.
        ('Richard 1908-1960', 'Richard'),
        ('Richard 1908-', 'Richard'),
        # Initials should be uppercase + period, split by space.
        ('J. D.', 'J. D.'),
        ('J.D.', 'J. D.'),
        ('J.', 'J.'),
        ('J', 'J.'),
        ('j. d.', 'J. D.'),
        ('j d', 'J. D.'),
        # Strip PhD.
        ('Dee Unglaub Ph.D.', 'Dee Unglaub'),
        ('Dee Unglaub Ph. D.', 'Dee Unglaub'),
        ('Dee Unglaub PhD', 'Dee Unglaub'),
        ('Dee Unglaub PHD', 'Dee Unglaub'),
        ('Dee Unglaub phd', 'Dee Unglaub'),
    ],
)
def test_clean_author(text, clean):
    assert clean_author(text) == clean


@pytest.mark.parametrize(
    'text,clean',
    [
        ('Vendome Press', 'Vendome Press'),
        # Collapse whitespace.
        (' Vendome   Press ', 'Vendome Press'),
        ('Vendome\nPress', 'Vendome Press'),
        # Strip punctuation.
        ('Cengage.', 'Cengage'),
        ('Cengage,', 'Cengage'),
        ('Cengage /', 'Cengage'),
        ('/ Cengage', 'Cengage'),
        # Strip outside parans / brackets, keep text.
        ('(Cengage)', 'Cengage'),
        ('[Cengage]', 'Cengage'),
        # Strip parens / brackets + text.
        ('Cengage (US)', 'Cengage'),
        ('Cengage [US]', 'Cengage'),
        ('Spinal Publications (N.Z.) Ltd.,', 'Spinal Publications'),
        ('Spinal Publications Ltd. (N.Z.),', 'Spinal Publications'),
        ('J.C.B. Mohr (Paul Siebeck),', 'J.C.B. Mohr'),
        (
            'International Mountain Society (IMS) and United Nations University',  # noqa: E501
            'International Mountain Society and United Nations University',
        ),
        (
            'International Mountain Society [IMS] and United Nations University',  # noqa: E501
            'International Mountain Society and United Nations University',
        ),
        # Drop legal abbrs.
        ('Vertical, Inc.', 'Vertical'),
        ('Vertical, Inc', 'Vertical'),
        ('Vertical, INC', 'Vertical'),
        ('Usborne Publishing Ltd.', 'Usborne Publishing'),
        ('Usborne Publishing Ltd', 'Usborne Publishing'),
        ('Usborne Publishing LTD', 'Usborne Publishing'),
        ('VIZ Media, LLC', 'VIZ Media'),
        ('VIZ Media, llc', 'VIZ Media'),
        ('VIZ Media, llc.', 'VIZ Media'),
        ('VIZ Media, Inc. Ltd.', 'VIZ Media'),
        # Pad spaces around /.
        (
            'White Tree Books/Redcliffe Press',
            'White Tree Books / Redcliffe Press',
        ),
        # Don't remove "Inc" as part of word.
        ('Press Incorporated', 'Press Incorporated'),
        # Expand abbreviations.
        ('Concept Pub. Co.', 'Concept Publishing Company'),
        ('Michael Rubenstein Pub.', 'Michael Rubenstein Publishing'),
        ('Chilton Book Co.', 'Chilton Book Company'),
        ('Kendall/Hunt Pub Co.,', 'Kendall / Hunt Publishing Company'),
        ('Harvard Univ. Press', 'Harvard University Press'),
        ('Berkley Publishing Corp.,', 'Berkley Publishing Corporation'),
        ('Carol Publ. Group,', 'Carol Publishing Group'),
        (
            'World Scientific Pub Co Pte Lt',
            'World Scientific Publishing Company',
        ),
        ('Headley Bros., Ltd.', 'Headley Brothers'),
        ('Princeton University Pr', 'Princeton University Press'),
        # Remove spaces before : and ;
        (
            'Atheneum ; Maxwell Macmillan Canada ; Maxwell Macmillan International',  # noqa: E501
            'Atheneum; Maxwell Macmillan Canada; Maxwell Macmillan International',  # noqa: E501
        ),
        (
            'Oxbow Books ; Available from, D. Brown Book Company',
            'Oxbow Books; Available from, D. Brown Book Company',
        ),
        (
            'Oxbow Books : Available from, D. Brown Book Company',
            'Oxbow Books: Available from, D. Brown Book Company',
        ),
        # Remove CJK characters
        ('上海外语教育出版社', None),
        ('上海 Cengage', 'Cengage'),
    ],
)
def test_clean_publisher(text, clean):
    assert clean_publisher(text) == clean


@pytest.mark.parametrize(
    'text,key',
    [
        ('Lowercase', 'lowercase'),
        ('LOWERCASE', 'lowercase'),
        ('keep numbers 1, 2, 3', 'keep numbers 1 2 3'),
        ('keep 1numbers2', 'keep 1numbers2'),
        ('article stopwords a, an, the', 'article stopwords'),
        ('punctuation.?!', 'punctuation'),
        (None, None),
        # Non-english
        (
            'О Бинарной Аддитивной Проблеме Делителей',
            'o binarnoi additivnoi probleme delitelei',
        ),
        (
            'الآلهة والمشاهد الزراعية في فنون بلاد الرافدين',
            'lalh wlmshhd lzr y fy fnwn bld lrfdyn',
        ),
        ('井藤英喜', 'jing teng ying xi'),
    ],
)
def test_title_key(text, key):
    assert title_key(text) == key


@pytest.mark.parametrize(
    'text,key',
    [
        ('Lowercase', 'lowercase'),
        ('LOWERCASE', 'lowercase'),
        ('keep numbers 1, 2, 3', 'keep numbers 1 2 3'),
        ('keep 1numbers2', 'keep 1numbers2'),
        ('article stopwords a, an, the', 'article stopwords'),
        ('punctuation.?!', 'punctuation'),
        (None, None),
    ],
)
def test_author_key(text, key):
    assert author_key(text) == key


@pytest.mark.parametrize(
    'text,key',
    [
        ('Simon and Schuster', 'simon schuster'),
        ('Simon & Schuster', 'simon schuster'),
        ('Pfeiffer & Company,', 'pfeiffer'),
        ('Vendome Press', 'vendome'),
        ('VIZ Media, Inc. Ltd.', 'viz media'),
        ('/ Cengage (US)', 'cengage'),
        (
            'American Mathematical Society (AMS)',
            'american mathematical society',
        ),
        ('World Scientific Pub Co Pte Lt', 'world scientific'),
        ('Harper & Bros.', 'harper brothers'),
        ('W. W. Norton & co.', 'w w norton'),
        ('Arnica Pub.,', 'arnica'),
        ('Harvard Univ. Press', 'harvard'),
        ('Spinal Publications (N.Z.) Ltd.,', 'spinal'),
        ('Life Choices Corp.,', 'life choices'),
        ('Simon & Schuster Pbks.,', 'simon schuster'),
        ('Benn brothers, limited,', 'benn brothers'),
        ('The University of Michigan Press', 'michigan'),
        ('Princeton University Pr', 'princeton'),
    ],
)
def test_publisher_key(text, key):
    # XXX: decouple regularize().
    clean_text = clean_publisher(text)
    assert publisher_key(clean_text) == key


@pytest.mark.parametrize(
    'text,key',
    [
        ('978-1-938168-37-6', '9781938168376'),
        ('9781938168376', '9781938168376'),
        ('0-306-40615-2', '9780306406157'),
        ('0306406152', '9780306406157'),
        ('0-8044-2957-x', '9780804429573'),
        ('0-8044-2957-X', '9780804429573'),
        ('0-306-40615-3', '0306406153'),  # bad checksum: left as-is
        ('0-19-853453-X', '019853453X'),  # bad checksum: left as-is
        ('12345', None),
        (None, None),
        ('', None),
    ],
)
def test_isbn_key(text, key):
    assert isbn_key(text) == key
