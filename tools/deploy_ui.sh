#!/bin/sh
set -e
cd "$(dirname "$0")/.."
echo "Deploying server + monitor + dashboard into freecash-solo ..."
sudo docker cp stratum/server.py freecash-solo:/app/stratum/server.py
sudo docker cp monitor/app.py freecash-solo:/app/monitor/app.py
sudo docker cp monitor/templates/dashboard.html freecash-solo:/app/monitor/templates/dashboard.html
sudo docker exec freecash-solo mkdir -p /app/tools
sudo docker cp tools/rebuild_blocks_log.py freecash-solo:/app/tools/rebuild_blocks_log.py
echo "Rebuilding blocks_log from wallet (no chain resync)..."
sudo docker exec freecash-solo python3 /app/tools/rebuild_blocks_log.py || true
sudo docker restart freecash-solo
sleep 5
sudo docker exec freecash-solo python3 -c "import json; d=json.load(open('/app/data/stats.json')); print('disk log', len(d.get('blocks_log') or []))"
echo "Done. Hard-reload browser (Ctrl+F5)."
