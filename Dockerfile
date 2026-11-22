FROM python:3.10-slim

ARG CODE_DIR=/opt/os-institutions

# System-level dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends \
  curl \
  git \
  && rm -rf /var/lib/apt/lists/*

# Install Poetry.
RUN curl -sSL https://install.python-poetry.org | POETRY_VERSION=1.8.5 python -
ENV PATH=$PATH:/root/.local/bin
RUN poetry config virtualenvs.create false

# DVC drives the pipeline from the command line. It lives in its own venv so
# it never changes the pinned library dependencies, and no library code
# imports it.
ARG DVC_VERSION=3.67.1
RUN python -m venv /opt/dvc \
  && /opt/dvc/bin/pip install --no-cache-dir "dvc==${DVC_VERSION}" \
  && ln -s /opt/dvc/bin/dvc /usr/local/bin/dvc

WORKDIR $CODE_DIR

# The repository is bind-mounted at run time and owned by another user, which
# git (and so DVC) refuses to use unless it is marked as safe.
RUN git config --global --add safe.directory $CODE_DIR

# Install poetry dependencies (cached unless the lockfile changes).
ADD ./pyproject.toml ./poetry.lock $CODE_DIR/
RUN poetry install --no-root && rm -rf ~/.cache

# Add source code, install the module.
ADD . $CODE_DIR
RUN poetry install && rm -rf ~/.cache
