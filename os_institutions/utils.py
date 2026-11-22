import io
from glob import glob
from io import StringIO
from zipfile import ZipFile

import pandas as pd
import requests
import wandb
import yaml
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def wandb_init(**kwargs):
    wandb.init(entity='opensyllabus', project='institutions', **kwargs)


def wandb_artifact(name, use_artifact=True, artifact_type='dataset'):
    if use_artifact:
        return wandb.use_artifact(name, type=artifact_type).download()
    else:
        return wandb.Api().artifact(name).download()


def wandb_create_reference(name, reference, artifact_type='dataset'):
    wandb_init()
    artifact = wandb.Artifact(name, type=artifact_type)
    artifact.add_reference(reference)
    wandb.log_artifact(artifact)


def first_file(dir):
    return sorted(glob(dir + '/*'))[0]


def log_info(df):
    buf = StringIO()
    df.info(buf=buf)
    logger.info(buf.getvalue())

    rows, cols = df.shape
    wandb.log({'rows': rows, 'cols': cols})


def read_yaml(path: str, columns=None, dtype=None, pandas=True):
    """Convert a YAML string to pandas object."""
    with open(path) as fh:
        data = yaml.safe_load(fh)

        if not pandas:
            return data

        df = pd.DataFrame(data.items(), columns=columns)

        if dtype:
            df = df.astype(dtype)

        return df


def download_zip_file(file_url):
    logger.info(f'Downloading {file_url}')
    resp = requests.get(file_url)

    zip_file = ZipFile(io.BytesIO(resp.content))
    logger.info(zip_file.namelist())

    return zip_file
