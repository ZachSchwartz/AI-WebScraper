FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY producer/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy queue_util.py from root directory
COPY util/queue_util.py /app/
COPY util/error_util.py /app/

# Set Python path to include app directory
ENV PYTHONPATH=/app

# Note: Source code will be mounted as a volume in docker-compose.yml
# CMD is set in docker-compose or when running the container