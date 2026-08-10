#!/bin/bash
set -e

DATADIR="${FCH_DATADIR:-/opt/newcoin}"
RPCUSER="${FCH_RPCUSER:-fchrpc}"
RPCPASS="${FCH_RPCPASS:-FreecashSoloAutoRpc_ChangeMeIfPublic}"
RPCPORT="${FCH_RPCPORT:-8332}"
P2PPORT="${FCH_P2PPORT:-8333}"
DASH_PORT="${FCH_DASH_PORT:-5050}"

mkdir -p "$DATADIR" /app/data /app/logs /app/config

echo "[allinone] FreeCash Solo – Node + Stratum + Dashboard"

cat > "$DATADIR/freecash.conf" << EOF
server=1
daemon=0
listen=1
port=${P2PPORT}
rpcport=${RPCPORT}
rpcuser=${RPCUSER}
rpcpassword=${RPCPASS}
rpcallowip=127.0.0.1
rpcallowip=0.0.0.0/0
txindex=1
printtoconsole=1
EOF

# Config immer mit Port 5050 schreiben/aktualisieren
python3 - <<PY
import yaml, os
from pathlib import Path
p = Path("/app/config/config.yaml")
cfg = yaml.safe_load(p.read_text()) if p.exists() else {}
if not isinstance(cfg, dict):
    cfg = {}
cfg.setdefault("rpc", {})
cfg["rpc"]["host"] = "127.0.0.1"
cfg["rpc"]["port"] = int(os.environ.get("FCH_RPCPORT", "8332"))
cfg["rpc"]["user"] = os.environ.get("FCH_RPCUSER", "fchrpc")
cfg["rpc"]["password"] = os.environ.get("FCH_RPCPASS", "FreecashSoloAutoRpc_ChangeMeIfPublic")
cfg["rpc"].setdefault("timeout", 30)
cfg.setdefault("pool", {})
cfg["pool"].setdefault("payout_address", "FCHANGE_ME_GETNEWADDRESS")
cfg["pool"].setdefault("stratum_port", 3333)
cfg["pool"].setdefault("stratum_host", "0.0.0.0")
cfg["pool"].setdefault("start_difficulty", 256)
cfg["pool"].setdefault("job_interval", 30)
cfg.setdefault("monitor", {})
cfg["monitor"]["host"] = "0.0.0.0"
cfg["monitor"]["port"] = int(os.environ.get("FCH_DASH_PORT", "5050"))
cfg.setdefault("logging", {"level": "INFO"})
p.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))
print("[allinone] config.yaml OK – dashboard port", cfg["monitor"]["port"])
PY

echo "[allinone] Starte freecashd (datadir=$DATADIR)…"
freecashd -datadir="$DATADIR" -conf="$DATADIR/freecash.conf" &
NODE_PID=$!

echo "[allinone] Warte auf RPC…"
for i in $(seq 1 180); do
  if freecash-cli -datadir="$DATADIR" -rpcuser="$RPCUSER" -rpcpassword="$RPCPASS" getblockchaininfo >/dev/null 2>&1; then
    echo "[allinone] RPC ok nach ${i}s"
    break
  fi
  if ! kill -0 $NODE_PID 2>/dev/null; then
    echo "[allinone] freecashd beendet unerwartet"
    wait $NODE_PID || true
    exit 1
  fi
  sleep 1
done

export PATH="/usr/local/bin:$PATH"
cd /app
cat > /usr/local/bin/freecash-cli-wrap << WEOF
#!/bin/bash
exec /usr/local/bin/freecash-cli.real -datadir="$DATADIR" -rpcuser="$RPCUSER" -rpcpassword="$RPCPASS" "\$@"
WEOF
chmod +x /usr/local/bin/freecash-cli-wrap
if [ ! -f /usr/local/bin/freecash-cli.real ]; then
  if [ -f /usr/local/bin/freecash-cli ]; then
    mv /usr/local/bin/freecash-cli /usr/local/bin/freecash-cli.real
  fi
fi
ln -sf /usr/local/bin/freecash-cli-wrap /usr/local/bin/freecash-cli

python3 scripts/setup_address.py || echo "[allinone] WARN: Adresse später setzen wenn Wallet ready"

touch /app/data/events.jsonl /app/data/stratum.log

start_stratum() {
  echo "[allinone] Starte Stratum :3333…"
  python3 /app/stratum/server.py >> /app/data/stratum.log 2>&1 &
  STRATUM_PID=$!
}

start_dashboard() {
  echo "[allinone] Starte Dashboard :${DASH_PORT}…"
  python3 /app/monitor/app.py >> /app/data/dashboard.log 2>&1 &
  MONITOR_PID=$!
  sleep 2
  if kill -0 $MONITOR_PID 2>/dev/null; then
    echo "[allinone] Dashboard PID $MONITOR_PID lauscht auf ${DASH_PORT}"
  else
    echo "[allinone] WARN: Dashboard start fehlgeschlagen – siehe /app/data/dashboard.log"
    cat /app/data/dashboard.log 2>/dev/null | tail -20 || true
  fi
}

start_stratum
start_dashboard

# Watchdog: wenn Stratum/Dashboard stirbt, neu starten (Node bleibt)
(
  while true; do
    sleep 15
    if ! kill -0 ${STRATUM_PID:-0} 2>/dev/null; then
      echo "[allinone] Stratum tot – restart"
      start_stratum
    fi
    if ! kill -0 ${MONITOR_PID:-0} 2>/dev/null; then
      echo "[allinone] Dashboard tot – restart auf :${DASH_PORT}"
      start_dashboard
    fi
  done
) &
WATCH_PID=$!

ADDR=$(python3 -c "import yaml; print(yaml.safe_load(open('/app/config/config.yaml')).get('pool',{}).get('payout_address','?'))" 2>/dev/null || echo "?")
echo "[allinone] ========================================"
echo "[allinone] Dashboard  http://0.0.0.0:${DASH_PORT}"
echo "[allinone] Stratum    stratum+tcp://0.0.0.0:3333"
echo "[allinone] Holding    $ADDR"
echo "[allinone] Username   ${ADDR}.nerdq1"
echo "[allinone] Maturity   144 blocks (~2.4h bei 1min/Block)"
echo "[allinone] ========================================"

trap "kill $NODE_PID $STRATUM_PID $MONITOR_PID $WATCH_PID 2>/dev/null" EXIT
wait $NODE_PID
