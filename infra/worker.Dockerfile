# Spec 0012/0002: the extraction worker image. Built from the repository root.
# The parse child runs inside this container, so the container is the isolation
# boundary (non root user, read only root, no capabilities, internal network).
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend/src PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/src backend/src
COPY backend/alembic backend/alembic

# Mount point only. Compose bind mounts the host document directory here, read only.
RUN mkdir -p /var/lib/energyiq/documents \
    && chown -R 10001:10001 /var/lib/energyiq

USER 10001:10001
CMD ["python", "-m", "energyiq.worker"]
