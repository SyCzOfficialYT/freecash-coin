#!/usr/bin/env python3
"""FreeCash Solo Dashboard – Holding-Adresse + Live-Terminal"""
from flask import Flask, render_template, jsonify
import yaml, json, requests, time, re, os
from requests.auth import HTTPBasicAuth
from pathlib import Path
from collections import deque

app = Flask(__name__, template_folder="templates")
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = ROOT / "config" / "config.example.yaml"

EVENTS_PATH = ROOT / "data" / "events.jsonl"
STRATUM_LOG = ROOT / "data" / "stratum.log"
STATS_PATH = ROOT / "data" / "stats.json"


def load_cfg():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


cfg = load_cfg()
RPC_HOST = cfg["rpc"]["host"]
RPC_PORT = cfg["rpc"]["port"]
RPC_USER = cfg["rpc"]["user"]
RPC_PASS = cfg["rpc"]["password"]
PAYOUT_THRESHOLD = float(cfg.get("pool", {}).get("payout_threshold", 10.0))


def rpc(method, params=None):
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "m", "method": method, "params": params or []},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS),
            timeout=10,
        )
        return r.json().get("result")
    except Exception:
        return None


def get_holding_address():
    try:
        c = load_cfg()
        return (c.get("pool") or {}).get("payout_address") or ""
    except Exception:
        return cfg.get("pool", {}).get("payout_address") or ""


def validate_holding(addr):
    if not addr or not str(addr).startswith("F"):
        return False, "keine F… Adresse"
    if re.search(r"CHANGE|xxxxxxxx", addr, re.I):
        return False, "Platzhalter"
    info = rpc("validateaddress", [addr])
    if info is None:
        return True, "RPC offline – Format ok"
    if info.get("isvalid"):
        return True, "valid"
    return False, "ungültig laut Node"


def load_stats():
    try:
        if STATS_PATH.exists():
            return json.loads(STATS_PATH.read_text())
    except Exception:
        pass
    return {
        "shares_ok": 0, "shares_bad": 0, "blocks_found": 0, "best_share_diff": 0,
        "block_rewards_total": 0.0, "workers": {}, "last_share_time": None,
        "last_share_diff": None, "last_share_hash": None, "started_at": None,
    }


def read_tail_lines(path: Path, n: int = 80):
    if not path.exists():
        return []
    try:
        # efficient-ish tail
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 8192
            data = b""
            while size > 0 and data.count(b"\n") <= n:
                step = min(block, size)
                size -= step
                f.seek(size)
                data = f.read(step) + data
            lines = data.decode(errors="ignore").splitlines()
            return lines[-n:]
    except Exception:
        return []


def load_events(limit: int = 100):
    """Strukturierte Events + Stratum-Log-Zeilen als Terminal-Zeilen."""
    lines = []
    # JSONL events (neueste zuerst sammeln, dann umdrehen)
    for raw in read_tail_lines(EVENTS_PATH, limit):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
            ts = ev.get("ts", "")
            level = ev.get("level", "INFO")
            msg = ev.get("msg", raw)
            lines.append({"ts": ts, "level": level, "msg": msg, "src": "event"})
        except Exception:
            lines.append({"ts": "", "level": "INFO", "msg": raw, "src": "event"})

    # Stratum plain log
    for raw in read_tail_lines(STRATUM_LOG, limit):
        raw = raw.strip()
        if not raw:
            continue
        # typisches Format: 2026-... [INFO] message
        m = re.match(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\d]*)\s+\[(\w+)\]\s+(.*)$", raw)
        if m:
            lines.append({"ts": m.group(1), "level": m.group(2), "msg": m.group(3), "src": "stratum"})
        else:
            lines.append({"ts": "", "level": "INFO", "msg": raw, "src": "stratum"})

    # sort by ts if present, keep last `limit`
    def key(x):
        return x.get("ts") or ""

    lines.sort(key=key)
    return lines[-limit:]


def estimate_hashrate(stats, share_diff):
    ok = stats.get("shares_ok") or 0
    if ok < 2 or not share_diff:
        return None
    started = stats.get("started_at")
    if not started:
        return None
    try:
        t0 = time.mktime(time.strptime(started, "%Y-%m-%d %H:%M:%S"))
        elapsed = max(time.time() - t0, 1)
        return (ok * float(share_diff) * (2**32)) / elapsed
    except Exception:
        return None


def fmt_hashrate(hps):
    if hps is None:
        return "–"
    units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s"]
    i = 0
    while hps >= 1000 and i < len(units) - 1:
        hps /= 1000
        i += 1
    return f"{hps:.2f} {units[i]}"


def fmt_diff(d):
    if d is None:
        return "–"
    if d >= 1e9:
        return f"{d/1e9:.2f} G"
    if d >= 1e6:
        return f"{d/1e6:.2f} M"
    if d >= 1e3:
        return f"{d/1e3:.2f} k"
    return f"{d:.2f}"


