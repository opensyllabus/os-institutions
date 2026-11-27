"""Hosts that must never identify an institution.

A lookup key such as `facebook.com` or `linkedin.com/redir` is registered for
every institution whose `url` is a page on that host. When one institution's
only URL is a Facebook page, every Facebook link then matches it. The keys
are produced by os-normalizer's `get_full_url` / `get_domain_url`: the host
without `www`-like subdomains, plus the first path segment.

The matcher build skips these keys, and the matcher ignores them at query
time, so a matcher built before the denylist existed behaves the same.

Google Sites is the exception. `sites.google.com` is shared, but a single site
(`sites.google.com/view/<name>`, `sites.google.com/site/<name>`,
`sites.google.com/<domain>/<name>`) belongs to one owner, and some
institutions have nothing else as their URL. os-normalizer cannot express
that: it keeps only the first path segment, so every `view/<name>` becomes
`sites.google.com/view`. `google_site_key` builds the per-site key instead.
"""

import re

import pandas as pd

from os_institutions.paths import DATA_DIR

DENYLIST_DIR = DATA_DIR / 'denylists'

def _read_hosts(name: str) -> frozenset[str]:
    return frozenset(pd.read_csv(DENYLIST_DIR / name)['host'])


# A key is denied when its host is one of these or a subdomain of one
# (`m.facebook.com`, `docs.google.com`), with any path. No page on these
# hosts says which institution it belongs to. The one exception is a single
# Google Site, see `google_site_key`.
SHARED_HOSTS = _read_hosts('shared_hosts.csv')

# A key is denied only when it is exactly one of these (the bare host, no
# path). The host serves many institutions at `host/<tenant>`, so the bare
# key is shared but the tenant keys still point at one institution.
SHARED_ROOTS = _read_hosts('shared_roots.csv')


GOOGLE_SITES = 'sites.google.com'

_SCHEME = re.compile(r'^[a-z][a-z0-9+.-]*://')


def google_site_key(url: str | None) -> str | None:
    """The lookup key of one Google Site: `sites.google.com/<first>/<name>`.

    `first` is `view`, `site` (classic Sites) or a Workspace domain, and
    `name` is the site's own name, so `.../view/<name>/home` and
    `.../view/<name>/page` share a key. Returns None for anything that does
    not name a site: the bare host, `view` or a domain without a site name,
    other Google hosts, and `sites.google.com/a/<domain>/...`, which
    os-normalizer already repairs to `<domain>/...`.
    """
    if not url:
        return None

    url = _SCHEME.sub('', url.strip().lower())
    url = re.split(r'[?#]', url, maxsplit=1)[0]
    parts = [p for p in url.split('/') if p]

    if len(parts) < 3 or parts[0] != GOOGLE_SITES or parts[1] == 'a':
        return None

    return '/'.join(parts[:3])


def is_shared_host(key: str | None) -> bool:
    """Whether a normalized URL lookup key is on a shared host."""
    if not key:
        return False

    host, _, path = key.partition('/')

    # A key from `google_site_key` identifies one site
    if host == GOOGLE_SITES:
        segments = path.split('/')
        if len(segments) == 2 and segments[0] != 'a':
            return False

    if key == host and host in SHARED_ROOTS:
        return True

    return any(host == h or host.endswith(f'.{h}') for h in SHARED_HOSTS)
