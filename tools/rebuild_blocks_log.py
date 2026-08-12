#!/usr/bin/env python3
"""Rebuild stats.json blocks_log from wallet coinbase/generate txs + chain."""
import json, os, sys
from pathlib import Path
from datetime import datetime

try:
    import yaml
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "requests", "-q"])
    import yaml
    import requests
    from requests.auth import HTTPBasicAuth

ROOT = Path(os.environ.get("APP_ROOT", "/app"))
STATS = Path(os.environ.get("STATS_PATH", str(ROOT / "data" / "stats.json")))
CFG_PATH = ROOT / "config" / "config.yaml"
if not CFG_PATH.exists():
    CFG_PATH = ROOT / "config" / "config.example.yaml"

cfg = yaml.safe_load(CFG_PATH.read_text())
rpc_c = cfg["rpc"]
payout = (cfg.get("pool") or {}).get("payout_address") or ""
MATURITY = 14400

def rpc(method, params=None):
    url = f"http://{rpc_c['host']}:{rpc_c['port']}"
    r = requests.post(
        url,
        json={"jsonrpc": "1.0", "id": "rb", "method": method, "params": params or []},
        auth=HTTPBasicAuth(rpc_c["user"], rpc_c["password"]),
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("result")

def ts_fmt(epoch):
    if not epoch:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return datetime.utcfromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")

def main():
    tip = rpc("getblockchaininfo") or {}
    height = int(tip.get("blocks") or 0)
    print(f"tip={height} payout={payout}")

    found = {}
    stats = {}
    if STATS.exists():
        stats = json.loads(STATS.read_text())
    for b in stats.get("blocks_log") or []:
        h = int(b.get("height") or 0)
        if h:
            found[h] = b

    try:
        txs = rpc("listtransactions", ["*", 1000, 0, True]) or []
    except Exception as e:
        print("listtransactions failed:", e)
        txs = []

    for tx in txs:
        cat = (tx.get("category") or "").lower()
        if cat not in ("generate", "immature", "orphan"):
            continue
        bh = tx.get("blockheight") or tx.get("height")
        if bh is None and tx.get("blockhash"):
            try:
                bi = rpc("getblock", [tx["blockhash"]])
                bh = bi.get("height")
            except Exception:
                continue
        if bh is None:
            continue
        bh = int(bh)
        amt = float(tx.get("amount") or 0)
        hx = (tx.get("blockhash") or tx.get("txid") or "")[:64]
        entry = {
            "ts": ts_fmt(tx.get("blocktime") or tx.get("time")),
            "height": bh,
            "hash": hx,
            "reward": amt,
            "address": payout or tx.get("address") or "",
            "mature_at_height": bh + MATURITY,
        }
        if bh not in found or float(found[bh].get("reward") or 0) < amt:
            found[bh] = entry
        print(f"  wallet {cat} h={bh} reward={amt}")

    target = int(stats.get("blocks_found") or 0)
    if payout and len(found) < max(target, 1):
        scan_n = min(height, 20000)
        print(f"scanning last {scan_n} blocks for coinbase -> {payout} ...")
        for h in range(height, max(0, height - scan_n), -1):
            if h in found:
                continue
            try:
                bhash = rpc("getblockhash", [h])
                blk = rpc("getblock", [bhash, 2])
            except Exception:
                continue
            txs_b = blk.get("tx") or []
            if not txs_b:
                continue
            cb = txs_b[0]
            vouts = cb.get("vout") or []
            hit = False
            reward = 0.0
            for v in vouts:
                spk = v.get("scriptPubKey") or {}
                addrs = list(spk.get("addresses") or [])
                addr = spk.get("address")
                if addr:
                    addrs.append(addr)
                if payout in addrs:
                    hit = True
                    reward += float(v.get("value") or 0)
            if hit:
                found[h] = {
                    "ts": ts_fmt(blk.get("time")),
                    "height": h,
                    "hash": (blk.get("hash") or bhash)[:64],
                    "reward": reward,
                    "address": payout,
                    "mature_at_height": h + MATURITY,
                }
                print(f"  chain hit h={h} reward={reward}")

    blog = [found[h] for h in sorted(found.keys())][-14400:]
    stats["blocks_log"] = blog
    if blog:
        stats["blocks_found"] = max(int(stats.get("blocks_found") or 0), len(blog))
        total_rew = sum(float(b.get("reward") or 0) for b in blog)
        stats["block_rewards_total"] = max(float(stats.get("block_rewards_total") or 0), total_rew)

    if STATS.exists():
        bak = STATS.with_suffix(".json.bak")
        bak.write_text(STATS.read_text())
        print("backup", bak)

    STATS.write_text(json.dumps(stats, indent=2))
    print(f"DONE log={len(blog)} found_counter={stats.get('blocks_found')} rewards={stats.get('block_rewards_total')}")
    for b in blog[-8:]:
        print(" ", b.get("height"), b.get("reward"), str(b.get("hash") or "")[:16])

if __name__ == "__main__":
    main()
