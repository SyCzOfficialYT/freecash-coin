#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "=== FreeCash (FCH) Solo Starter ==="

if [ ! -f config/config.yaml ]; then
  echo "Fehlt config/config.yaml"
  exit 1
fi

mkdir -p data logs

# Node erreichbar?
if command -v freecash-cli >/dev/null 2>&1; then
  if ! freecash-cli getblockchaininfo >/dev/null 2>&1; then
    echo "WARNUNG: freecashd RPC nicht erreichbar. Starte ggf.: freecashd -daemon"
  fi
else
  echo "Hinweis: freecash-cli nicht im PATH – Adresse wird über RPC versucht."
fi

# Holding-Adresse automatisch erzeugen + in config schreiben + prüfen
echo "Prüfe / erzeuge Holding-Adresse…"
python3 scripts/setup_address.py || {
  echo "Adress-Setup fehlgeschlagen – Stratum startet trotzdem (Jobs brauchen gültige Adresse)."
}

ADDR=$(python3 -c "import yaml; print(yaml.safe_load(open('config/config.yaml'))['pool']['payout_address'])" 2>/dev/null || echo "?")

echo "Starte Stratum…"
python3 stratum/server.py &
STRATUM_PID=$!
sleep 1
echo "Starte Dashboard…"
python3 monitor/app.py &
MONITOR_PID=$!

echo ""
echo "  Stratum      → :3333"
echo "  Dashboard    → http://0.0.0.0:5000"
echo "  Holding-Addr → $ADDR"
echo "  NerdQaxe     → stratum+tcp://DEINE_IP:3333"
echo "  Username     → ${ADDR}.nerdq1"
echo ""
echo "Ctrl+C zum Beenden"
trap "kill $STRATUM_PID $MONITOR_PID 2>/dev/null" EXIT
wait
