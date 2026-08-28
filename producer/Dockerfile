# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# curl is needed by the healthcheck; every Python dependency ships a wheel,
# so no compiler toolchain is required.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY producer/requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy queue_util.py from root directory
COPY util/queue_util.py /app/
COPY util/error_util.py /app/
COPY util/url_util.py /app/

# Set Python path to include app directory
ENV PYTHONPATH=/app

# Note: Source code will be mounted as a volume in docker-compose.yml
# CMD is set in docker-compose or when running the container
