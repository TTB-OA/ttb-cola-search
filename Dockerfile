# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 - build the Vite React SPA
# ---------------------------------------------------------------------------
FROM node:20-slim AS spa
WORKDIR /spa

# Install dependencies first (cached until the lockfile/manifest changes).
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install

# Build the production bundle into /spa/dist.
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 - Python API image (serves the API and the built SPA)
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# uv for fast, reproducible dependency installs (matches local workflow).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    SPA_DIR=/app/frontend/dist

WORKDIR /app

# Install only production dependencies against the committed lockfile.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Application code.
COPY src/ ./src/
COPY run.py ./

# Built SPA from stage 1 (served single-origin by FastAPI at "/").
COPY --from=spa /spa/dist ./frontend/dist

ENV PATH="/app/.venv/bin:$PATH"

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# On Linux the default asyncio/uvloop loop is compatible with psycopg's async
# driver, so no custom event-loop policy is needed here (that is Windows-only).
CMD ["sh", "-c", "uvicorn api.main:app --app-dir src --host 0.0.0.0 --port ${PORT}"]
