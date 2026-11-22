import os
from pathlib import Path

DATA_DIR = Path(__file__).parent / 'data'

# File name of each pipeline stage's output, under <artifacts>/<stage>/.
OUTPUTS = {
    'ror_dist': 'ror_dist.parquet',
    'ror': 'ror.parquet',
    'wikidata_dist': 'wikidata_dist.parquet',
    'wikidata': 'wikidata.parquet',
    'wikipedia': 'wikipedia.parquet',
    'ipeds': 'ipeds.parquet',
    'dataset': 'institutions.parquet',
    'matcher': 'matcher.pickle',
}


def artifacts_dir() -> Path:
    """Local, git-ignored directory holding the stage outputs."""
    return Path(os.environ.get('OS_INSTITUTIONS_ARTIFACTS_DIR', 'artifacts'))


def artifact_path(stage: str) -> Path:
    """Default local path of a stage's output."""
    return artifacts_dir() / stage / OUTPUTS[stage]


def validation_path() -> Path:
    """Default local path of the matcher validation table."""
    return artifacts_dir() / 'validation' / 'validation.csv'


def runs_dir() -> Path:
    """Directory of per-run logs (committed to git)."""
    return Path(os.environ.get('OS_INSTITUTIONS_RUNS_DIR', 'runs'))


def metrics_dir() -> Path:
    """Directory of per-stage metrics (committed to git)."""
    return Path(os.environ.get('OS_INSTITUTIONS_METRICS_DIR', 'metrics'))


def params_path() -> Path:
    """The DVC params file, which also holds the source version pins."""
    return Path(os.environ.get('OS_INSTITUTIONS_PARAMS', 'params.yaml'))
