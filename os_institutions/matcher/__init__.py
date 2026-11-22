from pathlib import Path

from os_institutions.matcher.matcher import (  # noqa
    Institution,
    InstitutionMatcher,
)
from os_institutions.paths import artifact_path


def model_path() -> Path:
    """Default local path of the built matcher (the `matcher` stage output)."""
    return artifact_path('matcher')


def load_model(path: Path | str | None = None):
    return InstitutionMatcher.load(path or model_path())
