from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version('os-institutions')
except PackageNotFoundError:  # pragma: no cover
    __version__ = '0.0.0'

from os_institutions.matcher import (  # noqa: E402
    Institution,
    InstitutionMatcher,
)
from os_institutions.release import (  # noqa: E402
    download,
    load_dataset,
    load_matcher,
)

__all__ = [
    'Institution',
    'InstitutionMatcher',
    '__version__',
    'download',
    'load_dataset',
    'load_matcher',
]
