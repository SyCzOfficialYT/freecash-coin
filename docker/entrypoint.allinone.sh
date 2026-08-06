#!/bin/bash
set -e

DATADIR="${FCH_DATADIR:-/opt/newcoin}"
RPCUSER="${FCH_RPCUSER:-fchrpc}"
RPCPASS="${FCH_RPCPASS:-FreecashSoloAutoRpc_ChangeMeIfPublic}"
RPCPORT="${FCH_RPCPORT:-8332}"
P2PPORT="${FCH_P2PPORT:-8333}"

mkdir -p "$DATADIR" /app/data /app/logs /app/config

echo "[allinone] FreeCash Solo – Node + Stratum + Dashboard"

# Node-Config (RPC nur lokal im Container-Netz / host)
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

# App-Config für Stratum/Dashboard (gleiche RPC-Daten)
if [ ! -f /app/config/config.yaml ]; then
  cat > /app/config/config.yaml << EOF
rpc:
  host: "127.0.0.1"
  port: ${RPCPORT}
  user: "${RPCUSER}"
  password: "${RPCPASS}"
  timeout: 30
pool:
  payout_address: "FCHANGE_ME_GETNEWADDRESS"
  stratum_port: 3333
  stratum_host: "0.0.0.0"
  start_difficulty: 256
  job_interval: 25
  payout_threshold: 10.0
monitor:
  host: "0.0.0.0"
  port: 5000
logging:
  level: "INFO"
EOF
else
  # RPC-Passwort in bestehender config angleichen
  python3 - <<'PY'
import yaml
from pathlib import Path
p = Path("/app/config/config.yaml")
cfg = yaml.safe_load(p.read_text()) if p.exists() else {}
cfg.setdefault("rpc", {})
cfg["rpc"]["host"] = "127.0.0.1"
cfg["rpc"]["port"] = int(__import__("os").environ.get("FCH_RPCPORT", "8332"))
cfg["rpc"]["user"] = __import__("os").environ.get("FCH_RPCUSER", "fchrpc")
cfg["rpc"]["password"] = __import__("os").environ.get("FCH_RPCPASS", "FreecashSoloAutoRpc_ChangeMeIfPublic")
p.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))
print("[allinone] config.yaml RPC sync")
PY
fi

echo "[allinone] Starte freecashd (datadir=$DATADIR)…"
freecashd -datadir="$DATADIR" -conf="$DATADIR/freecash.conf" &
NODE_PID=$!

echo "[allinone] Warte auf RPC…"
for i in $(seq 1 120); do
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

# Wallet + Holding-Adresse
export PATH="/usr/local/bin:$PATH"
# setup_address nutzt freecash-cli im PATH und config.yaml
cd /app
# CLI braucht -datadir für getnewaddress – Wrapper
cat > /usr/local/bin/freecash-cli-wrap << WEOF
#!/bin/bash
exec /usr/local/bin/freecash-cli -datadir="$DATADIR" -rpcuser="$RPCUSER" -rpcpassword="$RPCPASS" "\$@"
WEOF
chmod +x /usr/local/bin/freecash-cli-wrap
# temporär freecash-cli überschatten
mv /usr/local/bin/freecash-cli /usr/local/bin/freecash-cli.real
ln -sf /usr/local/bin/freecash-cli-wrap /usr/local/bin/freecash-cli

python3 scripts/setup_address.py || echo "[allinone] WARN: Adresse später setzen wenn Wallet ready"

touch /app/data/events.jsonl /app/data/stratum.log

echo "[allinone] Starte Stratum…"
python3 stratum/server.py >> /app/data/stratum.log 2>&1 &
STRATUM_PID=$!
sleep 1
echo "[allinone] Starte Dashboard…"
python3 monitor/app.py &
MONITOR_PID=$!

ADDR=$(python3 -c "import yaml; print(yaml.safe_load(open('/app/config/config.yaml'))['pool']['payout_address'])" 2>/dev/null || echo "?")
echo "[allinone] ========================================"
echo "[allinone] Dashboard  http://HOST:5000"
echo "[allinone] Stratum    stratum+tcp://HOST:3333"
echo "[allinone] Holding    $ADDR"
echo "[allinone] Username   ${ADDR}.nerdq1"
echo "[allinone] (Sync kann Stunden dauern – Shares erst nach Sync sinnvoll)"
echo "[allinone] ========================================"

trap "kill $NODE_PID $STRATUM_PID $MONITOR_PID 2>/dev/null" EXIT
wait -n $NODE_PID $STRATUM_PID $MONITOR_PID || true
kill $NODE_PID $STRATUM_PID $MONITOR_PID 2>/dev/null || true
