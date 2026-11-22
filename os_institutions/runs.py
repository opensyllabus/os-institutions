"""Per-run logs for pipeline stages.

Each stage runs inside `start(stage)`, which creates
`runs/<UTC timestamp>-<stage>/` holding:

- `run.log`      the loguru output of that run
- `run.json`     what ran: stage, git commit, versions, params, sha256 of the
                 inputs and outputs, and source version info
- `summary.json` what came out (rows and cols for a dataset)

`runs/` is committed to git, so nothing environment-specific is recorded: no
e-mail addresses, home or absolute paths, git remotes, or environment
variables. The summary is also copied to `metrics/<stage>.json`, which DVC
reads as the stage's metrics.
"""

import hashlib
import json
import platform
import re
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from io import StringIO
from pathlib import Path

from loguru import logger

from os_institutions.paths import metrics_dir, runs_dir

PACKAGES = [
    'os-institutions',
    'pandas',
    'numpy',
    'pyarrow',
    'pandera',
    'requests',
    'loguru',
]

# Files that change on every run and so do not make a checkout "dirty".
GIT_STATUS_IGNORE = ['runs', 'metrics', 'dvc.lock']

LOG_FORMAT = (
    '{time:YYYY-MM-DD HH:mm:ss.SSS!UTC} | {level: <8} | '
    '{name}:{function}:{line} - {message}'
)

EMAIL = re.compile(r'[\w.+-]+@[\w-]+(\.[\w-]+)+')
S3_URI = re.compile(r's3://\S+')
GIT_REMOTE = re.compile(r'git@[\w.-]+:\S+|https?://\S+\.git\b')


def sanitize(text: str) -> str:
    """Strip what must not be committed: working and home directories, e-mail
    addresses, S3 locations and git remotes."""
    for path, repl in ((Path.cwd().resolve(), '.'), (Path.home(), '~')):
        if str(path) not in ('/', '.'):
            text = text.replace(str(path), repl)
    text = S3_URI.sub('<s3-uri>', text)
    text = GIT_REMOTE.sub('<git-remote>', text)
    return EMAIL.sub('<email>', text)


def clean(obj):
    """`sanitize` every string in a JSON-like structure."""
    if isinstance(obj, str):
        return sanitize(obj)
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, Path):
        return sanitize(str(obj))
    return obj


def display_path(path) -> str:
    """Path relative to the working directory, or just the file name when it
    lies outside (so an absolute path is never recorded)."""
    path = Path(path).resolve()
    try:
        return path.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def git_info() -> dict:
    """Commit sha and whether tracked or new source files differ from it.

    Only the sha and a dirty flag are recorded, never remotes or config.
    """
    try:
        sha = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        status = subprocess.run(
            ['git', 'status', '--porcelain', '--', '.']
            + [f':(exclude){p}' for p in GIT_STATUS_IGNORE],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {'sha': None, 'dirty': None}
    return {'sha': sha, 'dirty': bool(status.strip())}


def package_versions() -> dict:
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def now() -> datetime:
    return datetime.now(timezone.utc)


def write_json(path, data):
    with open(path, 'w') as fh:
        json.dump(clean(data), fh, indent=2, sort_keys=True, default=str)
        fh.write('\n')


@dataclass
class Run:
    stage: str
    dir: Path
    params: dict = field(default_factory=dict)
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def add_input(self, path):
        """Record an upstream file by its sha256."""
        self.inputs[display_path(path)] = sha256(path)

    def add_output(self, path):
        """Record a produced file by its sha256."""
        self.outputs[display_path(path)] = sha256(path)

    def set_source(self, **info):
        """Record which version of an external source was used (ROR release
        file, IPEDS year, ...)."""
        self.source.update(info)

    def summarize(self, **values):
        self.summary.update(values)

    def log_info(self, df):
        """Log the dataframe info and record its size in the summary."""
        buf = StringIO()
        df.info(buf=buf)
        logger.info(buf.getvalue())

        rows, cols = df.shape
        self.summarize(rows=rows, cols=cols)


def new_run_dir(stage: str, started: datetime, root: Path) -> Path:
    stamp = started.strftime('%Y%m%dT%H%M%SZ')
    root.mkdir(parents=True, exist_ok=True)
    path = root / f'{stamp}-{stage}'
    n = 0
    while True:
        try:
            path.mkdir()
            return path
        except FileExistsError:
            n += 1
            path = root / f'{stamp}-{stage}-{n}'


@contextmanager
def start(stage: str, params: dict | None = None):
    """Run a stage with a log directory under `runs/`.

    Yields a `Run`; use it to record inputs, outputs, source info and the
    summary. The files are written when the block exits, `status` in
    `run.json` telling whether it succeeded. The summary is copied to
    `metrics/<stage>.json` only on success.
    """
    started = now()
    run = Run(
        stage=stage,
        dir=new_run_dir(stage, started, runs_dir()),
        params=dict(params or {}),
    )

    info = {
        'stage': stage,
        'started_at': started.isoformat(timespec='seconds'),
        'git': git_info(),
        'python': platform.python_version(),
        'packages': package_versions(),
    }

    def write_run_json(**extra):
        write_json(
            run.dir / 'run.json',
            {
                **info,
                'params': run.params,
                'inputs': run.inputs,
                'outputs': run.outputs,
                'source': run.source,
                **extra,
            },
        )

    write_run_json(status='running')

    log_file = open(run.dir / 'run.log', 'w', buffering=1, encoding='utf-8')
    sink = logger.add(
        lambda message: log_file.write(sanitize(str(message))),
        format=LOG_FORMAT,
        level='INFO',
        colorize=False,
    )
    logger.info(f'Starting {stage} run in {display_path(run.dir)}')

    status, error = 'ok', None
    try:
        yield run
    except BaseException as e:
        status, error = 'failed', type(e).__name__
        logger.exception(f'{stage} run failed')
        raise
    finally:
        finished = now()
        logger.remove(sink)
        log_file.close()

        write_run_json(
            status=status,
            error=error,
            finished_at=finished.isoformat(timespec='seconds'),
            duration_seconds=round((finished - started).total_seconds(), 1),
        )
        if status == 'ok':
            write_json(run.dir / 'summary.json', run.summary)
            out = metrics_dir()
            out.mkdir(parents=True, exist_ok=True)
            write_json(out / f'{stage}.json', run.summary)
