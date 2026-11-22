"""Matcher file format: gzip-compressed JSON.

    {"format": 1, "normalizer_version": "0.1.1",
     "institutions": [{...}, ...], "lookup": {"<key>": <index>, ...}}

Loading never executes code. The lookup keys are normalizer outputs, so the
file records the os-normalizer version it was built with.
"""

import gzip
import json
import warnings
import zlib
from pathlib import Path

import os_normalizer

FORMAT = 1


def save(table: dict, path: Path | str) -> None:
    """Write `table` ({'institutions': [...], 'lookup': {...}}) to `path`.

    The bytes depend only on the table and the zlib build: lookup keys are
    sorted, and the gzip header carries no name or timestamp.
    """
    document = {
        'format': FORMAT,
        'normalizer_version': getattr(os_normalizer, '__version__', None),
        'institutions': table['institutions'],
        'lookup': dict(sorted(table['lookup'].items())),
    }
    data = json.dumps(
        document, ensure_ascii=False, separators=(',', ':'), allow_nan=False
    ).encode('utf-8')
    with open(path, 'wb') as fh:
        with gzip.GzipFile(
            filename='', mode='wb', fileobj=fh, compresslevel=9, mtime=0
        ) as gz:
            gz.write(data)


def load(path: Path | str) -> dict:
    """Read a matcher file into {'institutions': [...], 'lookup': {...}}."""
    try:
        with gzip.open(path, 'rb') as fh:
            document = json.load(fh)
    except (EOFError, zlib.error, ValueError, gzip.BadGzipFile) as error:
        raise ValueError(f'{path} is not a matcher file: {error}') from error

    if not isinstance(document, dict) or document.get('format') != FORMAT:
        found = document.get('format') if isinstance(document, dict) else None
        raise ValueError(
            f'{path}: unsupported matcher format {found!r}, expected {FORMAT}'
        )
    institutions, lookup = document.get('institutions'), document.get('lookup')
    if not isinstance(institutions, list) or not isinstance(lookup, dict):
        raise ValueError(f'{path} is not a matcher file: bad tables')

    built_with = document.get('normalizer_version')
    installed = getattr(os_normalizer, '__version__', None)
    if built_with and installed and built_with != installed:
        warnings.warn(
            f'{path} was built with os-normalizer {built_with}, but '
            f'{installed} is installed; lookups may miss.',
            stacklevel=2,
        )
    return {'institutions': institutions, 'lookup': lookup}
