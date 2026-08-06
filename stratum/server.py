#!/usr/bin/env python3
"""FreeCash (FCH) Solo Stratum – NerdQaxe++ compatible."""
import socket, threading, json, time, struct, hashlib, logging, binascii, os
from pathlib import Path
from datetime import datetime
import yaml, requests
from requests.auth import HTTPBasicAuth
try:
    import base58 as _base58
except ImportError:
    _base58 = None

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
if not CONFIG_PATH.exists():
    CONFIG_PATH = ROOT / "config" / "config.example.yaml"
with open(CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

RPC_HOST, RPC_PORT = cfg["rpc"]["host"], int(cfg["rpc"]["port"])
RPC_USER, RPC_PASS = cfg["rpc"]["user"], cfg["rpc"]["password"]
PAYOUT_ADDRESS = cfg["pool"]["payout_address"]
STRATUM_HOST = cfg["pool"].get("stratum_host", "0.0.0.0")
STRATUM_PORT = int(cfg["pool"].get("stratum_port", 3333))
START_DIFF = int(cfg["pool"].get("start_difficulty", 256))
JOB_INTERVAL = int(cfg["pool"].get("job_interval", 25))
STATS_PATH = ROOT / "data" / "stats.json"
STATS_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fch-stratum")
_stats_lock = threading.Lock()
_stats = {"shares_ok": 0, "shares_bad": 0, "blocks_found": 0, "best_share_diff": 0,
          "block_rewards_total": 0.0, "workers": {}, "last_share_time": None,
          "last_share_diff": None, "last_share_hash": None,
          "started_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}

def _load_stats():
    global _stats
    try:
        if STATS_PATH.exists():
            for k, v in json.loads(STATS_PATH.read_text()).items():
                if k in _stats: _stats[k] = v
    except Exception: pass

def _save_stats():
    try:
        with _stats_lock: STATS_PATH.write_text(json.dumps(_stats, indent=2))
    except Exception as e: log.warning("stats: %s", e)

def _bump_worker(name, ok=True):
    with _stats_lock:
        w = _stats["workers"].setdefault(name, {"ok": 0, "bad": 0})
        if ok: w["ok"] = w.get("ok", 0) + 1; _stats["shares_ok"] = _stats.get("shares_ok", 0) + 1
        else: w["bad"] = w.get("bad", 0) + 1; _stats["shares_bad"] = _stats.get("shares_bad", 0) + 1

def rpc(method, params=None):
    try:
        r = requests.post(f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "s", "method": method, "params": params or []},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS), timeout=60)
        r.raise_for_status()
        data = r.json()
        if data.get("error"): log.error("RPC %s: %s", method, data["error"]); return None
        return data.get("result")
    except Exception as e:
        log.error("RPC %s: %s", method, e); return None

def sha256d(b): return hashlib.sha256(hashlib.sha256(b).digest()).digest()
def encode_varint(n):
    if n < 0xFD: return struct.pack("<B", n)
    if n <= 0xFFFF: return struct.pack("<BH", 0xFD, n)
    if n <= 0xFFFFFFFF: return struct.pack("<BI", 0xFE, n)
    return struct.pack("<BQ", 0xFF, n)
def bits_to_target(nbits):
    bits = int(nbits, 16) if isinstance(nbits, str) else int(nbits)
    exp, mant = bits >> 24, bits & 0xFFFFFF
    return mant >> (8 * (3 - exp)) if exp <= 3 else mant << (8 * (exp - 3))
def difficulty_to_target(diff):
    return int(0x00000000FFFF0000000000000000000000000000000000000000000000000000 / max(diff, 0.0001))
def target_to_difficulty(target):
    if target <= 0: return 0.0
    return 0x00000000FFFF0000000000000000000000000000000000000000000000000000 / target
def stratum_prevhash(rpc_be_hex):
    h = rpc_be_hex.lower()
    if len(h) != 64: return binascii.hexlify(binascii.unhexlify(h)[::-1]).decode()
    return "".join(h[i:i+8] for i in range(56, -1, -8))

