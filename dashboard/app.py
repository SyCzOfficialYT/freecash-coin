#!/usr/bin/env python3
"""
FreeCash Solo Dashboard – Mining-Dutch inspired layout
Queries freecashd via JSON-RPC and presents a clean SOLO-focused UI.
"""

import os
import time
from datetime import datetime, timezone
from functools import lru_cache

import requests
from flask import Flask, render_template, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

RPC_HOST = os.getenv("RPC_HOST", "127.0.0.1")
RPC_PORT = int(os.getenv("RPC_PORT", "8332"))
RPC_USER = os.getenv("RPC_USER", "freecashrpc")
RPC_PASSWORD = os.getenv("RPC_PASSWORD", "")
FCH_ADDRESS = os.getenv("FCH_ADDRESS", "")

RPC_URL = f"http://{RPC_USER}:{RPC_PASSWORD}@{RPC_HOST}:{RPC_PORT}"


def rpc(method: str, params=None):
    payload = {
        "jsonrpc": "1.0",
        "id": "dashboard",
        "method": method,
        "params": params or [],
    }
    try:
        r = requests.post(RPC_URL, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            return None, data["error"]
        return data.get("result"), None
    except Exception as e:
        return None, str(e)


def get_node_stats():
    info, err = rpc("getblockchaininfo")
    if err or not info:
        return {"error": err or "RPC failed"}

    mining_info, _ = rpc("getmininginfo")
    network_info, _ = rpc("getnetworkinfo")
    mempool, _ = rpc("getmempoolinfo")

    # Best effort hashrate estimate (network)
    nethash = None
    try:
        nethash, _ = rpc("getnetworkhashps", [120])  # last 120 blocks
    except Exception:
        pass

    return {
        "height": info.get("blocks"),
        "headers": info.get("headers"),
        "difficulty": info.get("difficulty"),
        "chain": info.get("chain"),
        "verification_progress": info.get("verificationprogress"),
        "pruned": info.get("pruned"),
        "nethash": nethash,
        "mining": mining_info or {},
        "connections": (network_info or {}).get("connections"),
        "mempool_size": (mempool or {}).get("size"),
        "mempool_bytes": (mempool or {}).get("bytes"),
        "synced": info.get("blocks") == info.get("headers"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.route("/")
def index():
    stats = get_node_stats()
    return render_template(
        "dashboard.html",
        stats=stats,
        address=FCH_ADDRESS,
        now=datetime.now(timezone.utc),
    )


@app.route("/api/stats")
def api_stats():
    return jsonify(get_node_stats())


@app.route("/health")
def health():
    stats = get_node_stats()
    if stats.get("error"):
        return jsonify({"status": "error", "detail": stats["error"]}), 503
    return jsonify({"status": "ok", "height": stats.get("height")})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
