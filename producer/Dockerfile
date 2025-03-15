FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt /app/requirements.txt
RUN pip install -v redis==5.0.1 && \
    pip install --no-cache-dir -r requirements.txt && \
    pip list | grep redis

# Copy the source code
COPY src/ /app/src/

# Set Python path
ENV PYTHONPATH=/app

# Print installed packages for debugging
RUN python -c "import pkg_resources; print('Installed packages:'); [print(i.key, i.version) for i in pkg_resources.working_set]"

# Default command (can be overridden)
CMD ["python", "src/main.py"]