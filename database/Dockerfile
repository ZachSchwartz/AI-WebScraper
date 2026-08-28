# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

RUN useradd --create-home --no-log-init app

# curl is needed by the healthcheck; every Python dependency ships a wheel,
# so no compiler toolchain is required.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY database/requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# The service and the shared utilities it imports, so the image runs on its own
# rather than depending on a bind mount from docker-compose.
COPY util/ /app/util/
COPY database/src/ /app/src/

ENV PYTHONPATH=/app:/app/src

USER app

CMD ["sh", "-c", "python -c 'from db_processor import ensure_schema; ensure_schema()' && \
     exec gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 300 \
     --access-logfile - db_main:app"]
