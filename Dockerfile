# syntax=docker/dockerfile:1
FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

WORKDIR /app

# ---- 依赖层：单独缓存，业务代码变更不触发重装依赖 ----
FROM base AS deps
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root --only main

# ---- 运行层 ----
FROM base AS runtime
COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY src ./src
COPY configs ./configs
COPY pyproject.toml ./

RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

# 通过 ENTRYPOINT_MODE 区分进程角色：api | job_worker | vector_worker | reconciliation_worker
ENV ENTRYPOINT_MODE=api
EXPOSE 8000

ENTRYPOINT ["python", "-m", "label_agent.main"]
CMD ["--mode", "api"]
