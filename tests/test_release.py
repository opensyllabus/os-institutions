import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import os_institutions
from os_institutions import release
from os_institutions.matcher import InstitutionMatcher, format

REPO = 'repos/opensyllabus/os-institutions'
TABLE = {
    'institutions': [{'_id': 1, 'name': 'Example University'}],
    'lookup': {'example.edu': 0},
}
V28 = Path.home() / '.os-institutions/export-v28/matcher/matcher.json.gz'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body=b'', headers=()):
        self.send_response(code)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        server = self.server
        auth = self.headers.get('Authorization')
        server.requests.append((self.path, auth))
        parts = self.path.strip('/').split('/')
        authorized = auth == 'Bearer secret'

        if parts[0] == 'download' and not server.private:
            body = server.releases.get(parts[1], {}).get(parts[2])
            return self.reply(*((200, body) if body is not None else (404,)))
        if parts[0] == 'storage':
            server.storage_auth.append(auth)
            return self.reply(200, server.assets[int(parts[1])])
        if not authorized and server.private:
            return self.reply(404)
        if self.path == f'/{REPO}/releases/latest':
            body = json.dumps({'tag_name': server.latest}).encode()
            return self.reply(200, body)
        if self.path.startswith(f'/{REPO}/releases/tags/'):
            files = server.releases.get(parts[-1])
            if files is None:
                return self.reply(404)
            assets = []
            for name, data in files.items():
                server.assets.append(data)
                assets.append({'name': name, 'id': len(server.assets) - 1})
            return self.reply(200, json.dumps({'assets': assets}).encode())
        if self.path.startswith(f'/{REPO}/releases/assets/'):
            assert self.headers['Accept'] == 'application/octet-stream'
            port = server.server_port
            location = f'http://localhost:{port}/storage/{parts[-1]}'
            return self.reply(302, headers=[('Location', location)])
        self.reply(404)


def make_release(tmp_path, tag='v1.0.0', corrupt=False):
    matcher = tmp_path / 'matcher.json.gz'
    format.save(TABLE, matcher)
    files = {
        'matcher.json.gz': matcher.read_bytes(),
        'institutions.parquet': b'parquet-bytes',
        'manifest.json': b'{}',
    }
    sums = ''.join(
        f'{hashlib.sha256(data).hexdigest()}  {name}\n'
        for name, data in files.items()
    )
    files['SHA256SUMS'] = sums.encode()
    if corrupt:
        files['institutions.parquet'] = b'tampered'
    return files


@pytest.fixture
def server(tmp_path, monkeypatch):
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    httpd.requests, httpd.storage_auth, httpd.assets = [], [], []
    httpd.private, httpd.latest = False, 'v1.0.0'
    httpd.releases = {'v1.0.0': make_release(tmp_path)}
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    base = f'http://127.0.0.1:{httpd.server_port}'
    monkeypatch.setattr(release, 'DOWNLOAD_BASE', f'{base}/download')
    monkeypatch.setattr(release, 'API_BASE', base)
    monkeypatch.setenv('OS_INSTITUTIONS_CACHE', str(tmp_path / 'cache'))
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GH_TOKEN', raising=False)
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def downloads(server):
    return [p for p, _ in server.requests if p.startswith('/download/')]


def test_fetch_downloads_verifies_and_reuses_the_cache(server, tmp_path):
    path = release.fetch('matcher.json.gz', '1.0.0')
    assert path == tmp_path / 'cache/v1.0.0/matcher.json.gz'
    assert format.load(path) == TABLE
    assert len(downloads(server)) == 2  # SHA256SUMS and the asset

    release.fetch('matcher.json.gz', 'v1.0.0')
    assert len(downloads(server)) == 2


def test_corrupt_cached_file_is_downloaded_again(server):
    path = release.fetch('matcher.json.gz', 'v1.0.0')
    path.write_bytes(b'garbage')
    assert format.load(release.fetch('matcher.json.gz', 'v1.0.0')) == TABLE


def test_download_that_fails_its_checksum_is_rejected(server, tmp_path):
    server.releases['v1.0.0'] = make_release(tmp_path, corrupt=True)
    with pytest.raises(RuntimeError, match='Checksum mismatch'):
        release.fetch('institutions.parquet', 'v1.0.0')
    assert not (tmp_path / 'cache/v1.0.0/institutions.parquet').exists()