def address_to_scriptpubkey(addr):
    info = rpc("validateaddress", [addr])
    if info and info.get("isvalid") and info.get("scriptPubKey"):
        return binascii.unhexlify(info["scriptPubKey"])
    info2 = rpc("getaddressinfo", [addr])
    if info2 and info2.get("scriptPubKey"):
        return binascii.unhexlify(info2["scriptPubKey"])
    if _base58 is None: raise ValueError("pip install base58 or use working freecashd RPC")
    raw = _base58.b58decode_check(addr)
    if len(raw) != 21: raise ValueError("bad address length")
    return b"\x76\xa9\x14" + raw[1:] + b"\x88\xac"

def bip34_height(height):
    if height == 0: return b"\x00"
    h, b = height, b""
    while h > 0: b += bytes([h & 0xFF]); h >>= 8
    return bytes([len(b)]) + b

def build_coinbase_parts(height, value_sats, script_pubkey, en1_size=4, en2_size=4):
    tag = b"/FCH-Solo/"
    height_script = bip34_height(height)
    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)
    part1 = struct.pack("<I", 2) + b"\x01" + b"\x00"*32 + struct.pack("<I", 0xFFFFFFFF)
    part1 += encode_varint(scriptsig_len) + height_script
    part2 = tag + struct.pack("<I", 0xFFFFFFFF) + b"\x01" + struct.pack("<Q", value_sats)
    part2 += encode_varint(len(script_pubkey)) + script_pubkey + struct.pack("<I", 0)
    return binascii.hexlify(part1).decode(), binascii.hexlify(part2).decode()

def assemble_coinbase(coinb1, en1, en2, coinb2):
    return binascii.unhexlify(coinb1) + en1 + en2 + binascii.unhexlify(coinb2)

def full_merkle_root(coinbase_hash_le, other_tx_le):
    layer = [coinbase_hash_le] + other_tx_le
    while len(layer) > 1:
        if len(layer) % 2: layer.append(layer[-1])
        layer = [sha256d(layer[i] + layer[i+1]) for i in range(0, len(layer), 2)]
    return layer[0]

class JobStore:
    def __init__(self):
        self.lock = threading.Lock(); self.jobs = {}; self.current_id = None; self.script_pubkey = None
    def ensure_spk(self):
        if self.script_pubkey is None:
            self.script_pubkey = address_to_scriptpubkey(PAYOUT_ADDRESS)
            log.info("scriptPubKey ready (%d bytes)", len(self.script_pubkey))
    def refresh(self):
        self.ensure_spk()
        tmpl = rpc("getblocktemplate", [{"rules": []}]) or rpc("getblocktemplate", [])
        if not tmpl: log.warning("getblocktemplate failed"); return None
        other_tx = [binascii.unhexlify(tx["txid"])[::-1] for tx in tmpl.get("transactions", [])]
        nbits = tmpl["bits"]
        job_id = f"{tmpl['height']:x}-{int(time.time()) & 0xFFFFFF:x}"
        job = {"id": job_id, "height": tmpl["height"], "value": tmpl["coinbasevalue"],
               "prevhash": tmpl["previousblockhash"], "version": tmpl["version"],
               "nbits": nbits if isinstance(nbits, str) else f"{nbits:08x}",
               "ntime": tmpl["curtime"], "target": bits_to_target(nbits),
               "template": tmpl, "spk": self.script_pubkey, "other_tx": other_tx}
        with self.lock:
            self.jobs[job_id] = job
            if len(self.jobs) > 10:
                for k in sorted(self.jobs.keys())[:-6]: self.jobs.pop(k, None)
            self.current_id = job_id
        log.info("Job %s height=%s value=%.8f FCH", job_id, job["height"], job["value"]/1e8)
        return job
    def get(self, job_id):
        with self.lock: return self.jobs.get(job_id)

store = JobStore()

