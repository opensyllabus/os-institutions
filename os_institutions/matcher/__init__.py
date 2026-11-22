import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import wandb
from loguru import logger

from os_institutions.matcher.matcher import (  # noqa
    Institution,
    InstitutionMatcher,
)
from os_institutions.paths import ARTIFACTS_DIR

ARTIFACT_NAME = 'opensyllabus/institutions/matcher:v28'


# TODO(W&B removal in PR #2): replace with a non-W&B artifact download.
@dataclass
class WandbFile:
    artifact: str
    path: str
    local_dir: Path = ARTIFACTS_DIR

    @property
    def local_name(self):
        """Convert a W&B artifact+path into a filename for the cached object -
        replace `/` with `__`.
        """
        return '__'.join(['wandb', *self.artifact.split('/'), self.path])

    @property
    def local_path(self):
        """The filesystem path of the cached object."""
        return Path(self.local_dir) / self.local_name

    def download(self):
        """Download the file to the local cache."""
        logger.info(
            f'Downloading {self.artifact}/{self.path} -> {self.local_path}'
        )

        # Ensure that the directory exists.
        self.local_path.parent.mkdir(parents=True, exist_ok=True)

        api = wandb.Api()
        artifact = api.artifact(self.artifact)

        tmp_dir = tempfile.TemporaryDirectory()
        src = artifact.get_entry(self.path).download(tmp_dir.name)

        shutil.move(src, self.local_path)

    def downloaded_path(self):
        """If the file isn't cached, download it. Return the local path."""
        if not self.local_path.exists():
            self.download()

        return self.local_path


artifact = WandbFile(artifact=ARTIFACT_NAME, path='matcher.pickle')


def download_data():
    artifact.download()


def load_model():
    return InstitutionMatcher.load(artifact.downloaded_path())
