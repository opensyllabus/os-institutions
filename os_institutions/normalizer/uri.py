import re
from urllib.parse import urlparse

from tldextract.tldextract import extract as tldextract

EXCLUDED_SUBDOMAINS = {
    'www',
    'web',
    'mail',
    'www1',
    'www2',
    'www3',
    'www4',
    'ww1',
    'ww2',
    'ww3',
    'ww4',
    'en',
    'eng',
    'english',
    'faculty',
}

EXCLUDED_EMAIL_DOMAINS = {'gmail', 'yahoo', 'outlook'}

EXCLUDED_PATH_PREFIX = {'content'}

URL_PATTERN = re.compile(
    r"https?://((web\.archive\.org/web)|(wayback\.archive-it\.org))/[0-9/]+/(?P<url>.*)"  # noqa: E501
)


def repair_wayback_url(url: str | None) -> str | None:
    """Most of the time, the URL on the path of a Wayback machine
    link we're trying to extract only has only has ':/' following the
    scheme instead of '://'.  This interferes in various ways with
    further parsing of the URL, so ensure that a the scheme is always
    followed with '://'.
    Ex: The Wayback link
    https://web.archive.org/web/20030814022411/http:/www.pas.rochester.edu/~rajeev/PHY408/index.html
    has this URL extracted from it:
    http:/www.pas.rochester.edu/~rajeev/PHY408/index.html.
    So, we transform that URL to
    http://www.pas.rochester.edu/~rajeev/PHY408/index.html
    """
    if url:
        return re.sub(r"^(\w+):/+", r"\1://", url)


def clean_wayback_url(url: str | None) -> str | None:
    """pre-clean URLs for archive.org, etc"""
    if url:
        if match := URL_PATTERN.match(url):
            clean_url = match.group('url')
            return repair_wayback_url(clean_url)
        return url


def repair_google_sites_url(url: str | None):
    """Remove anchor prefix from google sites URLs such as
    https://sites.google.com/a/g.clemson.edu/cpsc-8810/
    """
    if url:
        if 'sites.google.com/a/' in url:
            return url.replace('sites.google.com/a/', '')
        elif 'sites.google.com' in url:
            return None
        return url


def repair_cuny_edu_url(url: str | None):
    """Everything with cuny.edu shouldn't point to City University of New York
    by default. This happens because xxx.xxx.cuny.edu (depth=2) for most URLs
    with cuny.edu base domain.

    XXX: Generalize this to all domains by limiting depth of subdomain to 1?
    XXX: This should be handled under domain for efficiency.
    """
    if url:
        if '.cuny.edu' in url:
            tld = tldextract(url)
            subdomains = tld.subdomain.split('.')

            return url.replace(tld.subdomain, subdomains[-1])
        return url


def repair_scheme(url: str | None) -> str | None:
    """Prevent urllib.urlparse() from returning a ParseResult with
    a blank ('') netloc if scheme is abscent.
    """
    if url:
        if not (
            url.startswith('//')
            or url.startswith('http://')
            or url.startswith('https://')
            or url.startswith('ftp://')
        ):
            return 'http://' + url
        return url


def get_path_prefix(url):
    """Extract only the 2nd path component"""
    paths = urlparse(url).path.split('/', 2)

    if (
        len(paths) > 1
        and (path_prefix := paths[1])
        and (path_prefix not in EXCLUDED_PATH_PREFIX)
    ):
        return path_prefix


def exclude_subdomain(tld, exclude=EXCLUDED_SUBDOMAINS):
    subdomain = '.'.join(
        x for x in tld.subdomain.split('.') if x not in exclude
    )

    if subdomain:
        return f'{subdomain}.{tld.domain}.{tld.suffix}'
    else:
        return f'{tld.domain}.{tld.suffix}'


def valid_domain_url(tld):
    return tld.domain and tld.suffix


def valid_email_domain(tld):
    return tld.domain not in EXCLUDED_EMAIL_DOMAINS


def repair_url(url: str | None):
    url = repair_scheme(clean_wayback_url(url))
    url = repair_google_sites_url(url)
    return repair_cuny_edu_url(url)


def get_full_url(url: str | None) -> str | None:
    if url:
        url = url.lower()
        tld = tldextract(url)

        if valid_domain_url(tld):
            domain = exclude_subdomain(tld)

            if path := get_path_prefix(url):
                return f'{domain}/{path}'
            else:
                return domain


def get_domain_url(url: str | None) -> str | None:
    if url:
        url = url.lower()
        tld = tldextract(url)

        if valid_domain_url(tld):
            return exclude_subdomain(tld)


def get_base_domain_url(url: str | None) -> str | None:
    if url:
        url = url.lower()
        tld = tldextract(url)

        if valid_domain_url(tld):
            return f'{tld.domain}.{tld.suffix}'


def get_email_domain_url(email: str | None) -> str | None:
    if email:
        email = email.lower()
        tld = tldextract(email)

        if valid_domain_url(tld) and valid_email_domain(tld):
            return exclude_subdomain(tld)


def get_email_base_domain_url(email: str | None) -> str | None:
    if email:
        email = email.lower()
        tld = tldextract(email)

        if valid_domain_url(tld) and valid_email_domain(tld):
            return f'{tld.domain}.{tld.suffix}'
