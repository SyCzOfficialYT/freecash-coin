#!/bin/bash
# Schreibt ~/.freecash/freecash.conf mit gleichem RPC-Passwort wie config.yaml
set -e
CONF_DIR="${HOME}/.freecash"
CONF="${CONF_DIR}/freecash.conf"
PASS="CTSTnIiXEv9blO04eRKv8je8EUiMyL9M"

mkdir -p "$CONF_DIR"
if [ -f "$CONF" ]; then
  echo "Existiert bereits: $CONF"
  echo "rpcpassword muss identisch zu config/config.yaml sein:"
  echo "  $PASS"
  exit 0
fi

cat > "$CONF" << EOF
server=1
daemon=1
listen=1
port=8333
rpcport=8332
rpcuser=fchrpc
rpcpassword=${PASS}
rpcallowip=127.0.0.1
txindex=1
EOF

echo "Geschrieben: $CONF"
echo "Starte: freecashd -daemon"
echo "Adresse: freecash-cli getnewaddress  → in config/config.yaml eintragen"
