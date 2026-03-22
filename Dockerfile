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
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

LABEL maintainer="WikiJM"
LABEL description="Immo-Boussole – Collaborative real estate catalogue"

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

USER boussole

# ── Volumes ───────────────────────────────────────────────────────────────────
# /app/data      → SQLite database (persistent)
# /app/static    → Downloaded media files (persistent)
VOLUME ["/app/data", "/app/static"]

# ── Environment defaults ──────────────────────────────────────────────────────
ENV DATABASE_URL="sqlite:////app/data/immo_boussole.db" \
    FLARESOLVERR_URL="http://flaresolverr:8191" \
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
