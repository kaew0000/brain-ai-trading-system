# ══════════════════════════════════════════════════════
#  Brain Bot V13 — Production Dockerfile
# ══════════════════════════════════════════════════════
FROM python:3.11-slim

LABEL maintainer="Brain Bot V13"
LABEL description="AI Trading Command Center"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc g++ libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create non-root user
RUN useradd -m -u 1000 botuser \
    && chown -R botuser:botuser /app
USER botuser

# Expose dashboard port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["python", "main.py"]
