from os_institutions import params


def test_resolve_precedence(tmp_path, monkeypatch):
    path = tmp_path / 'params.yaml'
    path.write_text('ror_dist:\n  release: v2.16\nipeds:\n  year: 2023\n')
    monkeypatch.setenv('OS_INSTITUTIONS_PARAMS', str(path))

    defaults = {'api': 'https://example.org', 'release': 'latest'}

    # Defaults < params.yaml < explicit options (None means "not given").
    assert params.resolve('ror_dist', defaults) == {
        'api': 'https://example.org',
        'release': 'v2.16',
    }
    assert params.resolve('ror_dist', defaults, release='v2.1')['release'] == (
        'v2.1'
    )
    assert params.resolve('ror_dist', defaults, release=None)['release'] == (
        'v2.16'
    )
    assert params.resolve('ipeds') == {'year': 2023}


def test_resolve_without_params_file(tmp_path, monkeypatch):
    monkeypatch.setenv('OS_INSTITUTIONS_PARAMS', str(tmp_path / 'none.yaml'))

    assert params.stage_params('ror_dist') == {}
    assert params.resolve('ror_dist', {'release': 'latest'}) == {
        'release': 'latest'
    }
