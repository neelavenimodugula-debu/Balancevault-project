FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy configuration and project files
COPY pyproject.toml .
COPY README.md .
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY src/ ./src/

# Install python package and dependencies
RUN pip install --no-cache-dir .

# Create non-privileged user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD ["sh", "-c", "python -m uvicorn ledgerline.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

