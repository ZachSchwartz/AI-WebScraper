# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

RUN useradd --create-home --no-log-init app

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY web_service/requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY util/ /app/util/
COPY web_service/src/ /app/src/

ENV PYTHONPATH=/app:/app/src
EXPOSE 5000

USER app

# The timeout outlasts three PIPELINE_TIMEOUT service calls, since this request
# is held open for all of them; see Known Limitations in the README.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", \
     "--timeout", "600", "--access-logfile", "-", "app:app"]
