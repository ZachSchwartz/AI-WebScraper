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
COPY scorer/requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY util/ /app/util/
COPY scorer/src/ /app/src/

ENV PYTHONPATH=/app:/app/src

ENV MODEL_CACHE_DIR=/app/model_cache
RUN mkdir -p /app/model_cache && chown app:app /app/model_cache

USER app

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", \
     "--timeout", "600", "--access-logfile", "-", "scorer_main:app"]
