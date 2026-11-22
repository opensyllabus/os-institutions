FROM python:3.10-slim

ARG CODE_DIR=/opt/os-institutions

# System-level dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends \
  curl \
  && rm -rf /var/lib/apt/lists/*

# Install Poetry.
RUN curl -sSL https://install.python-poetry.org | POETRY_VERSION=1.8.5 python -
ENV PATH=$PATH:/root/.local/bin
RUN poetry config virtualenvs.create false

WORKDIR $CODE_DIR

# Install poetry dependencies (cached unless the lockfile changes).
ADD ./pyproject.toml ./poetry.lock $CODE_DIR/
RUN poetry install --no-root && rm -rf ~/.cache

# Add source code, install the module.
ADD . $CODE_DIR
RUN poetry install && rm -rf ~/.cache
