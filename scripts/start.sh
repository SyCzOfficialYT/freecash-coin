#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "=== FreeCash (FCH) Solo Starter ==="

if [ ! -f config/config.yaml ]; then
  echo "Fehlt config/config.yaml"
  exit 1
fi

if grep -q "FCHANGE_ME" config/config.yaml 2>/dev/null; then
  echo "WARNUNG: payout_address noch Platzhalter – bitte F… Adresse setzen!"
fi

mkdir -p data logs

if command -v freecash-cli >/dev/null 2>&1; then
  if ! freecash-cli getblockchaininfo >/dev/null 2>&1; then
    echo "WARNUNG: freecashd RPC nicht erreichbar. freecashd -daemon ?"
  fi
else
  echo "Hinweis: freecash-cli nicht im PATH – Node separat starten."
fi

echo "Starte Stratum..."
python3 stratum/server.py &
STRATUM_PID=$!
sleep 1
echo "Starte Dashboard..."
python3 monitor/app.py &
MONITOR_PID=$!

echo ""
echo "  Stratum   → :3333"
echo "  Dashboard → http://0.0.0.0:5000"
echo "  NerdQaxe  → stratum+tcp://DEINE_IP:3333"
echo "  Username  → FDeineAdresse.nerdq1"
echo ""
echo "Ctrl+C zum Beenden"
trap "kill $STRATUM_PID $MONITOR_PID 2>/dev/null" EXIT
wait
