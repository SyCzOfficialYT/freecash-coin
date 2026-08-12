#!/usr/bin/env python3
"""Rebuild the persistent solo block history from wallet coinbase rewards.

The history is intentionally bounded only at a large safety limit.  It is not
used as the source of truth for blocks_found or block_rewards_total; those
counters remain cumulative.
"""
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone

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
HISTORY_LIMIT = 14400


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
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main():
    tip = rpc("getblockchaininfo") or {}
    height = int(tip.get("blocks") or 0)
    print(f"tip={height} payout={payout}")

    stats = json.loads(STATS.read_text()) if STATS.exists() else {}
    found = {}

    # Preserve every historical entry already known locally.
    for b in stats.get("blocks_log") or []:
        h = int(b.get("height") or 0)
        if h:
            found[h] = b

    # Wallet history is the authoritative source for generated/immature blocks.
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
        block_hash = tx.get("blockhash") or ""
        if not block_hash and tx.get("txid"):
            block_hash = tx["txid"]

        entry = {
            "ts": ts_fmt(tx.get("blocktime") or tx.get("time")),
            "height": bh,
            "hash": block_hash[:64],
            "reward": amt,
            "address": payout or tx.get("address") or "",
            "mature_at_height": bh + MATURITY,
        }

        # Prefer the wallet's current reward information over stale local data.
        if bh not in found or float(found[bh].get("reward") or 0) < amt:
            found[bh] = entry
        print(f"  wallet {cat} h={bh} reward={amt}")

    # Optional chain scan is only a recovery path.  It never replaces wallet
    # history and is intentionally limited to the recent chain.
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
            reward = 0.0
            hit = False
            for v in cb.get("vout") or []:
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

    # Keep the complete recent history, not the old 20-entry dashboard cache.
    blog = [found[h] for h in sorted(found.keys())][-HISTORY_LIMIT:]
    stats["blocks_log"] = blog

    # Cumulative counters must never decrease merely because the history window
    # is bounded.  The wallet-derived history is used to repair missing totals.
    history_count = len(found)
    stats["blocks_found"] = max(int(stats.get("blocks_found") or 0), history_count)

    history_rewards = sum(float(b.get("reward") or 0) for b in found.values())
    stats["block_rewards_total"] = max(
        float(stats.get("block_rewards_total") or 0), history_rewards
    )

    if STATS.exists():
        bak = STATS.with_suffix(".json.bak")
        bak.write_text(STATS.read_text())
        print("backup", bak)

    STATS.write_text(json.dumps(stats, indent=2))
    print(
        f"DONE history={len(blog)} wallet_found={history_count} "
        f"found_counter={stats.get('blocks_found')} "
        f"rewards={stats.get('block_rewards_total')}"
    )
    for b in blog[-8:]:
        print(" ", b.get("height"), b.get("reward"), str(b.get("hash") or "")[:16])


if __name__ == "__main__":
    main()
