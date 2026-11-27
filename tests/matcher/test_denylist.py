import pytest

from os_institutions.matcher.build import build_table, normalize_urls
from os_institutions.matcher.denylist import google_site_key, is_shared_host
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
        'sites.google.com/site',
        'sites.google.com/a',
        'sites.google.com/a/cidexxi.org',
        'sites.google.com/moe-dl.edu.my',
        'docs.google.com/x',
        'drive.google.com/file',
        'forms.google.com/x',
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
        'sites.google.com/view/kolejvokasionalsandakan2',
        'sites.google.com/site/centrodeformacaocrista',
        'sites.google.com/moe-dl.edu.my/kvmiri',
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


@pytest.mark.parametrize(
    'url, key',
    [
        (
            'https://sites.google.com/view/kolejvokasionalsandakan2',
            'sites.google.com/view/kolejvokasionalsandakan2',
        ),
        (
            'https://sites.google.com/view/portalkvbalikpulau/utama',
            'sites.google.com/view/portalkvbalikpulau',
        ),
        ('https://sites.google.com/view/bpbl/', 'sites.google.com/view/bpbl'),
        (
            'HTTP://Sites.Google.com/site/centrodeformacaocrista?x=1#y',
            'sites.google.com/site/centrodeformacaocrista',
        ),
        (
            'sites.google.com/moe-dl.edu.my/kvmiri',
            'sites.google.com/moe-dl.edu.my/kvmiri',
        ),
        (
            'https://sites.google.com/ceylonspacescience.com/ciss-space-science/home',
            'sites.google.com/ceylonspacescience.com/ciss-space-science',
        ),
    ],
)
def test_google_site_key(url, key):
    assert google_site_key(url) == key
    assert not is_shared_host(key)


@pytest.mark.parametrize(
    'url',
    [
        None,
        '',
        'https://sites.google.com/',
        'https://sites.google.com/view',
        'https://sites.google.com/view/',
        'https://sites.google.com/andrew.cmu.edu/',
        # repair_url already turns these into `<domain>/...`
        'https://sites.google.com/a/cidexxi.org/cide/home',
        'https://docs.google.com/document/d/abc',
        'https://drive.google.com/file/d/1/view',
        'https://example.edu/view/x',
    ],
)
def test_google_site_key_none(url):
    assert google_site_key(url) is None


def test_google_sites_build_and_match():
    matcher = _matcher(
        [
            dict(
                name='Kolej Vokasional Sandakan 2',
                names=['Kolej Vokasional Sandakan 2'],
                urls=[
                    'https://sites.google.com/view/kolejvokasionalsandakan2'
                ],
            ),
            dict(
                name='Kolej Vokasional Miri',
                names=['Kolej Vokasional Miri'],
                urls=['https://sites.google.com/moe-dl.edu.my/kvmiri'],
            ),
            dict(
                name='Kolej Vokasional Keningau',
                names=['Kolej Vokasional Keningau'],
                urls=[
                    'https://sites.google.com/moe-dl.edu.my/kvkeningau/home'
                ],
            ),
            dict(
                name='Centro de Estudios Justo Sierra',
                names=['Centro de Estudios Justo Sierra'],
                urls=['https://sites.google.com/a/cidexxi.org/cide/home'],
            ),
            dict(
                name='Docs Only',
                names=['Docs Only'],
                urls=['https://docs.google.com/document/d/abc'],
            ),
        ]
    )
    keys = set(matcher.lookup_table)

    for bare in (
        'sites.google.com',
        'sites.google.com/view',
        'sites.google.com/a',
        'sites.google.com/moe-dl.edu.my',
    ):
        assert bare not in keys
    assert not any(k.startswith('docs.google.com') for k in keys)
    assert 'sites.google.com/view/kolejvokasionalsandakan2' in keys

    def name(url, source_url=None):
        found = matcher.match(url, source_url, None, None, None, None, None)
        return found and found['name']

    assert (
        name('https://sites.google.com/view/kolejvokasionalsandakan2/home')
        == 'Kolej Vokasional Sandakan 2'
    )
    assert (
        name(None, 'https://sites.google.com/view/kolejvokasionalsandakan2')
        == 'Kolej Vokasional Sandakan 2'
    )
    # Two sites of one Workspace domain stay distinct
    assert (
        name('https://sites.google.com/moe-dl.edu.my/kvmiri/home')
        == 'Kolej Vokasional Miri'
    )
    assert (
        name('https://sites.google.com/moe-dl.edu.my/kvkeningau')
        == 'Kolej Vokasional Keningau'
    )
    assert name('https://sites.google.com/a/cidexxi.org/cide/x') == (
        'Centro de Estudios Justo Sierra'
    )
    # Other people's sites, the bare host and other Google hosts match nothing
    assert name('https://sites.google.com/view/someone-else') is None
    assert name('https://sites.google.com/moe-dl.edu.my/other') is None
    assert name('https://sites.google.com/andrew.cmu.edu/course') is None
    assert name('https://sites.google.com/') is None
    assert name('https://docs.google.com/document/d/abc') is None
