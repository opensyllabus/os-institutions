import json
import re
import subprocess

import pandas as pd
import pytest

from os_institutions import runs


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Run in an empty directory with runs/ and metrics/ under it."""
    monkeypatch.chdir(tmp_path)
    for name in (
        'OS_INSTITUTIONS_RUNS_DIR',
        'OS_INSTITUTIONS_METRICS_DIR',
        'OS_INSTITUTIONS_ARTIFACTS_DIR',
        'OS_INSTITUTIONS_PARAMS',
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def read_json(path):
    return json.loads(path.read_text())


def test_start_writes_run_files(workdir):
    data = workdir / 'artifacts' / 'ror' / 'ror.parquet'
    data.parent.mkdir(parents=True)
    data.write_bytes(b'abc')
    df = pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})

    with runs.start('ror', params={'release': 'v2.16'}) as run:
        run.add_input(data)
        run.set_source(file='v2.16-ror-data.zip')
        run.log_info(df)
        run.add_output(data)

    (run_dir,) = (workdir / 'runs').iterdir()
    assert re.fullmatch(r'\d{8}T\d{6}Z-ror', run_dir.name)
    assert run_dir.name == run.dir.name

    info = read_json(run_dir / 'run.json')
    digest = runs.sha256(data)
    assert info['stage'] == 'ror'
    assert info['status'] == 'ok'
    assert info['params'] == {'release': 'v2.16'}
    assert info['inputs'] == {'artifacts/ror/ror.parquet': digest}
    assert info['outputs'] == {'artifacts/ror/ror.parquet': digest}
    assert info['source'] == {'file': 'v2.16-ror-data.zip'}
    assert info['python'].startswith('3.')
    assert info['packages']['pandas']
    assert set(info['git']) == {'sha', 'dirty'}
    assert info['finished_at'] >= info['started_at']

    assert read_json(run_dir / 'summary.json') == {'rows': 3, 'cols': 2}
    assert read_json(workdir / 'metrics' / 'ror.json') == {
        'rows': 3,
        'cols': 2,
    }
    assert 'Starting ror run' in (run_dir / 'run.log').read_text()


def test_sha256(tmp_path):
    path = tmp_path / 'f'
    path.write_bytes(b'abc')
    assert runs.sha256(path) == (
        'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    )


def test_log_captures_only_the_run(workdir):
    from loguru import logger

    logger.info('before the run')
    with runs.start('ror'):
        logger.info('inside the run')
        logger.warning('a warning')
    logger.info('after the run')

    (run_dir,) = (workdir / 'runs').iterdir()
    log = (run_dir / 'run.log').read_text()
    assert 'inside the run' in log
    assert 'a warning' in log
    assert 'WARNING' in log
    assert 'before the run' not in log
    assert 'after the run' not in log


def test_failed_run(workdir):
    with pytest.raises(ValueError):
        with runs.start('ror') as run:
            run.summarize(rows=1)
            raise ValueError('boom')

    (run_dir,) = (workdir / 'runs').iterdir()
    info = read_json(run_dir / 'run.json')
    assert info['status'] == 'failed'
    assert info['error'] == 'ValueError'
    assert 'Traceback' in (run_dir / 'run.log').read_text()
    # A failed run leaves no summary or metrics behind.
    assert not (run_dir / 'summary.json').exists()
    assert not (workdir / 'metrics').exists()


def test_same_second_runs_do_not_collide(workdir, monkeypatch):
    from datetime import datetime, timezone

    fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(runs, 'now', lambda: fixed)

    for _ in range(2):
        with runs.start('ror'):
            pass

    names = sorted(p.name for p in (workdir / 'runs').iterdir())
    assert names == ['20260102T030405Z-ror', '20260102T030405Z-ror-1']


def test_dirs_follow_environment(workdir, monkeypatch):
    monkeypatch.setenv('OS_INSTITUTIONS_RUNS_DIR', str(workdir / 'r'))
    monkeypatch.setenv('OS_INSTITUTIONS_METRICS_DIR', str(workdir / 'm'))

    with runs.start('ipeds') as run:
        run.summarize(rows=1, cols=1)

    assert len(list((workdir / 'r').iterdir())) == 1
    assert (workdir / 'm' / 'ipeds.json').exists()


def test_sanitize_strips_emails_and_paths(workdir, monkeypatch):
    home = workdir / 'home' / 'someone'
    home.mkdir(parents=True)
    monkeypatch.setenv('HOME', str(home))

    text = f'mail jane.doe+x@example.edu from {home}/data and {workdir}/x'
    out = runs.sanitize(text)

    assert 'example.edu' not in out
    assert '<email>' in out
    assert str(home) not in out
    assert str(workdir) not in out
    assert out.endswith('and ./x')


def test_display_path_never_absolute(workdir, tmp_path_factory):
    inside = workdir / 'artifacts' / 'a.parquet'
    outside = tmp_path_factory.mktemp('outside') / 'b.parquet'

    assert runs.display_path(inside) == 'artifacts/a.parquet'
    assert runs.display_path(outside) == 'b.parquet'


def test_nothing_private_is_written(workdir, monkeypatch):
    """Home paths, e-mail addresses, remotes and env vars stay out."""
    home = workdir / 'home' / 'someone'
    home.mkdir(parents=True)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('SECRET_TOKEN', 'hunter2-token')
    outside = home / 'private' / 'validation_input.csv'
    outside.parent.mkdir(parents=True)
    outside.write_text('x')

    from loguru import logger

    with runs.start(
        'ror', params={'owner': 'jane.doe@example.edu', 'path': str(outside)}
    ) as run:
        run.add_input(outside)
        logger.info(f'Loading {outside} for jane.doe@example.edu')

    (run_dir,) = (workdir / 'runs').iterdir()
    for path in run_dir.iterdir():
        text = path.read_text()
        assert 'example.edu' not in text
        assert str(home) not in text
        assert 'hunter2-token' not in text
        assert 'SECRET_TOKEN' not in text


def test_git_info_in_repo(workdir):
    def git(*args):
        subprocess.run(
            ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com']
            + list(args),
            check=True,
            capture_output=True,
        )

    git('init')
    (workdir / 'code.py').write_text('x = 1\n')
    git('add', 'code.py')
    git('commit', '-m', 'init')

    info = runs.git_info()
    assert re.fullmatch(r'[0-9a-f]{40}', info['sha'])
    assert info['dirty'] is False

    # Run outputs do not make the checkout dirty, source changes do.
    (workdir / 'runs').mkdir()
    (workdir / 'runs' / 'x.json').write_text('{}')
    (workdir / 'dvc.lock').write_text('schema: 2.0\n')
    assert runs.git_info()['dirty'] is False

    (workdir / 'code.py').write_text('x = 2\n')
    assert runs.git_info()['dirty'] is True


def test_git_info_outside_repo(workdir):
    assert runs.git_info() == {'sha': None, 'dirty': None}
