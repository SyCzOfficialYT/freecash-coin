#!/usr/bin/env python3
"""FreeCash Solo Dashboard – VarDiff round effort bar"""
from flask import Flask, render_template, jsonify
import yaml, json, requests, time, re, os
from requests.auth import HTTPBasicAuth
from pathlib import Path
from datetime import datetime

app = Flask(__name__, template_folder="templates")
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = ROOT / "config" / "config.example.yaml"
EVENTS_PATH = ROOT / "data" / "events.jsonl"
STRATUM_LOG = ROOT / "data" / "stratum.log"
STATS_PATH = ROOT / "data" / "stats.json"
COINBASE_MATURITY = 14400  # FreeCash consensus: coinbaseMaturity
HR_WINDOW_SEC = 600

def load_cfg():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

cfg = load_cfg()
RPC_HOST = cfg["rpc"]["host"]
RPC_PORT = cfg["rpc"]["port"]
RPC_USER = cfg["rpc"]["user"]
RPC_PASS = cfg["rpc"]["password"]

def rpc(method, params=None):
    try:
        r = requests.post(f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "m", "method": method, "params": params or []},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS), timeout=10)
        return r.json().get("result")
    except Exception:
        return None

def get_holding_address():
    try:
        return (load_cfg().get("pool") or {}).get("payout_address") or ""
    except Exception:
        return cfg.get("pool", {}).get("payout_address") or ""

def validate_holding(addr):
    if not addr or not str(addr).startswith("F"):
        return False, "keine F… Adresse"
    if re.search(r"CHANGE|xxxxxxxx", addr, re.I):
        return False, "Platzhalter"
    info = rpc("validateaddress", [addr])
    if info is None:
        return True, "RPC offline"
    return (True, "valid") if info.get("isvalid") else (False, "ungültig")

def load_stats():
    try:
        if STATS_PATH.exists():
            return json.loads(STATS_PATH.read_text())
    except Exception:
        pass
    return {}

def wallet_balances():
    out = {"confirmed": 0.0, "unconfirmed": 0.0, "immature": 0.0, "pending": 0.0}
    gb = rpc("getbalances")
    if isinstance(gb, dict) and "mine" in gb:
        m = gb["mine"]
        out["confirmed"] = float(m.get("trusted") or 0)
        out["immature"] = float(m.get("immature") or 0)
        out["pending"] = float(m.get("untrusted_pending") or 0)
        out["unconfirmed"] = out["immature"] + out["pending"]
        return out
    bal = rpc("getbalance")
    if bal is not None:
        out["confirmed"] = float(bal)
    wi = rpc("getwalletinfo")
    if isinstance(wi, dict):
        out["immature"] = float(wi.get("immature_balance") or 0)
        out["unconfirmed"] = out["immature"] + float(wi.get("unconfirmed_balance") or 0)
    return out

def maturity_info(height, blocks_log):
    rows = []
    for b in blocks_log or []:
        bh = int(b.get("height") or 0)
        mature_at = int(b.get("mature_at_height") or (bh + COINBASE_MATURITY))
        left = max(0, mature_at - height)
        rows.append({
            "height": bh, "hash": (b.get("hash") or "")[:16], "reward": b.get("reward"),
            "ts": b.get("ts"), "mature_at": mature_at,
            "confs": min(COINBASE_MATURITY, max(0, height - bh)),
            "left": left, "spendable": left <= 0, "eta_min": left,
        })
    return rows

def read_tail_lines(path: Path, n: int = 80):
    if not path.exists():
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell(); block = 8192; data = b""
            while size > 0 and data.count(b"\n") <= n:
                step = min(block, size); size -= step; f.seek(size); data = f.read(step) + data
            return data.decode(errors="ignore").splitlines()[-n:]
    except Exception:
        return []

def load_events(limit=100):
    lines = []
    for raw in read_tail_lines(EVENTS_PATH, limit):
        raw = raw.strip()
        if not raw: continue
        try:
            ev = json.loads(raw)
            lines.append({"ts": ev.get("ts", ""), "level": ev.get("level", "INFO"), "msg": ev.get("msg", raw)})
        except Exception:
            lines.append({"ts": "", "level": "INFO", "msg": raw})
    for raw in read_tail_lines(STRATUM_LOG, limit):
        raw = raw.strip()
        if not raw: continue
        m = re.match(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\d]*)\s+\[(\w+)\]\s+(.*)$", raw)
        if m:
            lines.append({"ts": m.group(1), "level": m.group(2), "msg": m.group(3)})
        else:
            lines.append({"ts": "", "level": "INFO", "msg": raw})
    lines.sort(key=lambda x: x.get("ts") or "")
    return lines[-limit:]