def eta_seconds(network_diff, hashrate):
    if not network_diff or not hashrate or hashrate <= 0:
        return None
    return (network_diff * (2**32)) / hashrate


def fmt_duration(sec):
    if sec is None or sec < 0:
        return "∞"
    if sec < 60:
        return f"{int(sec)}s"
    if sec < 3600:
        return f"{int(sec//60)}m {int(sec%60)}s"
    if sec < 86400:
        return f"{int(sec//3600)}h {int((sec%3600)//60)}m"
    return f"{int(sec//86400)}d {int((sec%86400)//3600)}h"


@app.route("/")
def index():
    info = rpc("getblockchaininfo") or {}
    net = rpc("getnetworkinfo") or {}
    balance = rpc("getbalance")
    height = info.get("blocks") or 0
    difficulty = info.get("difficulty") or 0
    synced = not info.get("initialblockdownload", True)
    connections = net.get("connections", 0)
    stats = load_stats()
    shares_ok = stats.get("shares_ok") or 0
    shares_bad = stats.get("shares_bad") or 0
    total = shares_ok + shares_bad
    reject_pct = f"{(100.0 * shares_bad / total):.1f}" if total else "0.0"
    blocks_found = stats.get("blocks_found") or 0
    best = stats.get("best_share_diff") or 0
    rewards = stats.get("block_rewards_total") or 0.0
    share_diff = stats.get("last_share_diff") or cfg["pool"].get("start_difficulty", 256)
    hr = estimate_hashrate(stats, share_diff)
    eta = eta_seconds(difficulty, hr) if hr else None
    effort = min(100.0, 100.0 * float(best) / float(difficulty)) if difficulty and best else 0.0
    soft = min(40.0, shares_ok * 0.5) if shares_ok else 0
    effort_bar = max(effort, soft)
    bal = float(balance) if balance is not None else 0.0
    holding = get_holding_address()
    addr_ok, addr_msg = validate_holding(holding)

    return render_template(
        "dashboard.html",
        synced=synced,
        height=height,
        difficulty_fmt=fmt_diff(difficulty),
        hashrate_fmt=fmt_hashrate(hr),
        balance_fmt=f"{bal:.4f}",
        blocks_found=blocks_found,
        rewards_fmt=f"{rewards:.4f}",
        effort_pct=f"{effort:.2f}",
        effort_bar=f"{effort_bar:.1f}",
        eta_fmt=fmt_duration(eta),
        best_share_fmt=fmt_diff(best),
        shares_ok=shares_ok,
        shares_bad=shares_bad,
        reject_pct=reject_pct,
        share_diff_fmt=fmt_diff(share_diff),
        last_share_time=stats.get("last_share_time"),
        last_share_hash=stats.get("last_share_hash"),
        threshold_fmt=f"{PAYOUT_THRESHOLD:.2f}",
        payout=holding,
        addr_ok=addr_ok,
        addr_msg=addr_msg,
        workers=stats.get("workers") or {},
        started_at=stats.get("started_at"),
        connections=connections,
        rpc_host=RPC_HOST,
        rpc_port=RPC_PORT,
        now=time.strftime("%Y-%m-%d %H:%M:%S"),
    )


@app.route("/api/status")
def api_status():
    info = rpc("getblockchaininfo") or {}
    holding = get_holding_address()
    addr_ok, addr_msg = validate_holding(holding)
    stats = load_stats()
    share_diff = stats.get("last_share_diff") or cfg["pool"].get("start_difficulty", 256)
    hr = estimate_hashrate(stats, share_diff)
    return jsonify({
        "synced": not info.get("initialblockdownload", True),
        "height": info.get("blocks"),
        "difficulty": info.get("difficulty"),
        "balance": rpc("getbalance"),
        "holding_address": holding,
        "address_valid": addr_ok,
        "address_status": addr_msg,
        "hashrate_fmt": fmt_hashrate(hr),
        "stats": stats,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/logs")
def api_logs():
    """Live terminal: echte Events + Stratum-Log + Snapshot-Stats."""
    stats = load_stats()
    events = load_events(120)
    info = rpc("getblockchaininfo") or {}
    snapshot = {
        "height": info.get("blocks"),
        "difficulty": info.get("difficulty"),
        "shares_ok": stats.get("shares_ok", 0),
        "shares_bad": stats.get("shares_bad", 0),
        "blocks_found": stats.get("blocks_found", 0),
        "best_share_diff": stats.get("best_share_diff", 0),
        "last_share_time": stats.get("last_share_time"),
        "last_share_hash": stats.get("last_share_hash"),
        "workers": list((stats.get("workers") or {}).keys()),
        "holding": get_holding_address(),
        "balance": rpc("getbalance"),
    }
    return jsonify({"events": events, "snapshot": snapshot, "ts": time.strftime("%Y-%m-%d %H:%M:%S")})


if __name__ == "__main__":
    host = cfg.get("monitor", {}).get("host", "0.0.0.0")
    port = int(cfg.get("monitor", {}).get("port", 5000))
    app.run(host=host, port=port, debug=False)
