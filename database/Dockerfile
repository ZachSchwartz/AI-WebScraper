FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY database/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy queue_manager.py from root directory
COPY queue_manager.py /app/

# Set Python path to include app directory
ENV PYTHONPATH=/app

# Note: Source code will be mounted as a volume in docker-compose.yml
# CMD is set in docker-compose or when running the container 