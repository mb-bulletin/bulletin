# Single Dockerfile shared by api and harness containers.
# Different services, same code — they just have different entrypoints
# and are wired up differently in docker-compose.
#
# Multi-stage build keeps the runtime image small (no compilers, no
# build deps). Python 3.12-slim is the base; we install pdftotext via
# poppler-utils because that's our fallback when pdfplumber chokes.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime dependencies:
# - poppler-utils provides pdftotext for the PDF extraction fallback
# - tzdata so /etc/localtime resolves (zoneinfo lookups are common)
# - ca-certificates for HTTPS to api.anthropic.com and parish CDNs
# - curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        tzdata \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in their own layer so code changes don't bust
# the dependency cache.
COPY requirements.txt .
RUN pip install -r requirements.txt

# App code. The .dockerignore at the root excludes node_modules, dist,
# the local SQLite DB, etc., so we don't ship junk.
COPY bulletin_parser/ ./bulletin_parser/

# Non-root user — running as root inside a container is a smell even
# when nothing's exposed to the public.
RUN useradd -u 10001 -m -s /usr/sbin/nologin bulletin
USER bulletin

# Default to running the API. The harness compose service overrides
# this with its own command.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["python", "-m", "uvicorn", "bulletin_parser.api.asgi:app", \
     "--host", "0.0.0.0", "--port", "8000"]
