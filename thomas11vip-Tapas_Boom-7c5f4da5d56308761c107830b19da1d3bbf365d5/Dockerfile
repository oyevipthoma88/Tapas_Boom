# Tapas Boom — India-egress deploy image (Fly.io bom region).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (curl for healthcheck / self-ping).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Long-polling bot — no inbound port needed. Fly still needs an
# internal_port for [http_service] if enabled; we skip http_service.
CMD ["python", "bot.py"]
