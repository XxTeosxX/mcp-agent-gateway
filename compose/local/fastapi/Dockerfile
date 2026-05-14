FROM ghcr.io/astral-sh/uv:python3.13-trixie

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ARG APP_HOME=/app
WORKDIR ${APP_HOME}

# Install project dependencies (cached across rebuilds)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-install-project

COPY ./compose/local/fastapi/start /start
RUN sed -i 's/\r$//g' /start && chmod +x /start

ENV PATH="/opt/venv/bin:$PATH"
