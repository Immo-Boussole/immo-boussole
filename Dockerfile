# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a separate layer for caching
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt \
    && python -c "import urllib.request, tarfile; urllib.request.urlretrieve('https://nodejs.org/dist/v24.14.1/node-v24.14.1-linux-x64.tar.xz', 'node.tar.xz'); tar = tarfile.open('node.tar.xz'); tar.extractall(); tar.close();" \
    && find /install -path "*/playwright/driver/node" -exec cp node-v24.14.1-linux-x64/bin/node {} \; \
    && rm -rf node.tar.xz node-v24.14.1-linux-x64


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Upgrade system packages to patch vulnerabilities (e.g., openssl)
RUN apt-get update && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

LABEL maintainer="WikiJM"
LABEL description="Immo-Boussole – Collaborative real estate catalogue"
ARG APP_VERSION="1.1.1-dev"
LABEL version="${APP_VERSION}"
LABEL org.opencontainers.image.version="${APP_VERSION}"

ENV APP_VERSION="${APP_VERSION}"

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create non-root user for security
RUN useradd -m -u 1000 boussole \
    && mkdir -p /app/static/media /app/data \
    && chown -R boussole:boussole /app

# Copy application source
COPY --chown=boussole:boussole app/ ./app/
COPY --chown=boussole:boussole templates/ ./templates/
COPY --chown=boussole:boussole locales/ ./locales/
COPY --chown=boussole:boussole static/ ./static/

USER boussole

# ── Volumes ───────────────────────────────────────────────────────────────────
# /app/data      → SQLite database (persistent)
# /app/static/media → Downloaded media files (persistent)
VOLUME ["/app/data", "/app/static/media"]

# ── Environment defaults ──────────────────────────────────────────────────────
ENV DATABASE_URL="sqlite:////app/data/immo_boussole.db" \
    BROWSERLESS_URL="ws://browserless:3000" \
    SCRAPING_INTERVAL_HOURS=12 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# ── Start ─────────────────────────────────────────────────────────────────────
CMD ["python", "-m", "uvicorn", "app.main:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "1"]
