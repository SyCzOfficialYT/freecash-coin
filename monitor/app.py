#!/usr/bin/env python3
"""FreeCash Solo dashboard.

Read-only monitor for freecashd RPC and the stratum stats persisted in
/app/data. Mining state is never modified by the dashboard.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from flask import Flask, jsonify, render_template
from requests.auth import HTTPBasicAuth

app = Flask(__name__, template_folder="templates")
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = ROOT / "config" / "config.example.yaml"
DATA_DIR = Path(os.getenv("FCH_DATA_DIR", "/app/data"))
EVENTS_PATH = DATA_DIR / "events.jsonl"
STRATUM_LOG = DATA_DIR / "stratum.log"
STATS_PATH = DATA_DIR / "stats.json"
COINBASE_MATURITY = int(os.getenv("FCH_COINBASE_MATURITY", "14400"))
HR_WINDOW_SEC = int(os.getenv("FCH_HASHRATE_WINDOW", "600"))
DEFAULT_BLOCK_INTERVAL = float(os.getenv("FCH_BLOCK_INTERVAL", "60"))


def load_cfg() -> dict:
    try:
        with CONFIG_PATH.open() as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


cfg = load_cfg()
rpc_cfg = cfg.get("rpc") or {}
RPC_HOST = rpc_cfg.get("host", os.getenv("FCH_RPC_HOST", "127.0.0.1"))
RPC_PORT = int(rpc_cfg.get("port", os.getenv("FCH_RPC_PORT", "8332")))
RPC_USER = rpc_cfg.get("user", os.getenv("FCH_RPC_USER", "fchrpc"))
RPC_PASS = rpc_cfg.get("password", os.getenv("FCH_RPC_PASS", ""))
POOL_CFG = cfg.get("pool") or {}


def rpc(method: str, params=None):
    try:
        r = requests.post(f"http://{RPC_HOST}:{RPC_PORT}", json={"jsonrpc":"1.0","id":"dashboard","method":method,"params":params or []}, auth=HTTPBasicAuth(RPC_USER, RPC_PASS), timeout=8)
        r.raise_for_status()
        data = r.json()
        return None if data.get("error") else data.get("result")
    except Exception:
        return None


def load_stats() -> dict:
    try:
        if STATS_PATH.exists():
            value = json.loads(STATS_PATH.read_text())
            return value if isinstance(value, dict) else {}
    except Exception:
        pass
    return {}


def read_tail_lines(path: Path, n: int = 100):
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell(); data = b""; chunk = 8192
            while size > 0 and data.count(b"\n") <= n:
                step = min(chunk, size); size -= step; f.seek(size); data = f.read(step) + data
        return data.decode(errors="replace").splitlines()[-n:]
    except Exception:
        return []


def load_events(limit: int = 120):
    rows = []
    for raw in read_tail_lines(EVENTS_PATH, limit):
        raw = raw.strip()
        if not raw: continue
        try:
            ev = json.loads(raw); rows.append({"ts":ev.get("ts",""),"level":ev.get("level","INFO"),"msg":ev.get("msg",raw)})
        except Exception:
            rows.append({"ts":"","level":"INFO","msg":raw})
    for raw in read_tail_lines(STRATUM_LOG, limit):
        raw = raw.strip()
        if not raw: continue
        m = re.match(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\d]*)\s+\[(\w+)\]\s+(.*)$", raw)
        rows.append({"ts":m.group(1),"level":m.group(2),"msg":m.group(3)} if m else {"ts":"","level":"INFO","msg":raw})
    rows.sort(key=lambda x: x.get("ts") or "")
    return rows[-limit:]


def parse_ts(value):
    if not value: return None
    try: return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception: return None


def estimate_hashrate(stats: dict, fallback_diff: float):
    now = time.time(); samples = []
    for share in stats.get("recent_shares") or []:
        if not share.get("ok", True): continue
        ts = parse_ts(share.get("ts"))
        if ts is None or now - ts > HR_WINDOW_SEC: continue
        diff = float(share.get("pool_diff") or share.get("credited_diff") or fallback_diff or 0)
        if diff > 0: samples.append((ts, diff))
    if len(samples) < 2: return None
    first = min(t for t, _ in samples)
    elapsed = max(now - first, 1.0)
    return sum(d for _, d in samples) * (2 ** 32) / elapsed


def fmt_hashrate(value):
    if value is None: return "–"
    units = ["H/s","kH/s","MH/s","GH/s","TH/s","PH/s"]; value=float(value); i=0
    while value >= 1000 and i < len(units)-1: value /= 1000; i += 1
    return f"{value:.2f} {units[i]}"


def fmt_diff(value):
    if value is None: return "–"
    try: value=float(value)
    except Exception: return "–"
    if value >= 1e9: return f"{value/1e9:.2f} G"
    if value >= 1e6: return f"{value/1e6:.2f} M"
    if value >= 1e3: return f"{value/1e3:.2f} k"
    return f"{value:.2f}"


def fmt_fch(value):
    try: return f"{float(value or 0):.8f}".rstrip("0").rstrip(".") or "0"
    except Exception: return "0"


def fmt_duration(seconds):
    if seconds is None: return "–"
    seconds=max(0,int(seconds))
    if seconds < 60: return f"{seconds}s"
    if seconds < 3600: return f"{seconds//60}m {seconds%60}s"
    if seconds < 86400: return f"{seconds//3600}h {(seconds%3600)//60}m"
    return f"{seconds//86400}d {(seconds%86400)//3600}h"


def wallet_balances():
    out={"confirmed":0.0,"unconfirmed":0.0,"immature":0.0,"pending":0.0}
    balances=rpc("getbalances")
    if isinstance(balances,dict) and isinstance(balances.get("mine"),dict):
        mine=balances["mine"]; out["confirmed"]=float(mine.get("trusted") or 0); out["immature"]=float(mine.get("immature") or 0); out["pending"]=float(mine.get("untrusted_pending") or 0); out["unconfirmed"]=out["immature"]+out["pending"]; return out
    balance=rpc("getbalance")
    if balance is not None: out["confirmed"]=float(balance)
    wallet=rpc("getwalletinfo")
    if isinstance(wallet,dict): out["immature"]=float(wallet.get("immature_balance") or 0); out["pending"]=float(wallet.get("unconfirmed_balance") or 0); out["unconfirmed"]=out["immature"]+out["pending"]
    return out


def holding_address():
    return str((load_cfg().get("pool") or {}).get("payout_address") or "")


def validate_holding(address):
    if not address or not address.startswith("F"): return False,"keine F… Adresse"
    if re.search(r"CHANGE|xxxxxxxx",address,re.I): return False,"Platzhalter"
    result=rpc("validateaddress",[address])
    if result is None: return True,"Format ok · RPC nicht verfügbar"
    return (True,"valid") if result.get("isvalid") else (False,"ungültig laut Node")


def maturity_rows(height, blocks_log):
    rows=[]
    for block in blocks_log or []:
        bh=int(block.get("height") or 0); mature_at=int(block.get("mature_at_height") or bh+COINBASE_MATURITY); left=max(0,mature_at-height)
        rows.append({"height":bh,"hash":str(block.get("hash") or "")[:16],"reward":float(block.get("reward") or 0),"ts":block.get("ts"),"mature_at":mature_at,"confs":min(COINBASE_MATURITY,max(0,height-bh)),"left":left,"spendable":left==0})
    return rows


def network_interval(height):
    if height < 2: return DEFAULT_BLOCK_INTERVAL
    timestamps=[]
    for h in range(max(1,height-11),height+1):
        bh=rpc("getblockhash",[h]); block=rpc("getblock",[bh,1]) if bh else None
        if isinstance(block,dict) and block.get("time"): timestamps.append(int(block["time"]))
    deltas=[b-a for a,b in zip(timestamps,timestamps[1:]) if 5 <= b-a <= 3600]
    if not deltas: return DEFAULT_BLOCK_INTERVAL
    deltas.sort(); return float(deltas[len(deltas)//2])


def build_payload():
    info=rpc("getblockchaininfo") or {}; net=rpc("getnetworkinfo") or {}; height=int(info.get("blocks") or 0); difficulty=float(info.get("difficulty") or 0); stats=load_stats(); balances=wallet_balances()
    share_diff=float(stats.get("last_share_diff") or POOL_CFG.get("start_difficulty") or 10000); hashrate=estimate_hashrate(stats,share_diff); net_diff=float(stats.get("network_diff") or difficulty or 1)
    best=float(stats.get("best_share_diff") or stats.get("round_best") or 0); last_work=float(stats.get("last_share_work") or 0); effort=float(stats.get("round_effort_pct") or 0)
    best_pct=100*best/net_diff if net_diff and best else 0; last_pct=100*last_work/net_diff if net_diff and last_work else 0; eta=net_diff*(2**32)/hashrate if hashrate and hashrate>0 else None
    address=holding_address(); addr_ok,addr_msg=validate_holding(address); job_height=int(stats.get("job_height") or stats.get("round_height") or height)
    tip_changed=parse_ts(stats.get("tip_changed_at")); tip_age=max(0,int(time.time()-tip_changed)) if tip_changed else None; interval=network_interval(height); network_eta=max(0,int(interval-tip_age)) if tip_age is not None else None
    total=int(stats.get("shares_ok") or 0)+int(stats.get("shares_bad") or 0); reject=100*int(stats.get("shares_bad") or 0)/max(1,total)
    return {"synced":not info.get("initialblockdownload",True) and height==int(info.get("headers") or height),"height":height,"headers":info.get("headers"),"difficulty_fmt":fmt_diff(net_diff),"hashrate_fmt":fmt_hashrate(hashrate),"connections":net.get("connections",0),"unconfirmed_fmt":fmt_fch(balances["unconfirmed"]),"confirmed_fmt":fmt_fch(balances["confirmed"]),"blocks_found":int(stats.get("blocks_found") or 0),"rewards_fmt":f"{float(stats.get('block_rewards_total') or 0):.4f}","maturity_blocks":COINBASE_MATURITY,"shares_ok":int(stats.get("shares_ok") or 0),"shares_bad":int(stats.get("shares_bad") or 0),"reject_pct":round(reject,1),"share_diff_fmt":fmt_diff(share_diff),"last_share_time":stats.get("last_share_time"),"last_share_hash":stats.get("last_share_hash"),"best_share_fmt":fmt_diff(best),"best_pct":round(best_pct,3),"effort_pct":round(effort,3),"last_share_work_fmt":fmt_diff(last_work),"last_pct":round(last_pct,3),"eta_fmt":fmt_duration(eta),"workers":stats.get("workers") or {},"started_at":stats.get("started_at"),"payout":address,"addr_ok":addr_ok,"addr_msg":addr_msg,"job_id":stats.get("job_id") or "–","job_height":job_height,"job_prevhash":stats.get("job_prevhash") or "–","job_nbits":stats.get("job_nbits") or "–","job_ntime":stats.get("job_ntime") or "–","job_version":stats.get("job_version") or "–","tip_age":tip_age,"network_interval":round(interval),"network_eta":network_eta,"recent_shares":list(reversed(stats.get("recent_shares") or []))[:25],"blocks_log":list(reversed(maturity_rows(height,stats.get("blocks_log") or [])))[:10],"ts":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}


@app.route("/")
def index(): return render_template("dashboard.html",**build_payload())

@app.route("/api/status")
def api_status(): return jsonify(build_payload())

@app.route("/api/logs")
def api_logs():
    stats=load_stats(); info=rpc("getblockchaininfo") or {}
    return jsonify({"events":load_events(120),"snapshot":{"height":info.get("blocks"),"shares_ok":stats.get("shares_ok",0),"shares_bad":stats.get("shares_bad",0),"blocks_found":stats.get("blocks_found",0),"round_effort_pct":stats.get("round_effort_pct",0),"round_shares":stats.get("round_shares",0),"best_share_diff":stats.get("best_share_diff",0),"last_share_work":stats.get("last_share_work")},"ts":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")})

@app.route("/health")
def health():
    info=rpc("getblockchaininfo"); return jsonify({"status":"ok" if info else "error","height":(info or {}).get("blocks")}),200 if info else 503

if __name__ == "__main__":
    host=cfg.get("monitor",{}).get("host","0.0.0.0"); port=int(cfg.get("monitor",{}).get("port",5050)); app.run(host=host,port=5050 if port in (5000,5001) else port,debug=False)
