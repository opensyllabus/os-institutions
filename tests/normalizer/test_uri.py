import pytest
import tldextract

from os_institutions.normalizer.uri import (
    clean_wayback_url,
    exclude_subdomain,
    get_base_domain_url,
    get_domain_url,
    get_email_base_domain_url,
    get_email_domain_url,
    get_full_url,
    get_path_prefix,
    repair_cuny_edu_url,
    repair_google_sites_url,
    repair_scheme,
    repair_wayback_url,
)


@pytest.mark.parametrize(
    'url,res',
    [
        ('http://example.com', 'http://example.com'),
        ('example.com', 'http://example.com'),
        ('www.example.com', 'http://www.example.com'),
        ('', None),
        (None, None),
    ],
)
def test_repair_scheme(url, res):
    assert repair_scheme(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        (
            'http:/www.pas.rochester.edu/~rajeev/PHY408/index.html',
            'http://www.pas.rochester.edu/~rajeev/PHY408/index.html',
        ),
        ('', None),
        (None, None),
        # TODO: Add more cases
    ],
)
def test_repair_wayback_url(url, res):
    assert repair_wayback_url(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        # Anchors (has a valid URL in the path)
        (
            'https://sites.google.com/a/g.clemson.edu/cpsc-8810/',
            'https://g.clemson.edu/cpsc-8810/',
        ),
        (
            'https://sites.google.com/a/msu.edu/',
            'https://msu.edu/',
        ),
        (
            'https://sites.google.com/a/mail.ccsf.edu/jeff-liss/home/',
            'https://mail.ccsf.edu/jeff-liss/home/',
        ),
        ('', None),
        (None, None),
        # Non-anchors (should be dropped)
        (
            'https://sites.google.com/site/drolsonmi/met2010/syllabus',
            None,
        ),
        ('https://sites.google.com/view/kefulu/cs211_19W', None),
    ],
)
def test_repair_google_sites_url(url, res):
    assert repair_google_sites_url(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        (
            'https://openlab.citytech.cuny.edu/',
            'https://citytech.cuny.edu/',
        ),
        (
            'http://faculty.lagcc.cuny.edu',
            'http://lagcc.cuny.edu',
        ),
        ('https://www.math.csi.cuny.edu/', 'https://csi.cuny.edu/'),
        ('https://stonecenter.gc.cuny.edu/', 'https://gc.cuny.edu/'),
        ('https://senate.qc.cuny.edu/', 'https://qc.cuny.edu/'),
        ('http://www.geo.hunter.cuny.edu/', 'http://hunter.cuny.edu/'),
        (  # Should match bmcc, but it's hard just based on URL.
            'https://bmccremmath.commons.gc.cuny.edu/',
            'https://gc.cuny.edu/',
        ),
        ('', None),
        (None, None),
        # XXX Google search prefix
        (
            'https://www.google.com/search?q=baruch.cuny.edu',
            'https://www.google.com/search?q=baruch.cuny.edu',
        ),
    ],
)
def test_repair_cuny_edu_url(url, res):
    assert repair_cuny_edu_url(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        (
            'https://web.archive.org/web/20030814022411/http:/www.pas.rochester.edu/~rajeev/PHY408/index.html',  # noqa
            'http://www.pas.rochester.edu/~rajeev/PHY408/index.html',
        ),
        ('', None),
        (None, None),
        # TODO: Add more cases
    ],
)
def test_clean_wayback_url(url, res):
    assert clean_wayback_url(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        (
            'https://web.archive.org/web/20030814022411/http:/example.com',
            'http://example.com',
        ),
        (
            'https://web.archive.org/web/20030814022411/http://example.com',
            'http://example.com',
        ),
        (
            'https://web.archive.org/web/20030814022411/http://///example.com',
            'http://example.com',
        ),
        (
            'https://web.archive.org/web/20030814022411/ftp:/example.com',
            'ftp://example.com',
        ),
        (
            'https://web.archive.org/web/2/http://example.com',
            'http://example.com',
        ),
        (
            'https://web.archive.org/web/2/http://example.com',
            'http://example.com',
        ),
        (
            'https://wayback.archive-it.org/194/20090804164317/http://example.com',  # noqa
            'http://example.com',
        ),
        # NOTE: The below isn't like any real Wayback URL, but our
        # method matches against it anyway.
        (
            'https://web.archive.org/web/2/15/15/16/http://example.com',
            'http://example.com',
        ),
        (
            'notawaybacklink.com',
            'http://notawaybacklink.com',
        ),
    ],
)
def test_wayback_url(url, res):
    assert repair_scheme(clean_wayback_url(url)) == res


@pytest.mark.parametrize(
    'url,res',
    [
        ('http://example.com/path', 'path'),
        ('http://example.com/', None),
        ('http://example.com/path1/path2', 'path1'),
        ('http://www.example.com/path', 'path'),
    ],
)
def test_get_path_prefix(url, res):
    assert get_path_prefix(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        ('http://www.example.com/path', 'example.com'),
        ('http://web.example.com/', 'example.com'),
        ('http://custom.example.com/', 'custom.example.com'),
        ('http://example.com/', 'example.com'),
        ('https://www.qc.cuny.edu', 'qc.cuny.edu'),
    ],
)
def test_exclude_subdomain(url, res):
    tld = tldextract.extract(url)
    assert exclude_subdomain(tld) == res


@pytest.mark.parametrize(
    'url,res',
    [
        ('bare.com', 'bare.com'),
        ('http://google.com', 'google.com'),
        ('http://www.google.com', 'google.com'),
        ('https://bar.example.com', 'bar.example.com'),
        ('https://foo.example.com', 'foo.example.com'),
        ('https://mail.example.com', 'example.com'),
        ('bare.com', 'bare.com'),
        ('', None),
        (None, None),
        ('this.is.bogus', None),
    ],
)
def test_get_get_full_url(url, res):
    assert get_full_url(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        ('bare.com', 'bare.com'),
        ('http://google.com', 'google.com'),
        ('http://www.google.com', 'google.com'),
        ('https://bar.example.com', 'bar.example.com'),
        ('https://foo.example.com', 'foo.example.com'),
        ('https://mail.example.com', 'example.com'),
        ('bare.com', 'bare.com'),
        ('', None),
        (None, None),
        ('this.is.bogus', None),
    ],
)
def test_get_domain_url(url, res):
    assert get_domain_url(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        ('bare.com', 'bare.com'),
        ('http://google.com', 'google.com'),
        ('http://www.google.com', 'google.com'),
        ('https://bar.example.com', 'example.com'),
        ('https://foo.example.com', 'example.com'),
        ('https://mail.example.com', 'example.com'),
        ('bare.com', 'bare.com'),
        ('', None),
        (None, None),
        ('this.is.bogus', None),
    ],
)
def test_get_base_domain_url(url, res):
    assert get_base_domain_url(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        ('foo@harvard.edu', 'harvard.edu'),
        ('in random hi@mail.example.com', 'example.com'),
        ('', None),
        (None, None),
    ],
)
def test_get_email_domain_url(url, res):
    assert get_email_domain_url(url) == res


@pytest.mark.parametrize(
    'url,res',
    [
        ('foo@harvard.edu', 'harvard.edu'),
        ('in random hi@mail.example.com', 'example.com'),
        ('', None),
        (None, None),
    ],
)
def test_get_email_base_domain_url(url, res):
    assert get_email_base_domain_url(url) == res
