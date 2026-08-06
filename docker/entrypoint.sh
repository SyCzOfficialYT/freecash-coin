#!/bin/bash
set -e
cd /app
mkdir -p data logs config

echo "[entrypoint] FreeCash Solo – auto setup"

# Config aus Example, falls Volume leer
if [ ! -f config/config.yaml ]; then
  if [ -f config/config.example.yaml ]; then
    cp config/config.example.yaml config/config.yaml
    echo "[entrypoint] config.yaml aus example erzeugt"
  fi
fi

# Holding-Adresse automatisch
python3 scripts/setup_address.py || echo "[entrypoint] WARN: Adress-Setup fehlgeschlagen (Node offline?)"

# Logs leeren/rotieren sanft
touch data/events.jsonl data/stratum.log

echo "[entrypoint] Starte Stratum + Dashboard"
python3 stratum/server.py >> data/stratum.log 2>&1 &
STRATUM_PID=$!
sleep 1
python3 monitor/app.py &
MONITOR_PID=$!

echo "[entrypoint] Stratum PID=$STRATUM_PID  Monitor PID=$MONITOR_PID"
echo "[entrypoint] Dashboard http://0.0.0.0:5000  Stratum :3333"

trap "kill $STRATUM_PID $MONITOR_PID 2>/dev/null" EXIT
wait -n $STRATUM_PID $MONITOR_PID || true
kill $STRATUM_PID $MONITOR_PID 2>/dev/null || true
