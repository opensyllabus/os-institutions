# syntax=docker/dockerfile:1
FROM python:3.10-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

ARG CODE_DIR=/opt/os-institutions
# Extra `uv sync` flags, e.g. UV_SYNC_ARGS="--group dvc" for pipeline runs.
ARG UV_SYNC_ARGS=""

# git: DVC needs it, and the repo is bind-mounted at run time.
RUN apt-get update && apt-get install -y --no-install-recommends git \
  && rm -rf /var/lib/apt/lists/*

# The venv lives outside CODE_DIR because CODE_DIR is bind-mounted at run time.
# UV_NO_SYNC stops `uv run` from re-syncing on every call.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_NO_SYNC=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR $CODE_DIR

# The bind-mounted repo is owned by another user, which git (and so DVC)
# refuses to use unless it is marked as safe.
RUN git config --global --add safe.directory $CODE_DIR

# Dependencies first (cached unless pyproject.toml or uv.lock change).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project $UV_SYNC_ARGS

# Source, then the project itself.
COPY . $CODE_DIR
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen $UV_SYNC_ARGS
