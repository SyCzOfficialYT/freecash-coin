#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "=== Solo Node Starter (freecash-coin / fch-node stack) ==="

if [ ! -f config/config.yaml ]; then
  echo "Fehlt: config/config.yaml"
  echo "  cp config/config.example.yaml config/config.yaml"
  echo "  und RPC-Passwort + payout_address setzen"
  exit 1
fi

mkdir -p data logs

if ! command -v bitcoincashII-cli >/dev/null 2>&1; then
  echo "WARNUNG: bitcoincashII-cli nicht im PATH – Node muss separat laufen."
elif ! bitcoincashII-cli getblockchaininfo >/dev/null 2>&1; then
  echo "WARNUNG: RPC nicht erreichbar. Node starten: bitcoincashIId -daemon"
fi

echo "Starte Stratum..."
python3 stratum/server.py &
STRATUM_PID=$!

sleep 1
echo "Starte Dashboard..."
python3 monitor/app.py &
MONITOR_PID=$!

echo ""
echo "  Stratum   PID $STRATUM_PID  → Port 3333"
echo "  Dashboard PID $MONITOR_PID  → http://0.0.0.0:5000"
echo ""
echo "NerdQaxe: stratum+tcp://DEINE_IP:3333"
echo "Ctrl+C zum Beenden"

trap "kill $STRATUM_PID $MONITOR_PID 2>/dev/null" EXIT
wait
