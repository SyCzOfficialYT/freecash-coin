#!/usr/bin/env python3
"""Expand packed server from .b64part* then run it."""
import zlib, base64, sys, runpy
from pathlib import Path
here = Path(__file__).resolve().parent
parts = sorted(here.glob("server.b64part*"))
if not parts:
    raise SystemExit("missing server.b64part* files")
b64 = "".join(p.read_text().strip() for p in parts)
impl = here / "_server_impl.py"
if not impl.exists() or impl.stat().st_size < 1000:
    impl.write_bytes(zlib.decompress(base64.b64decode(b64.encode())))
sys.argv[0] = str(impl)
runpy.run_path(str(impl), run_name="__main__")
