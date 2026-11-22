import os
from pathlib import Path

DATA_DIR = Path(__file__).parent / 'data'

# Local cache for downloaded artifacts (git-ignored).
ARTIFACTS_DIR = Path(
    os.environ.get(
        'OS_INSTITUTIONS_ARTIFACTS_DIR',
        Path(__file__).resolve().parent.parent / 'artifacts',
    )
)
