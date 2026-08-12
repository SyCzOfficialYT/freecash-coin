#!/bin/sh
# Deploy working FreeCash solo UI + stratum with persistent block history.
set -e
cd "$(dirname "$0")/.."

HISTORY_LIMIT=14400
SERVER_REF="a88d89675b"

printf '%s\n' "==> Fetch good server (${SERVER_REF}) + apply runtime fixes"
curl -fsSL "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/${SERVER_REF}/stratum/server.py" -o stratum/server.py
sed -i 's/job_interval", 20)/job_interval", 4)/' stratum/server.py
sed -i "s/blog\\[-20:\\]/blog[-${HISTORY_LIMIT}:]/" stratum/server.py

python3 -c "
from pathlib import Path
p=Path('stratum/server.py')
t=p.read_text()
a='if job is not None and clean:\n                broadcast_job(clean=True)'
b='if job is not None:\n                if clean:\n                    broadcast_job(clean=True)\n                else:\n                    broadcast_job(clean=False)'
if a in t:
    p.write_text(t.replace(a,b,1)); print('job_loop patched')
else:
    print('job_loop already patched')
"

python3 -c "
import ast
from pathlib import Path
p=Path('stratum/server.py')
ast.parse(p.read_text())
t=p.read_text()
assert f'blog[-{14400}:]' in t, 'persistent history patch missing'
print('server OK; history limit=14400')
"

echo "==> Fetch monitor app"
curl -fsSL "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/main/monitor/app.py" -o monitor/app.py
sed -i 's/list(reversed(mat))\[:10\]/list(reversed(mat))[:14400]/' monitor/app.py
sed -i 's/list(reversed(mat))\[:20\]/list(reversed(mat))[:14400]/' monitor/app.py

echo "==> Write dashboard (height chips + sparkline + time bar)"
python3 tools/patch_dashboard.py

echo "==> Copy into container"
sudo docker cp stratum/server.py freecash-solo:/app/stratum/server.py
sudo docker cp monitor/app.py freecash-solo:/app/monitor/app.py
sudo docker cp monitor/templates/dashboard.html freecash-solo:/app/monitor/templates/dashboard.html
sudo docker exec freecash-solo mkdir -p /app/tools
sudo docker cp tools/rebuild_blocks_log.py freecash-solo:/app/tools/rebuild_blocks_log.py

echo "==> Rebuild complete solo block history from wallet + recovery scan"
sudo docker exec freecash-solo python3 /app/tools/rebuild_blocks_log.py

echo "==> Restart"
sudo docker restart freecash-solo
sleep 8

sudo docker exec freecash-solo python3 -c "import json; d=json.load(open('/app/data/stats.json')); log=d.get('blocks_log') or []; print('disk log', len(log)); print('blocks found', d.get('blocks_found')); print('rewards', d.get('block_rewards_total')); assert len(log) <= 14400"

echo "Done. Hard refresh the dashboard (Ctrl+F5)."