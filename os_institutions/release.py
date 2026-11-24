"""Fetch the released matcher and dataset by version and load them.

Assets of a release `vX.Y.Z` (see README, "Release assets") are downloaded to
a cache directory, checked against the release's SHA256SUMS, and reused.
"""

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from os_institutions import __version__

REPO = 'opensyllabus/os-institutions'
DOWNLOAD_BASE = f'https://github.com/{REPO}/releases/download'
API_BASE = 'https://api.github.com'
ASSETS = ('matcher.json.gz', 'institutions.parquet', 'manifest.json')
SUMS = 'SHA256SUMS'


class _DropAuthOnNewHost(urllib.request.HTTPRedirectHandler):
    """Do not forward the token to the storage host GitHub redirects to."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and (
            urllib.parse.urlsplit(newurl).netloc
            != urllib.parse.urlsplit(req.full_url).netloc
        ):
            new.remove_header('Authorization')
        return new


_opener = urllib.request.build_opener(_DropAuthOnNewHost)


def _token() -> str | None:
    return os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')


def _open(url: str, accept: str | None = None, token: str | None = None):
    request = urllib.request.Request(url)
    if accept:
        request.add_header('Accept', accept)
    if token:
        request.add_header('Authorization', f'Bearer {token}')
    try:
        return _opener.open(request, timeout=60)
    except urllib.error.HTTPError as error:
        hint = ''
        if error.code in (401, 403, 404):
            hint = (
                ' The release or asset may not exist, or the token cannot'
                ' read the repository.'
                if token
                else ' The release or asset may not exist. For a private fork'
                ' or mirror, or if rate limited, set GITHUB_TOKEN (or'
                ' GH_TOKEN).'
            )
        raise RuntimeError(
            f'GET {url.split("?")[0]} failed: HTTP {error.code}.{hint}'
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f'Cannot reach {urllib.parse.urlsplit(url).netloc}'
            f' ({error.reason}) and the release is not in the local cache.'
        ) from error


def cache_dir() -> Path:
    root = os.environ.get('OS_INSTITUTIONS_CACHE')
    if not root:
        base = os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache'
        root = Path(base) / 'os-institutions'
    return Path(root)


def resolve_tag(version: str | None = None) -> str:
    """None is the release matching the installed package, 'latest' the newest
    non-prerelease; anything else is a tag ('1.0.0' means 'v1.0.0')."""
    if version is None:
        return f'v{__version__}'
    if version == 'latest':
        token = _token()
        url = f'{API_BASE}/repos/{REPO}/releases/latest'
        with _open(url, 'application/vnd.github+json', token) as response:
            return json.load(response)['tag_name']
    return version if version.startswith('v') else f'v{version}'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _download(tag: str, asset: str, dest: Path) -> None:
    token = _token()
    if token:
        url = f'{API_BASE}/repos/{REPO}/releases/tags/{tag}'
        with _open(url, 'application/vnd.github+json', token) as response:
            assets = {
                a['name']: a['id'] for a in json.load(response)['assets']
            }
        if asset not in assets:
            raise RuntimeError(f'Release {tag} has no asset {asset}.')
        url = f'{API_BASE}/repos/{REPO}/releases/assets/{assets[asset]}'
        response = _open(url, 'application/octet-stream', token)
    else:
        response = _open(f'{DOWNLOAD_BASE}/{tag}/{asset}')

    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f'.{asset}.')
    try:
        with response, os.fdopen(fd, 'wb') as fh:
            while chunk := response.read(1 << 20):
                fh.write(chunk)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _checksums(tag: str, directory: Path, refresh: bool = False) -> dict:
    path = directory / SUMS
    if refresh or not path.exists():
        _download(tag, SUMS, path)
    sums = {}
    for line in path.read_text().splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.lstrip('*')] = digest
    return sums


def fetch(asset: str, version: str | None = None) -> Path:
    """Return the local path of a release asset, downloading it if needed."""
    tag = resolve_tag(version)
    directory = cache_dir() / tag
    path = directory / asset

    for refresh in (False, True):
        expected = _checksums(tag, directory, refresh).get(asset)
        if expected is None:
            raise RuntimeError(
                f'{SUMS} of release {tag} does not list {asset}.'
            )
        if path.exists() and _sha256(path) == expected:
            return path
        _download(tag, asset, path)
        if _sha256(path) == expected:
            return path
        path.unlink()
        # A stale cached SHA256SUMS may be at fault: retry with a fresh one.
    raise RuntimeError(
        f'Checksum mismatch for {asset} of release {tag}: the downloaded file'
        f' does not match {SUMS}. Not using it.'
    )


def download(version: str | None = None) -> dict[str, Path]:
    """Fetch every asset of a release (e.g. at image build time)."""
    return {asset: fetch(asset, version) for asset in ASSETS}


def load_matcher(
    version: str | None = None, *, path: Path | str | None = None
):
    """The institution matcher of a release, or of a local matcher file."""
    from os_institutions.matcher import load_model

    return load_model(path or fetch('matcher.json.gz', version))


def load_dataset(
    version: str | None = None, *, path: Path | str | None = None
):
    """The institutions dataset of a release, or of a local parquet file,
    checked against the dataset schema."""
    from os_institutions import dataset

    return dataset.load(
        Path(path) if path else fetch('institutions.parquet', version)
    )
