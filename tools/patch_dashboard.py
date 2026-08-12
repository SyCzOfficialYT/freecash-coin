#!/usr/bin/env python3
import base64, zlib, urllib.request
from pathlib import Path
BASE = "https://raw.githubusercontent.com/SyCzOfficialYT/freecash-coin/main/tools/"
chunks = []
for i in range(3):
    with urllib.request.urlopen(BASE + "d.b64.%d" % i, timeout=60) as r:
        chunks.append(r.read().decode().strip())
data = zlib.decompress(base64.b64decode("".join(chunks)))
out = Path("monitor/templates/dashboard.html")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(data)
print("dashboard written", len(data))
assert b"heightStrip" in data
