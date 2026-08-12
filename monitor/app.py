#!/usr/bin/env python3
"""FreeCash Solo Dashboard – VarDiff round effort bar"""
import os, json, time, logging, yaml, requests
from pathlib import Path
from flask import Flask, render_template, jsonify, request

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config" / "config.yaml"
STATS = Path(os.environ.get("STATS_PATH", "/data/stats.json"))
EVENTS = Path(os.environ.get("EVENTS_PATH", "/data/events.jsonl"))

def load_cfg():
    with open(CFG) as f:
        return yaml.safe_load(f)

cfg = load_cfg()
rpc_cfg = cfg["rpc"]
log = logging.getLogger("monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

COINBASE_MATURITY = 14400

def rpc(method, params=None):
    url = f"http://{rpc_cfg['host']}:{rpc_cfg['port']}"
    payload = {"jsonrpc": "1.0", "id": "mon", "method": method, "params": params or []}
    try:
        r = requests.post(url, json=payload, auth=(rpc_cfg["user"], rpc_cfg["password"]), timeout=8)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            return None
        return data.get("result")
    except Exception as e:
        log.debug("rpc %s: %s", method, e)
        return None

def load_stats():
    try:
        if STATS.exists():
            return json.loads(STATS.read_text())
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

def balances_merged(height, blocks_log, wbal):
    immature_log = 0.0
    matured_log = 0.0
    for b in blocks_log or []:
        bh = int(b.get("height") or 0)
        rew = float(b.get("reward") or 0)
        mature_at = int(b.get("mature_at_height") or (bh + COINBASE_MATURITY))
        if height >= mature_at:
            matured_log += rew
        else:
            immature_log += rew
    w_conf = float(wbal.get("confirmed") or 0)
    w_unc = float(wbal.get("unconfirmed") or 0)
    if blocks_log:
        confirmed = max(w_conf, matured_log)
        unconfirmed = immature_log
        if unconfirmed <= 0 and w_unc > 0 and matured_log <= 0:
            unconfirmed = w_unc
        return confirmed, unconfirmed
    return w_conf, w_unc

def maturity_info(height, blocks_log):
    rows = []
    for b in blocks_log or []:
        bh = int(b.get("height") or 0)
        mature_at = int(b.get("mature_at_height") or (bh + COINBASE_MATURITY))
        left = max(0, mature_at - height)
        rows.append({
            "height": bh, "hash": (b.get("hash") or "")[:16],
            "ts": b.get("ts"), "mature_at": mature_at,
            "confs": min(COINBASE_MATURITY, max(0, height - bh)),
            "left": left, "spendable": left == 0,
            "reward": b.get("reward"),
        })
    return rows

def get_holding_address():
    return (cfg.get("pool") or {}).get("payout_address") or ""

def validate_holding(addr):
    if not addr:
        return False, "no payout_address"
    info = rpc("validateaddress", [addr])
    if info and info.get("isvalid"):
        return True, "ok"
    return False, "invalid"

def estimate_hashrate(stats, share_diff):
    try:
        return float(stats.get("est_hashrate") or 0)
    except Exception:
        return 0.0

def eta_seconds(net_diff, hr):
    if not hr or hr <= 0 or not net_diff:
        return None
    return (float(net_diff) * (2 ** 32)) / float(hr)

def fmt_hashrate(hps):
    try:
        h = float(hps or 0)
    except Exception:
        return "0 H/s"
    for u, d in (("TH/s", 1e12), ("GH/s", 1e9), ("MH/s", 1e6), ("KH/s", 1e3)):
        if h >= d:
            return f"{h/d:.2f} {u}"
    return f"{h:.0f} H/s"

def fmt_diff(d):
    try:
        d = float(d or 0)
    except Exception:
        return "0"
    if d >= 1e9: return f"{d/1e9:.2f} G"
    if d >= 1e6: return f"{d/1e6:.2f} M"
    if d >= 1e3: return f"{d/1e3:.2f} k"
    return f"{d:.2f}"

def fmt_duration(sec):
    if sec is None: return "–"
    try: s = int(sec)
    except Exception: return "–"
    if s < 0: s = 0
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    if h: return f"{h}h {m}m"
    if m: return f"{m}m {s}s"
    return f"{s}s"

def build_payload():
    stats = load_stats()
    tip = rpc("getblockchaininfo") or {}
    height = int(tip.get("blocks") or stats.get("height") or 0)
    difficulty = float(tip.get("difficulty") or stats.get("network_diff") or 0)
    synced = bool(tip.get("blocks")) and tip.get("blocks") == tip.get("headers")
    wbal = wallet_balances()
    blog = stats.get("blocks_log") or []
    confirmed, unconfirmed = balances_merged(height, blog, wbal)
    shares_ok = stats.get("shares_ok") or 0
    shares_bad = stats.get("shares_bad") or 0
    total = shares_ok + shares_bad
    reject_pct = (100.0 * shares_bad / total) if total else 0.0
    best = float(stats.get("best_share_diff") or stats.get("round_best") or 0)
    last_work = float(stats.get("last_share_work") or 0)
    share_diff = stats.get("last_share_diff") or cfg["pool"].get("start_difficulty", 10000)
    hr = estimate_hashrate(stats, share_diff)
    net_d = float(stats.get("network_diff") or difficulty or 1)
    effort = float(stats.get("round_effort_pct") or 0)
    last_pct = (100.0 * last_work / net_d) if net_d and last_work else 0.0
    best_pct = (100.0 * best / net_d) if net_d and best else 0.0
    eta = eta_seconds(net_d, hr) if hr else None
    holding = get_holding_address()
    addr_ok, addr_msg = validate_holding(holding)
    mat = maturity_info(height, blog)
    found_set = {int(b.get("height") or 0) for b in blog}
    strip_n = 12
    height_strip = []
    for h in range(max(0, height - strip_n + 1), height + 1):
        height_strip.append({
            "h": h,
            "short": str(h)[-3:].zfill(3) if h >= 100 else str(h),
            "found": h in found_set,
            "current": h == height,
        })
    return {
        "synced": synced, "height": height, "difficulty": difficulty,
        "height_strip": height_strip,
        "found_heights": sorted(found_set)[-50:],
        "difficulty_fmt": fmt_diff(net_d), "hashrate_fmt": fmt_hashrate(hr),
        "confirmed": confirmed, "unconfirmed": unconfirmed,
        "confirmed_fmt": f"{confirmed:.8f}",
        "unconfirmed_fmt": f"{unconfirmed:.8f}",
        "blocks_found": stats.get("blocks_found") or 0,
        "rewards": float(stats.get("block_rewards_total") or 0),
        "rewards_fmt": f"{float(stats.get('block_rewards_total') or 0):.8f}",
        "shares_ok": shares_ok, "shares_bad": shares_bad, "reject_pct": reject_pct,
        "effort_pct": effort, "best_pct": best_pct, "last_pct": last_pct,
        "eta_fmt": fmt_duration(eta),
        "best_share_fmt": fmt_diff(best),
        "last_share_work_fmt": fmt_diff(last_work),
        "last_share_time": stats.get("last_share_time"),
        "last_share_hash": stats.get("last_share_hash"),
        "share_diff_fmt": fmt_diff(share_diff),
        "payout_address": holding, "addr_ok": addr_ok, "addr_msg": addr_msg,
        "round_height": stats.get("round_height") or height,
        "round_started_at": stats.get("round_started_at"),
        "tip_changed_at": stats.get("tip_changed_at") or stats.get("round_started_at"),
        "target_block_sec": 60,
        "network_diff": net_d,
        "blocks_log": list(reversed(mat))[:14400],
        "maturity_blocks": COINBASE_MATURITY,
        "recent_shares": list(reversed(stats.get("recent_shares") or []))[:50],
    }

app = Flask(__name__, template_folder="templates")

@app.route("/")
def index():
    return render_template("dashboard.html", **build_payload())

@app.route("/api/status")
def api_status():
    return jsonify(build_payload())

@app.route("/api/events")
def api_events():
    lines = []
    try:
        if EVENTS.exists():
            lines = EVENTS.read_text().splitlines()[-200:]
    except Exception:
        pass
    return jsonify({"events": lines})

if __name__ == "__main__":
    host = os.environ.get("MONITOR_HOST", "0.0.0.0")
    port = int(os.environ.get("MONITOR_PORT", "5050"))
    app.run(host=host, port=port, debug=False)
