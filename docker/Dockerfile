FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stratum/ ./stratum/
COPY monitor/ ./monitor/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh scripts/*.sh scripts/*.py 2>/dev/null || true \
 && mkdir -p data logs

EXPOSE 3333 5000

ENTRYPOINT ["/entrypoint.sh"]
