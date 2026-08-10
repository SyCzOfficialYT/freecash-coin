#!/bin/bash
# FreeCash Solo – freecashd + stratum + dashboard (5050) mit Auto-Restart
set -u

DATADIR="${FCH_DATADIR:-/opt/newcoin}"
RPCUSER="${FCH_RPCUSER:-fchrpc}"
RPCPASS="${FCH_RPCPASS:-FreecashSoloAutoRpc_ChangeMeIfPublic}"
RPCPORT="${FCH_RPCPORT:-8332}"
P2PPORT="${FCH_P2PPORT:-8333}"
DASH_PORT="${FCH_DASH_PORT:-5050}"

mkdir -p "$DATADIR" /app/data /app/logs /app/config
cd /app

echo "[allinone] FreeCash Solo boot"

# --- freecash.conf ---
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

# --- config.yaml always port 5050 ---
python3 - <<'PY' || true
import yaml, os
from pathlib import Path
p = Path("/app/config/config.yaml")
cfg = {}
if p.exists():
    try:
        cfg = yaml.safe_load(p.read_text()) or {}
    except Exception:
        cfg = {}
cfg.setdefault("rpc", {})
cfg["rpc"].update({
    "host": "127.0.0.1",
    "port": int(os.environ.get("FCH_RPCPORT", "8332")),
    "user": os.environ.get("FCH_RPCUSER", "fchrpc"),
    "password": os.environ.get("FCH_RPCPASS", "FreecashSoloAutoRpc_ChangeMeIfPublic"),
    "timeout": 30,
})
cfg.setdefault("pool", {})
cfg["pool"].setdefault("payout_address", "FCHANGE_ME_GETNEWADDRESS")
cfg["pool"].setdefault("stratum_port", 3333)
cfg["pool"].setdefault("stratum_host", "0.0.0.0")
cfg["pool"].setdefault("start_difficulty", 256)
cfg["pool"].setdefault("job_interval", 30)
cfg["monitor"] = {"host": "0.0.0.0", "port": int(os.environ.get("FCH_DASH_PORT", "5050"))}
cfg.setdefault("logging", {"level": "INFO"})
p.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))
print("[allinone] monitor port", cfg["monitor"]["port"])
PY

# --- CLI wrapper ---
if [ -x /usr/local/bin/freecash-cli ] && [ ! -f /usr/local/bin/freecash-cli.real ]; then
  mv /usr/local/bin/freecash-cli /usr/local/bin/freecash-cli.real
fi
cat > /usr/local/bin/freecash-cli << EOF
#!/bin/bash
exec /usr/local/bin/freecash-cli.real -datadir="$DATADIR" -rpcuser="$RPCUSER" -rpcpassword="$RPCPASS" "\$@"
EOF
chmod +x /usr/local/bin/freecash-cli
export PATH="/usr/local/bin:$PATH"

echo "[allinone] start freecashd"
freecashd -datadir="$DATADIR" -conf="$DATADIR/freecash.conf" &
NODE_PID=$!

for i in $(seq 1 180); do
  if freecash-cli getblockchaininfo >/dev/null 2>&1; then
    echo "[allinone] RPC ok (${i}s)"
    break
  fi
  if ! kill -0 $NODE_PID 2>/dev/null; then
    echo "[allinone] freecashd died"
    exit 1
  fi
  sleep 1
done

python3 scripts/setup_address.py 2>/dev/null || echo "[allinone] address setup skip/later"
touch /app/data/events.jsonl /app/data/stratum.log /app/data/dashboard.log

# --- supervisor loop: keeps stratum + dashboard alive forever ---
run_forever() {
  local name="$1"
  local logfile="$2"
  shift 2
  while true; do
    echo "[allinone] start $name: $*"
    "$@" >>"$logfile" 2>&1 &
    local pid=$!
    echo $pid >"/tmp/${name}.pid"
    wait $pid
    local rc=$?
    echo "[allinone] $name exited rc=$rc – restart in 3s"
    sleep 3
  done
}

run_forever stratum /app/data/stratum.log python3 /app/stratum/server.py &
run_forever dashboard /app/data/dashboard.log python3 /app/monitor/app.py &

sleep 3
ADDR=$(python3 -c "import yaml;print(yaml.safe_load(open('/app/config/config.yaml')).get('pool',{}).get('payout_address','?'))" 2>/dev/null || echo "?")
echo "[allinone] ========================================"
echo "[allinone] Dashboard  http://0.0.0.0:${DASH_PORT}"
echo "[allinone] Stratum    :3333"
echo "[allinone] Holding    $ADDR"
echo "[allinone] ========================================"

# Block on node – if node dies, container exits (restart policy brings it back)
wait $NODE_PID
echo "[allinone] freecashd exited – container stop"
exit 1
