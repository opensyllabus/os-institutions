# syntax=docker/dockerfile:1
FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

ARG CODE_DIR=/opt/os-institutions
# Extra `uv sync` flags, e.g. UV_SYNC_ARGS="--group dvc" for pipeline runs.
ARG UV_SYNC_ARGS=""

# git: DVC needs it, and uv fetches os-normalizer with it.
# openssh-client: only while os-normalizer is private; drop it, the ssh mount
# below and the known_hosts line once it is public.
RUN apt-get update && apt-get install -y --no-install-recommends \
  git \
  openssh-client \
  && rm -rf /var/lib/apt/lists/* \
  && mkdir -p -m 700 /root/.ssh \
  && ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null

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

# Dependencies first (cached unless pyproject.toml or uv.lock change). The ssh
# mount needs `docker build --ssh default[=KEYFILE]`; the URL rewrite applies to
# this RUN only, so uv.lock keeps the https URL.
COPY pyproject.toml uv.lock ./
RUN --mount=type=ssh \
    --mount=type=cache,target=/root/.cache/uv \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=url.git@github.com:.insteadOf \
    GIT_CONFIG_VALUE_0=https://github.com/ \
    uv sync --frozen --no-install-project $UV_SYNC_ARGS

# Source, then the project itself.
COPY . $CODE_DIR
RUN --mount=type=ssh \
    --mount=type=cache,target=/root/.cache/uv \
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0=url.git@github.com:.insteadOf \
    GIT_CONFIG_VALUE_0=https://github.com/ \
    uv sync --frozen $UV_SYNC_ARGS
