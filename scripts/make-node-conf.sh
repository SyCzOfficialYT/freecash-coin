#!/bin/bash
# Schreibt bitcoincashII.conf mit dem gleichen RPC-Passwort wie config.yaml
set -e
CONF_DIR="${HOME}/.bitcoincashII"
CONF="${CONF_DIR}/bitcoincashII.conf"
PASS="AcX3p5J_Xk4j-NX4wdSji489z9RQgVzy"

mkdir -p "$CONF_DIR"
if [ -f "$CONF" ]; then
  echo "Existiert bereits: $CONF"
  echo "Bitte rpcpassword manuell auf denselben Wert setzen wie in config/config.yaml"
  exit 0
fi

cat > "$CONF" << EOF
server=1
daemon=1
listen=1
port=8339
rpcport=8342
rpcuser=bch2rpc
rpcpassword=${PASS}
rpcallowip=127.0.0.1
txindex=1
EOF

echo "Geschrieben: $CONF"
echo "Starte Node mit: bitcoincashIId -daemon"