def test_stale_cached_checksums_are_refreshed(server, tmp_path):
    release.fetch('matcher.json.gz', 'v1.0.0')
    sums = tmp_path / 'cache/v1.0.0/SHA256SUMS'
    sums.write_text('0' * 64 + sums.read_text()[64:])
    assert release.fetch('matcher.json.gz', 'v1.0.0').exists()


def test_version_resolution(server, monkeypatch):
    assert release.resolve_tag(None) == f'v{os_institutions.__version__}'
    assert release.resolve_tag('1.2.3') == 'v1.2.3'
    assert release.resolve_tag('v1.2.3') == 'v1.2.3'
    server.latest = 'v9.9.9'
    assert release.resolve_tag('latest') == 'v9.9.9'


def test_default_version_is_the_installed_package_version(server, monkeypatch):
    server.releases['v7.0.0'] = server.releases['v1.0.0']
    monkeypatch.setattr(release, '__version__', '7.0.0')
    release.fetch('manifest.json')
    assert any('/v7.0.0/' in p for p in downloads(server))


def test_unknown_release_names_the_token_for_private_repositories(server):
    with pytest.raises(RuntimeError, match='HTTP 404.*GITHUB_TOKEN'):
        release.fetch('matcher.json.gz', 'v2.0.0')


def test_offline_with_an_empty_cache(server, monkeypatch):
    monkeypatch.setattr(
        release, 'DOWNLOAD_BASE', 'http://127.0.0.1:9/download'
    )
    with pytest.raises(RuntimeError, match='local cache'):
        release.fetch('matcher.json.gz', 'v1.0.0')


def test_cached_release_works_offline(server, monkeypatch):
    release.fetch('matcher.json.gz', 'v1.0.0')
    monkeypatch.setattr(
        release, 'DOWNLOAD_BASE', 'http://127.0.0.1:9/download'
    )
    assert release.fetch('matcher.json.gz', 'v1.0.0').exists()


@pytest.mark.parametrize('variable', ['GITHUB_TOKEN', 'GH_TOKEN'])
def test_token_uses_the_api_and_is_not_sent_to_the_redirect(
    server, monkeypatch, variable
):
    server.private = True
    monkeypatch.setenv(variable, 'secret')
    path = release.fetch('matcher.json.gz', 'v1.0.0')
    assert format.load(path) == TABLE
    assert downloads(server) == []
    assert all(
        auth == 'Bearer secret'
        for p, auth in server.requests
        if p.startswith(f'/{REPO}')
    )
    assert server.storage_auth and set(server.storage_auth) == {None}


def test_private_release_without_a_token_fails_clearly(server):
    server.private = True
    with pytest.raises(RuntimeError, match='GITHUB_TOKEN'):
        release.fetch('matcher.json.gz', 'v1.0.0')


def test_load_matcher_from_a_release(server):
    matcher = os_institutions.load_matcher('1.0.0')
    assert isinstance(matcher, InstitutionMatcher)
    assert matcher.lookup('example.edu')['name'] == 'Example University'


def test_load_matcher_from_a_path_skips_the_network(server, tmp_path):
    path = tmp_path / 'local.json.gz'
    format.save(TABLE, path)
    assert os_institutions.load_matcher(path=path).lookup('example.edu')
    assert server.requests == []


def test_load_dataset_reads_the_release_parquet(server, monkeypatch):
    from os_institutions import loader

    seen = []
    monkeypatch.setattr(loader, 'load', lambda p: seen.append(p) or 'df')
    assert os_institutions.load_dataset('1.0.0') == 'df'
    assert seen[0].name == 'institutions.parquet'
    assert os_institutions.load_dataset(path='x.parquet') == 'df'
    assert seen[1] == Path('x.parquet')


def test_download_fetches_every_asset(server):
    paths = os_institutions.download('1.0.0')
    assert set(paths) == {
        'matcher.json.gz',
        'institutions.parquet',
        'manifest.json',
    }
    assert all(p.exists() for p in paths.values())


def test_public_names():
    assert os_institutions.Institution and os_institutions.__version__


@pytest.mark.skipif(not V28.exists(), reason='v28 export not present')
def test_load_the_converted_v28_matcher():
    matcher = os_institutions.load_matcher(path=V28)
    assert len(matcher.institutions) > 1000