class Client(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__(daemon=True)
        self.conn, self.addr = conn, addr
        self.worker, self.diff = "?", START_DIFF
        self.diff_from_password = False
        self.en1, self.en2_size = os.urandom(4), 4
        self.running, self.shares_ok, self.shares_bad = True, 0, 0
    def send(self, obj):
        try: self.conn.sendall((json.dumps(obj) + "\n").encode())
        except Exception: self.running = False
    def handle_subscribe(self, mid, params):
        en1_hex = binascii.hexlify(self.en1).decode()
        self.send({"id": mid, "result": [[["mining.notify", en1_hex], ["mining.set_difficulty", en1_hex]], en1_hex, self.en2_size], "error": None})
    def handle_authorize(self, mid, params):
        self.worker = params[0] if params else "?"
        password = params[1] if len(params) > 1 else ""
        if isinstance(password, str) and password.lower().startswith("d="):
            try:
                d = float(password[2:].strip())
                if 16 <= d <= 10_000_000: self.diff = max(16, int(round(d))); self.diff_from_password = True
            except Exception: pass
        self.send({"id": mid, "result": True, "error": None})
        self.send({"id": None, "method": "mining.set_difficulty", "params": [self.diff]})
        self.push_job(True)
    def handle_suggest_difficulty(self, mid, params):
        if not self.diff_from_password and params:
            try:
                d = float(params[0])
                if 16 <= d <= 10_000_000:
                    self.diff = max(16, int(round(d)))
                    self.send({"id": None, "method": "mining.set_difficulty", "params": [self.diff]})
            except Exception: pass
        self.send({"id": mid, "result": True, "error": None})
    def push_job(self, clean=True):
        job = store.refresh() if clean else None
        if job is None:
            with store.lock: jid = store.current_id
            job = store.get(jid) if jid else None
        if not job: return
        coinb1, coinb2 = build_coinbase_parts(job["height"], job["value"], job["spk"], len(self.en1), self.en2_size)
        branches, hashes = [], job["other_tx"][:]
        while hashes:
            branches.append(binascii.hexlify(hashes[0][::-1]).decode())
            rest = hashes[1:]
            if not rest: break
            if len(rest) % 2: rest = rest + [rest[-1]]
            hashes = [sha256d(rest[i] + rest[i+1]) for i in range(0, len(rest), 2)]
        nb = job["nbits"] if len(job["nbits"]) == 8 else f"{int(job['nbits'], 16):08x}"
        self.send({"id": None, "method": "mining.notify", "params": [
            job["id"], stratum_prevhash(job["prevhash"]), coinb1, coinb2, branches,
            f"{job['version']:08x}", nb, f"{job['ntime']:08x}", clean]})
    def handle_submit(self, mid, params):
        if len(params) < 5:
            self.send({"id": mid, "result": False, "error": [20, "bad params", None]}); _bump_worker(self.worker, False); _save_stats(); return
        _, job_id, en2_hex, ntime_hex, nonce_hex = params[:5]
        version_hex = params[5] if len(params) >= 6 else None
        job = store.get(job_id)
        if not job:
            self.send({"id": mid, "result": False, "error": [21, "stale job", None]}); _bump_worker(self.worker, False); _save_stats(); return
        try:
            en2 = binascii.unhexlify(en2_hex)
            if len(en2) != self.en2_size: en2 = (en2 + b"\x00" * self.en2_size)[:self.en2_size]
            ntime, nonce = int(ntime_hex, 16), int(nonce_hex, 16)
            VERSION_MASK = 0x1FFFE000
            if version_hex:
                sv = int(version_hex, 16)
                version = sv if sv >= 0x20000000 else (int(job["version"]) & ~VERSION_MASK) | (sv & VERSION_MASK)
            else: version = int(job["version"])
        except Exception:
            self.send({"id": mid, "result": False, "error": [20, "bad hex", None]}); _bump_worker(self.worker, False); _save_stats(); return
        coinb1, coinb2 = build_coinbase_parts(job["height"], job["value"], job["spk"], len(self.en1), self.en2_size)
        coinbase_tx = assemble_coinbase(coinb1, self.en1, en2, coinb2)
        merkle = full_merkle_root(sha256d(coinbase_tx), job["other_tx"])
        header = struct.pack("<I", version) + binascii.unhexlify(job["prevhash"])[::-1] + merkle
        header += struct.pack("<I", ntime) + struct.pack("<I", int(job["nbits"], 16)) + struct.pack("<I", nonce)
        h = sha256d(header); h_int = int.from_bytes(h[::-1], "big")
        if h_int > difficulty_to_target(self.diff):
            self.send({"id": mid, "result": False, "error": [23, "low difficulty", None]})
            self.shares_bad += 1; _bump_worker(self.worker, False); _save_stats(); return
        self.send({"id": mid, "result": True, "error": None}); self.shares_ok += 1
        with _stats_lock:
            _stats["last_share_time"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            _stats["last_share_diff"] = self.diff
            _stats["last_share_hash"] = h[::-1].hex()[:16]
            sd = target_to_difficulty(h_int)
            if sd > (_stats.get("best_share_diff") or 0): _stats["best_share_diff"] = sd
        _bump_worker(self.worker, True); _save_stats()
        log.info("ACCEPT share #%d worker=%s hash=%s", self.shares_ok, self.worker, h[::-1].hex()[:16])
        if h_int <= job["target"]:
            log.warning("*** BLOCK CANDIDATE *** height=%s", job["height"])
            tx_count = 1 + len(job["template"].get("transactions", []))
            block = header + encode_varint(tx_count) + coinbase_tx
            for tx in job["template"].get("transactions", []):
                block += binascii.unhexlify(tx["data"])
            res = rpc("submitblock", [binascii.hexlify(block).decode()])
            if res in (None, ""):
                log.warning("*** BLOCK ACCEPTED ***")
                with _stats_lock:
                    _stats["blocks_found"] = _stats.get("blocks_found", 0) + 1
                    _stats["block_rewards_total"] = _stats.get("block_rewards_total", 0) + job["value"] / 1e8
                _save_stats()
            else: log.error("submitblock: %s", res)
    def run(self):
        buf = ""
        try:
            while self.running:
                data = self.conn.recv(8192)
                if not data: break
                buf += data.decode(errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line: continue
                    try: msg = json.loads(line)
                    except json.JSONDecodeError: continue
                    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or []
                    if method == "mining.subscribe": self.handle_subscribe(mid, params)
                    elif method == "mining.authorize": self.handle_authorize(mid, params)
                    elif method == "mining.submit": self.handle_submit(mid, params)
                    elif method == "mining.extranonce.subscribe": self.send({"id": mid, "result": True, "error": None})
                    elif method == "mining.suggest_difficulty": self.handle_suggest_difficulty(mid, params)
                    elif method == "mining.configure":
                        self.send({"id": mid, "result": {"version-rolling": True, "version-rolling.mask": "1fffe000", "version-rolling.min-bit-count": 16}, "error": None})
                    elif mid is not None: self.send({"id": mid, "result": None, "error": [20, "unknown", None]})
        except Exception as e: log.error("client %s: %s", self.addr, e)
        finally:
            try: self.conn.close()
            except Exception: pass
            log.info("disconnect %s ok=%d bad=%d", self.worker, self.shares_ok, self.shares_bad)

def job_loop():
    while True:
        try: store.refresh()
        except Exception as e: log.error("job_loop: %s", e)
        time.sleep(JOB_INTERVAL)

def main():
    _load_stats(); _save_stats()
    log.info("FreeCash (FCH) Solo Stratum – NerdQaxe compatible")
    log.info("Payout : %s", PAYOUT_ADDRESS)
    log.info("Listen : %s:%s diff=%s", STRATUM_HOST, STRATUM_PORT, START_DIFF)
    if not PAYOUT_ADDRESS.startswith("F") or "CHANGE" in PAYOUT_ADDRESS:
        log.error("Set a real FreeCash F… address in config/config.yaml!")
    store.ensure_spk(); store.refresh()
    threading.Thread(target=job_loop, daemon=True).start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((STRATUM_HOST, STRATUM_PORT)); sock.listen(16)
    log.info("waiting for miners on :%s", STRATUM_PORT)
    while True:
        conn, addr = sock.accept()
        log.info("connect %s", addr)
        Client(conn, addr).start()

if __name__ == "__main__":
    main()
