# ---- Builder ----
FROM ghcr.io/astral-sh/uv:python3.13-trixie AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

ARG APP_HOME=/app
WORKDIR ${APP_HOME}

# Install deps only (no dev)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-install-project --no-dev

# Copy source and sync project
COPY . ${APP_HOME}
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-dev

# ---- Runtime ----
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

ARG APP_HOME=/app
WORKDIR ${APP_HOME}

# Non-root user
RUN addgroup --system fastapi \
    && adduser --system --ingroup fastapi fastapi

COPY --from=builder --chown=fastapi:fastapi ${APP_HOME} ${APP_HOME}

COPY --chown=fastapi:fastapi ./compose/production/fastapi/start /start
RUN sed -i 's/\r$//g' /start && chmod +x /start

USER fastapi
