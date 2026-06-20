# ───────────────────────────────────────────────────────────
# Tender Monitoring Agent — Multi-stage Dockerfile
# ───────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright browser dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libwayland-client0 \

    # Utilities
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install Python Dependencies ──────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Install Playwright Chromium ──────────────────────────────
RUN playwright install chromium

# ── Copy Application Code ───────────────────────────────────
COPY . /app

# ── Create directories ──────────────────────────────────────
RUN mkdir -p /app/downloads /app/logs

# ── Health Check ─────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Expose Dashboard Port ───────────────────────────────────
EXPOSE 8000

# ── Entry Point ──────────────────────────────────────────────
CMD ["python", "main.py"]
