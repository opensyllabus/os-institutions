import pytest

from os_institutions.matcher.build import build_table, normalize_urls
from os_institutions.matcher.denylist import is_shared_host
from os_institutions.matcher.matcher import InstitutionMatcher


@pytest.mark.parametrize(
    'key',
    [
        'facebook.com',
        'facebook.com/p',
        'facebook.com/kolejpacific.edu.my',
        'm.facebook.com/foo',
        'fr-fr.facebook.com',
        'linkedin.com',
        'linkedin.com/redir',
        'twitter.com/mit',
        'x.com/mit',
        'youtu.be/abc',
        'wikipedia.org/wiki',
        'sites.google.com',
        'sites.google.com/view',
        'docs.google.com/x',
        'archive.org/web',
        'curricunet.com',
        'curriqunet.com',
    ],
)
def test_shared_host(key):
    assert is_shared_host(key)


@pytest.mark.parametrize(
    'key',
    [
        None,
        '',
        'vandercook.edu',
        'nuga.com.ng',
        'kolejpacific.edu.my',
        # A tenant of a shared platform identifies the institution
        'curricunet.com/rccd',
        'miracosta.curricunet.com',
        'bpp.rl.talis.com',
        'alamo.campusconcourse.com',
        # Only whole labels count
        'notfacebook.com',
        'box.com',
        'facebook.com.example.edu',
        'google.com.br',
        'mit.edu/x.com',
    ],
)
def test_not_shared_host(key):
    assert not is_shared_host(key)


def test_normalize_urls_drops_shared_hosts():
    urls = normalize_urls(
        [
            'https://www.linkedin.com/redir/redirect?url=http%3A%2F%2Fwww.nuga.com.ng',
            'https://www.nuga.com.ng/',
        ]
    )

    assert urls == ['nuga.com.ng', 'nuga.com.ng']


def _matcher(rows):
    import pandas as pd

    df = pd.DataFrame(rows)
    df['_id'] = df.index
    return InstitutionMatcher(build_table(df))


def test_build_and_match_skip_shared_hosts():
    matcher = _matcher(
        [
            dict(
                name='Nigerian University Games Association',
                names=['Nigerian University Games Association'],
                urls=[
                    'https://www.linkedin.com/redir/redirect?url=x',
                    'https://www.nuga.com.ng/',
                ],
            ),
            dict(
                name='Kolej Pacific Kuantan',
                names=['Kolej Pacific Kuantan'],
                urls=['https://www.facebook.com/kolejpacific.edu.my'],
            ),
        ]
    )

    assert 'linkedin.com' not in matcher.lookup_table
    assert 'facebook.com' not in matcher.lookup_table
    assert not any(k.startswith('facebook.com/') for k in matcher.lookup_table)
    assert matcher(url='https://www.linkedin.com/in/someone') is None
    assert matcher(url='https://www.facebook.com/p/other-page') is None
    assert (
        matcher.match(
            'https://www.nuga.com.ng/', None, None, None, None, None, None
        )['name']
        == 'Nigerian University Games Association'
    )
    # No URL key left, but the name still matches
    assert (
        matcher.match(
            None, None, None, 'Kolej Pacific Kuantan', None, None, None
        )['name']
        == 'Kolej Pacific Kuantan'
    )


def test_matcher_ignores_shared_host_keys_in_old_tables():
    """A matcher built before the denylist still holds the bad keys."""
    table = {
        'institutions': [{'_id': 0, 'name': 'Old'}],
        'lookup': {'linkedin.com': 0, 'linkedin.com/redir': 0, 'old.edu': 0},
    }
    matcher = InstitutionMatcher(table)

    assert (
        matcher.match(
            'https://www.linkedin.com/redir/x',
            None,
            None,
            None,
            None,
            None,
            None,
        )
        is None
    )
    assert matcher.match(
        'https://www.old.edu/', None, None, None, None, None, None
    )
