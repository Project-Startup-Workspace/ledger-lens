# API and AuditPulse A2A service (same image, different command). Build from the repo root:
#   docker build -f infra/docker/api.Dockerfile -t ledger-lens-api .
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    LL_REPO_ROOT=/app \
    LL_DATA_DIR=/app/.data \
    PATH=/app/agents/.venv/bin:$PATH \
    PORT=8080

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY agents/pyproject.toml agents/uv.lock agents/README.md agents/
RUN cd agents && uv sync --locked --no-dev --extra gcp --extra agents --no-install-project

COPY agents/ledger_lens agents/ledger_lens
COPY rule-packs rule-packs
COPY ml/artifacts ml/artifacts
COPY demo-data demo-data
RUN cd agents && uv sync --locked --no-dev --extra gcp --extra agents \
    && useradd --uid 10001 --no-create-home app \
    && mkdir -p .data && chown app .data

USER app
EXPOSE 8080
CMD ["sh", "-c", "uvicorn ledger_lens.api.app:app --host 0.0.0.0 --port ${PORT}"]
