"""Stage parameters from params.yaml.

`params.yaml` is a plain YAML file at the repository root. DVC tracks it (a
changed value re-runs the stage), and the library reads it directly, so a
stage behaves the same under `dvc repro` and when run by hand. Command-line
options override the file, and the file overrides the defaults in code.
"""

import yaml

from os_institutions.paths import params_path


def stage_params(stage: str) -> dict:
    """The `params.yaml` section of a stage ({} if there is none)."""
    path = params_path()
    if not path.exists():
        return {}
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    return dict(data.get(stage) or {})


def resolve(stage: str, defaults: dict | None = None, **overrides) -> dict:
    """Merge defaults < params.yaml < explicit (non-None) overrides."""
    params = {**(defaults or {}), **stage_params(stage)}
    params.update({k: v for k, v in overrides.items() if v is not None})
    return params
