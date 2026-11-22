import pandas as pd

from os_institutions.paths import DATA_DIR

BLACKLIST_DIR = DATA_DIR / 'blacklists'

CODE_FILES = {
    'district': 'district.csv',
    'chain': 'chains.csv',
    'for-profit': 'for-profit.csv',
    'k12': 'k12.csv',
    'branch': 'branches.csv',
    'shared-domain': 'branches.csv',
    'no-conflict': 'review.csv',
}


CONTROLS = {'public', 'private nonprofit', 'private for-profit'}


def load_blacklist():
    paths = sorted(BLACKLIST_DIR.glob('*.csv'))
    return pd.concat(
        [pd.read_csv(p).convert_dtypes().assign(file=p.name) for p in paths],
        ignore_index=True,
    )


def test_every_row_has_an_identifier():
    df = load_blacklist()
    has_id = df.unitid.notna() | df.ror_id.notna()

    assert has_id.all()


def test_every_row_has_a_name_and_reason():
    """Every blacklist entry must explain why it's excluded, so future
    additions/removals can be diagnosed without re-deriving the history.
    """
    df = load_blacklist()

    for col in ('name', 'reason'):
        assert df[col].notna().all()
        assert (df[col].str.strip() != '').all()


def test_control_is_a_known_ownership_type_for_ipeds_rows():
    df = load_blacklist()

    assert df[df.unitid.isna()].control.isna().all()
    assert df[df.unitid.notna()].control.isin(CONTROLS).all()


def test_reason_codes_are_in_their_own_file():
    df = load_blacklist()
    coded = df[df.reason.isin(CODE_FILES)]

    assert (coded.reason.map(CODE_FILES) == coded.file).all()


def test_readme_documents_every_reason_code():
    readme = (BLACKLIST_DIR / 'README.md').read_text()

    for code in CODE_FILES:
        assert f'`{code}`' in readme


def test_no_identifier_is_blacklisted_twice():
    df = load_blacklist()

    assert not df.unitid.dropna().duplicated().any()
    assert not df.ror_id.dropna().duplicated().any()
