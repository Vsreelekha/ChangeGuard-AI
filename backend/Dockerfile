# Build from the repository root:
# docker build -f backend/Dockerfile -t changeguard-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend:/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Keep the shared core modules in their canonical locations. Do not fork their implementations.
COPY backend/app /app/backend/app
COPY code_analyzer /app/code_analyzer
COPY test_selector /app/test_selector
COPY reports /app/reports
COPY backend/migrations /app/backend/migrations

RUN python -c "import code_analyzer.impact_analyzer, test_selector.test_mapper, test_selector.selector, reports.risk_scorer, reports.report_generator; import app.main"

WORKDIR /app/backend

RUN useradd -m -u 1000 changeguard && chown -R changeguard:changeguard /app
USER changeguard

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
