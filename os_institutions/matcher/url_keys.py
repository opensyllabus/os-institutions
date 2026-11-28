"""Lookup keys derived from institution URLs.

A key is a bare domain (`dal.ca`) or a domain plus the full normalized path of
an institution URL (`purdue.edu/campuses/indianapolis`). Only schools are
kept (see data/blacklists/units.csv), so a path means a different school or
campus sharing the domain, never a department of the domain's owner.

* every institution URL registers its full path (extension and index page
  stripped), never a shorter prefix of it;
* the bare domain belongs to the institution whose URL is that domain, else
  to the most common claimant;
* at query time the longest registered path prefix wins, and a link that
  matches no path falls through to the domain (`www.dal.ca/faculty/x` is
  Dalhousie).

This module only depends on os-normalizer's public domain/URL helpers so it
can be used by both the build and the matcher.
"""

import re
from collections import Counter
from urllib.parse import urlparse

from os_normalizer.uri import EXCLUDED_PATH_PREFIX, get_domain_url, repair_url

_EXTENSION = re.compile(r'\.(html?|php|aspx?|jsp|cfm|shtml)$')
_INDEX = {'index', 'default'}
# A landing page under a path (`/florida/home`) is the path (`/florida`).
_LANDING = {'home', 'main'}


def path_segments(url):
    """Normalized path segments (lowercase, no extension or index page)."""
    if not url:
        return []
    path = urlparse(url.lower()).path
    segments = (_EXTENSION.sub('', s) for s in path.split('/') if s)
    segments = [s for s in segments if s and s not in _INDEX]
    if len(segments) > 1 and segments[-1] in _LANDING:
        segments.pop()
    return segments


def _split(url):
    """`(domain, segments)` of a URL, or None if it has no valid domain.
    Segments are empty for a bare domain, or for a path that is only an
    os-normalizer excluded prefix (`/content`). A longer path under one
    (`/content/71`) is kept whole: it can be a campus of its own."""
    domain = get_domain_url(url)
    if not domain:
        return None
    segments = path_segments(url)
    if len(segments) == 1 and segments[0] in EXCLUDED_PATH_PREFIX:
        segments = []
    return domain, segments


def path_prefix_keys(url):
    """Keys to try for a query URL, longest path prefix first. The bare
    domain is included only for URLs without a usable path; otherwise it is
    left to the later domain lookups."""
    split = _split(repair_url(url))
    if not split:
        return []
    domain, segments = split
    if not segments:
        return [domain]
    return [
        f'{domain}/' + '/'.join(segments[:i])
        for i in range(len(segments), 0, -1)
    ]


def _mode(idxs):
    """Most common index; ties go to the first one seen (as Counter does)."""
    return Counter(idxs).most_common(1)[0][0]


def build_url_key_table(institutions):
    """Map URL keys to institution indices.

    `institutions` is an iterable of `(idx, urls)`. Returns `{key: idx}`.
    """
    domains = {}  # domain -> [idx], one per URL
    bare = {}  # domain -> [idx] for URLs that are the bare domain
    paths = {}  # domain/seg1/../segN -> [idx]
    for idx, urls in institutions:
        for url in urls:
            if not (split := _split(url)):
                continue
            domain, segments = split
            domains.setdefault(domain, []).append(idx)
            if segments:
                key = f'{domain}/' + '/'.join(segments)
                paths.setdefault(key, []).append(idx)
            else:
                bare.setdefault(domain, []).append(idx)

    table = {d: _mode(bare.get(d) or idxs) for d, idxs in domains.items()}
    table.update({k: _mode(idxs) for k, idxs in paths.items()})
    return table
