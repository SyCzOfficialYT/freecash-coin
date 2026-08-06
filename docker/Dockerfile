FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stratum/ ./stratum/
COPY monitor/ ./monitor/
COPY config/ ./config/

RUN mkdir -p data logs

EXPOSE 3333 5000

CMD ["python3", "stratum/server.py"]
