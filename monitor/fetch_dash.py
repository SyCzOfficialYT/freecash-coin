#!/usr/bin/env python3
import base64, zlib, urllib.request
from pathlib import Path
BASE = "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/main/monitor/"
chunks = []
for i in range(3):
    with urllib.request.urlopen(BASE + "dash.b64.%d" % i) as r:
        chunks.append(r.read().decode())
data = zlib.decompress(base64.b64decode("".join(chunks)))
out = Path("monitor/templates/dashboard.html")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(data)
print("OK", out, len(data))
