"""Hosts that must never identify an institution.

A lookup key such as `facebook.com` or `linkedin.com/redir` is registered for
every institution whose `url` is a page on that host. When one institution's
only URL is a Facebook page, every Facebook link then matches it. The keys
are produced by os-normalizer's `get_full_url` / `get_domain_url`: the host
without `www`-like subdomains, plus the first path segment.

The matcher build skips these keys, and the matcher ignores them at query
time, so a matcher built before the denylist existed behaves the same.
"""

# A key is denied when its host is one of these or a subdomain of one
# (`m.facebook.com`, `sites.google.com`), with any path. No page on these
# hosts says which institution it belongs to.
SHARED_HOSTS = frozenset(
    {
        # Social media and media sharing
        'facebook.com',
        'instagram.com',
        'linkedin.com',
        'pinterest.com',
        'tiktok.com',
        'twitter.com',
        'x.com',
        'youtube.com',
        'youtu.be',
        'flickr.com',
        'vimeo.com',
        # Encyclopedias and registries
        'wikipedia.org',
        'wikidata.org',
        # Link shorteners and link pages
        'bit.ly',
        'goo.gl',
        'tinyurl.com',
        'linktr.ee',
        # Generic hosting: Google Sites/Docs/Drive, the Wayback Machine
        'google.com',
        'archive.org',
    }
)

# A key is denied only when it is exactly one of these (the bare host, no
# path). The host serves many institutions at `host/<tenant>`, so the bare
# key is shared but the tenant keys still point at one institution.
SHARED_ROOTS = frozenset(
    {
        'curricunet.com',
        'curriqunet.com',
    }
)


def is_shared_host(key: str | None) -> bool:
    """Whether a normalized URL lookup key is on a shared host."""
    if not key:
        return False

    host = key.split('/', 1)[0]

    if key == host and host in SHARED_ROOTS:
        return True

    return any(host == h or host.endswith(f'.{h}') for h in SHARED_HOSTS)
