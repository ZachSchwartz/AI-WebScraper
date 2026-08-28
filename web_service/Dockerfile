# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY web_service/requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY util/ /app/util/
COPY web_service/src/ /app/src/

ENV PYTHONPATH=/app
EXPOSE 5000

CMD ["python", "src/app.py"]
