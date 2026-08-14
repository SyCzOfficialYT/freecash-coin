#!/bin/sh
# Deploy the working FreeCash solo UI + stratum without dirtying tracked source files.
set -e
cd "$(dirname "$0")/.."

HISTORY_LIMIT=14400
SERVER_REF="a88d89675b"
TMP_DIR="${TMPDIR:-/tmp}/freecash-solo-deploy"
mkdir -p "$TMP_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

printf '%s\n' "==> Fetch working server (${SERVER_REF}) into temporary deploy area"
curl -fsSL "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/${SERVER_REF}/stratum/server.py" -o "$TMP_DIR/server.py"
sed -i 's/job_interval", 20)/job_interval", 4)/' "$TMP_DIR/server.py"
sed -i "s/blog\\[-20:\\]/blog[-${HISTORY_LIMIT}:]/" "$TMP_DIR/server.py"

python3 - "$TMP_DIR/server.py" <<'PY'
import ast
import sys
from pathlib import Path

p = Path(sys.argv[1])
t = p.read_text()
a = 'if job is not None and clean:\n                broadcast_job(clean=True)'
b = 'if job is not None:\n                if clean:\n                    broadcast_job(clean=True)\n                else:\n                    broadcast_job(clean=False)'
if a in t:
    t = t.replace(a, b, 1)
    p.write_text(t)
    print('job_loop patched')
else:
    print('job_loop already patched')
ast.parse(t)
assert f'blog[-{14400}:]' in t, 'persistent history patch missing'
print('server OK; history limit=14400')
PY

printf '%s\n' "==> Fetch monitor app into temporary deploy area"
curl -fsSL "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/main/monitor/app.py" -o "$TMP_DIR/app.py"
sed -i 's/list(reversed(mat))\[:10\]/list(reversed(mat))[:14400]/' "$TMP_DIR/app.py"
sed -i 's/list(reversed(mat))\[:20\]/list(reversed(mat))[:14400]/' "$TMP_DIR/app.py"

printf '%s\n' "==> Ensure dashboard template is generated"
python3 tools/patch_dashboard.py

printf '%s\n' "==> Copy runtime files into container"
sudo docker cp "$TMP_DIR/server.py" freecash-solo:/app/stratum/server.py
sudo docker cp "$TMP_DIR/app.py" freecash-solo:/app/monitor/app.py
sudo docker cp monitor/templates/dashboard.html freecash-solo:/app/monitor/templates/dashboard.html
sudo docker exec freecash-solo mkdir -p /app/tools
sudo docker cp tools/rebuild_blocks_log.py freecash-solo:/app/tools/rebuild_blocks_log.py

printf '%s\n' "==> Rebuild persistent block history from wallet + existing local log"
sudo docker exec freecash-solo python3 /app/tools/rebuild_blocks_log.py

printf '%s\n' "==> Restart"
sudo docker restart freecash-solo
sleep 8

sudo docker exec freecash-solo python3 -c "import json; d=json.load(open('/app/data/stats.json')); log=d.get('blocks_log') or []; print('disk log', len(log)); print('blocks found', d.get('blocks_found')); print('rewards', d.get('block_rewards_total')); assert len(log) <= 14400"

echo "Done. Working tree remains clean; hard refresh dashboard with Ctrl+F5."