def _parse_ts(ts):
    try:
        return time.mktime(datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S").timetuple())
    except Exception:
        return None

def estimate_hashrate(stats, share_diff_fallback):
    now = time.time()
    window = []
    for s in stats.get("recent_shares") or []:
        if not s.get("ok", True): continue
        t = _parse_ts(s.get("ts"))
        if t is None or now - t > HR_WINDOW_SEC: continue
        d = float(s.get("pool_diff") or share_diff_fallback or 0)
        if d > 0: window.append((t, d))
    if len(window) >= 2:
        t_min = min(t for t, _ in window)
        t_max = max(t for t, _ in window)
        elapsed = max(t_max - t_min, 1.0)
        if now - t_min < HR_WINDOW_SEC:
            elapsed = max(elapsed, now - t_min)
        return (sum(d for _, d in window) * (2**32)) / elapsed
    return None

def fmt_hashrate(hps):
    if hps is None: return "–"
    units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s"]
    i, v = 0, float(hps)
    while v >= 1000 and i < len(units) - 1:
        v /= 1000; i += 1
    return f"{v:.2f} {units[i]}"

def fmt_diff(d):
    if d is None: return "–"
    try: d = float(d)
    except Exception: return "–"
    if d >= 1e9: return f"{d/1e9:.2f} G"
    if d >= 1e6: return f"{d/1e6:.2f} M"
    if d >= 1e3: return f"{d/1e3:.2f} k"
    return f"{d:.2f}"

def eta_seconds(network_diff, hashrate):
    if not network_diff or not hashrate or hashrate <= 0: return None
    return (float(network_diff) * (2**32)) / hashrate

def fmt_duration(sec):
    if sec is None or sec < 0: return "∞"
    if sec < 60: return f"{int(sec)}s"
    if sec < 3600: return f"{int(sec//60)}m {int(sec%60)}s"
    if sec < 86400: return f"{int(sec//3600)}h {int((sec%3600)//60)}m"
    return f"{int(sec//86400)}d {int((sec%86400)//3600)}h"

def build_payload():
    info = rpc("getblockchaininfo") or {}
    net = rpc("getnetworkinfo") or {}
    height = info.get("blocks") or 0
    difficulty = float(info.get("difficulty") or 0)
    synced = not info.get("initialblockdownload", True)
    connections = net.get("connections", 0)
    stats = load_stats()
    wbal = wallet_balances()
    shares_ok = stats.get("shares_ok") or 0
    shares_bad = stats.get("shares_bad") or 0
    total = shares_ok + shares_bad
    reject_pct = (100.0 * shares_bad / total) if total else 0.0
    # Best share = best in CURRENT ROUND only (resets on new height)
    best = float(stats.get("best_share_diff") or stats.get("round_best") or 0)
    last_work = float(stats.get("last_share_work") or 0)
    share_diff = stats.get("last_share_diff") or cfg["pool"].get("start_difficulty", 10000)
    hr = estimate_hashrate(stats, share_diff)
    net_d = float(stats.get("network_diff") or difficulty or 1)
    # Round effort: sum(share diffs)/net_diff — can exceed 100% until block found
    effort = float(stats.get("round_effort_pct") or 0)
    last_pct = (100.0 * last_work / net_d) if net_d and last_work else 0.0
    best_pct = (100.0 * best / net_d) if net_d and best else 0.0
    eta = eta_seconds(net_d, hr) if hr else None
    holding = get_holding_address()
    addr_ok, addr_msg = validate_holding(holding)
    mat = maturity_info(height, stats.get("blocks_log") or [])
    return {
        "synced": synced, "height": height, "difficulty": difficulty,
        "difficulty_fmt": fmt_diff(net_d), "hashrate_fmt": fmt_hashrate(hr),
        "confirmed": wbal["confirmed"], "unconfirmed": wbal["unconfirmed"],
        "confirmed_fmt": f"{wbal['confirmed']:.8f}".rstrip("0").rstrip(".") or "0",
        "unconfirmed_fmt": f"{wbal['unconfirmed']:.8f}".rstrip("0").rstrip(".") or "0",
        "blocks_found": stats.get("blocks_found") or 0,
        "rewards": float(stats.get("block_rewards_total") or 0),
        "rewards_fmt": f"{float(stats.get('block_rewards_total') or 0):.4f}",
        "effort_pct": round(effort, 3),
        "best_pct": round(best_pct, 4),
        "last_pct": round(last_pct, 4),
        "eta_fmt": fmt_duration(eta),
        "best_share_fmt": fmt_diff(best),
        "last_share_work_fmt": fmt_diff(last_work),
        "shares_ok": shares_ok, "shares_bad": shares_bad,
        "reject_pct": round(reject_pct, 1),
        "share_diff_fmt": fmt_diff(share_diff),
        "last_share_time": stats.get("last_share_time"),
        "last_share_hash": stats.get("last_share_hash"),
        "payout": holding, "addr_ok": addr_ok, "addr_msg": addr_msg,
        "workers": stats.get("workers") or {},
        "started_at": stats.get("started_at"),
        "connections": connections,
        "rpc_host": RPC_HOST, "rpc_port": RPC_PORT,
        "recent_shares": list(reversed(stats.get("recent_shares") or []))[:25],
        "blocks_log": list(reversed(mat))[:10],
        "maturity_blocks": COINBASE_MATURITY,
        "round_height": stats.get("round_height") or height,
        "round_shares": stats.get("round_shares") or 0,
        "round_work": stats.get("round_work") or 0,
        "round_started_at": stats.get("round_started_at"),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

@app.route("/")
def index():
    return render_template("dashboard.html", **build_payload())

@app.route("/api/status")
def api_status():
    return jsonify(build_payload())

@app.route("/api/logs")
def api_logs():
    stats = load_stats()
    info = rpc("getblockchaininfo") or {}
    return jsonify({
        "events": load_events(120),
        "snapshot": {
            "height": info.get("blocks"),
            "shares_ok": stats.get("shares_ok", 0),
            "shares_bad": stats.get("shares_bad", 0),
            "blocks_found": stats.get("blocks_found", 0),
            "round_effort_pct": stats.get("round_effort_pct", 0),
            "round_shares": stats.get("round_shares", 0),
            "best_share_diff": stats.get("best_share_diff", 0),
            "last_share_work": stats.get("last_share_work"),
        },
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    })

if __name__ == "__main__":
    host = cfg.get("monitor", {}).get("host", "0.0.0.0")
    port = int(cfg.get("monitor", {}).get("port", 5050))
    if port in (5000, 5001):
        port = 5050
    app.run(host=host, port=port, debug=False)
