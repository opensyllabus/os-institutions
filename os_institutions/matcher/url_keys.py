"""Lookup keys derived from institution URLs.

A key is either a bare domain (`dal.ca`) or a domain plus path segments
(`dal.ca/faculty/engineering`). Registering only the first path segment of a
sub-unit's deep URL (`dal.ca/faculty`) would send every link under that
segment to the sub-unit, so:

* deep URLs (2+ segments) are registered under their full normalized path;
* a first-segment key is registered only for a URL that is exactly one
  segment, or for a deep URL whose first segment is clearly tied to the
  institution, and never when the segment is generic or claimed by several
  institutions;
* at query time the longest registered path prefix wins.

This module only depends on os-normalizer's public domain/URL helpers so it
can be used by both the build and the matcher.
"""

import re
from urllib.parse import urlparse

from os_normalizer.institution import normalize_school_name
from os_normalizer.uri import EXCLUDED_PATH_PREFIX, get_domain_url, repair_url

_EXTENSION = re.compile(r'\.(html?|php|aspx?|jsp|cfm|shtml)$')
_LOCALE = re.compile(r'[a-z]{2}[-_][a-z]{2}')
_INDEX = {'index', 'default'}

# First segments that describe a kind of page or a language rather than a
# particular institution.
GENERIC_SEGMENTS = frozenset(
    '''
    en english eng home pages page site sites web de fr es it pt ru ar fa tr
    ca portal main bin university univ college school campus campuses about
    academics academic faculty faculties dept department departments study
    studies research education index default wp cms html login new v2
    contents content domain accueil p redir admin staff students student
    programs program courses course people news events services entidades
    organizations undergraduate graduate admissions
    '''.split()
)


def path_segments(url):
    """Normalized path segments (lowercase, no extension or index page)."""
    if not url:
        return []
    path = urlparse(url.lower()).path
    segments = (_EXTENSION.sub('', s) for s in path.split('/') if s)
    return [s for s in segments if s and s not in _INDEX]


def is_generic(segment):
    return (
        segment in GENERIC_SEGMENTS
        or '.' in segment
        or len(segment) <= 2
        or bool(_LOCALE.fullmatch(segment))
    )


def _words(text):
    return re.findall(r'[a-z0-9]+', (text or '').lower())


def segment_matches_name(segment, name):
    """True if a path segment looks like part of the institution's name,
    or an acronym of it."""
    seg = re.sub(r'[^a-z0-9]', '', segment)
    if not seg:
        return False
    words = _words(name)
    normalized = _words(normalize_school_name(name) or '')
    if seg in words or seg in normalized:
        return True
    if len(seg) >= 3 and any(
        w.startswith(seg) or (seg.startswith(w) and len(w) >= 4) for w in words
    ):
        return True
    stop = ('of', 'the', 'and', 'for', 'at', 'in')
    if seg == ''.join(w[0] for w in words) or seg == ''.join(
        w[0] for w in words if w not in stop
    ):
        return True
    return len(seg) >= 4 and seg in ''.join(words)


def owner_name_in_name(domain_owner_name, name):
    """True if the domain owner's name is contained in the institution's
    name (`University of Alberta` in `University of Alberta Augustana`)."""
    owner = (
        normalize_school_name(domain_owner_name)
        or (domain_owner_name or '').lower()
    )
    inst = normalize_school_name(name) or (name or '').lower()
    return bool(owner) and owner in inst


def url_key_candidates(url):
    """Split a URL into (domain, segments), or None if it has no valid
    domain."""
    domain = get_domain_url(url)
    if not domain:
        return None
    return domain, path_segments(url)


def path_prefix_keys(url):
    """Keys to try for a query URL, longest path prefix first. The bare
    domain is included only for URLs without a usable path, as with
    `get_full_url`; otherwise it is left to the later domain lookups."""
    url = repair_url(url)
    cand = url_key_candidates(url)
    if not cand:
        return []
    domain, segs = cand
    if not segs or segs[0] in EXCLUDED_PATH_PREFIX:
        return [domain]
    return [f'{domain}/' + '/'.join(segs[:i]) for i in range(len(segs), 0, -1)]


def _mode(idxs):
    """Most common index; ties go to the first one seen (as Counter does)."""
    counts = {}
    for i in idxs:
        counts[i] = counts.get(i, 0) + 1
    if counts:
        return max(counts, key=counts.get)


def build_url_key_table(institutions):
    """Map URL keys to institution indices.

    `institutions` is an iterable of `(idx, names, urls)` where `names` is
    the institution's name(s), the first being its primary name.
    Returns `{key: idx}`.
    """
    institutions = [(i, list(n), list(u)) for i, n, u in institutions]
    names_of = {i: n for i, n, _ in institutions}

    domain_all, domain_bare = {}, {}  # domain -> [idx], one per URL
    full_keys = {}  # domain/seg1/../segN -> [idx]
    first_claims = {}  # domain/seg1 -> {idx: [(deep, segment)]}
    for idx, _, urls in institutions:
        for url in urls:
            cand = url_key_candidates(url)
            if not cand:
                continue
            domain, segs = cand
            domain_all.setdefault(domain, []).append(idx)
            if not segs:
                domain_bare.setdefault(domain, []).append(idx)
                continue
            if len(segs) >= 2:
                key = f'{domain}/' + '/'.join(segs)
                full_keys.setdefault(key, []).append(idx)
            first_claims.setdefault(f'{domain}/{segs[0]}', {}).setdefault(
                idx, []
            ).append(len(segs) >= 2)

    table = {}

    # The bare domain belongs to the institution whose URL is that domain,
    # falling back to the most common claimant.
    for domain, idxs in domain_all.items():
        table[domain] = _mode(domain_bare.get(domain) or idxs)

    for key, idxs in full_keys.items():
        table[key] = _mode(idxs)

    for key, claims in first_claims.items():
        domain, segment = key.split('/')
        if is_generic(segment) or len(claims) != 1:
            continue
        ((idx, deep),) = claims.items()
        if any(deep):
            # A deep URL says little about its first segment unless that
            # names the institution or the institution is the domain owner's.
            owner = table[domain]
            if not (
                any(segment_matches_name(segment, n) for n in names_of[idx])
                or any(
                    owner_name_in_name(o, n)
                    for o in names_of[owner][:1]
                    for n in names_of[idx][:1]
                )
            ):
                continue
        # setdefault: an exact deep URL registered above is more specific
        table.setdefault(key, idx)
    return table
