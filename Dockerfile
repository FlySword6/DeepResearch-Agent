# =============================================================================
# Stage 1: Python dependencies
# =============================================================================
FROM python:3.11-slim AS python-deps

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 2: Frontend build (React + Vite)
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# Install dependencies (separate copy for layer caching)
COPY app/web/package.json app/web/package-lock.json* ./
RUN npm ci

# Copy source and build
COPY app/web/ .
RUN npm run build

# =============================================================================
# Stage 3: Runtime
# =============================================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy Python packages from python-deps
COPY --from=python-deps /usr/local /usr/local

# Copy built React frontend
COPY --from=frontend-builder /app/dist /app/app/web/dist

# Install runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy application code (data/ is excluded by .dockerignore, created at runtime)
COPY app/ app/

# Create data directories
RUN mkdir -p data/reports data/knowledge data/chroma_db data/uploads && \
    adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app/data

# Switch to non-root user
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
