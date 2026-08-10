#!/bin/bash
# One-shot: force dashboard on 5050 inside running container (no rebuild)
set -e
C="${1:-freecash-solo}"

echo "== config port 5050 =="
docker exec "$C" python3 -c "
import yaml
from pathlib import Path
p = Path('/app/config/config.yaml')
cfg = yaml.safe_load(p.read_text()) if p.exists() else {}
cfg.setdefault('monitor', {})
cfg['monitor'] = {'host': '0.0.0.0', 'port': 5050}
p.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))
print(cfg['monitor'])
"

echo "== kill old monitor if any =="
docker exec "$C" bash -c 'for p in $(ps aux | grep "monitor/app.py" | grep -v grep | awk "{print \$2}"); do kill "\$p" 2>/dev/null; done' || true
sleep 1

echo "== start monitor =="
docker exec -d "$C" python3 /app/monitor/app.py
sleep 2

echo "== listen =="
ss -tlnp 2>/dev/null | grep 5050 || netstat -tlnp 2>/dev/null | grep 5050 || true
echo "Done. Open http://HOST:5050"
