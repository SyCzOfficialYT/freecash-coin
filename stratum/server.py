#!/usr/bin/env python3
"""FreeCash Solo Stratum – soft VarDiff + grace window (no lowdiff storm)"""
import socket, threading, json, time, struct, hashlib, logging, binascii, os, sys
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
START_DIFF = int(cfg["pool"].get("start_difficulty", 5000))
JOB_INTERVAL = int(cfg["pool"].get("job_interval", 20))
VARDIFF = bool(cfg["pool"].get("vardiff", True))
TARGET_SHARE_SEC = float(cfg["pool"].get("vardiff_target_sec", 10))
MIN_DIFF = int(cfg["pool"].get("vardiff_min", 1000))
MAX_DIFF = int(cfg["pool"].get("vardiff_max", 50_000_000))
# After set_difficulty, still accept old diff for this many seconds (ASIC lag)
DIFF_GRACE_SEC = float(cfg["pool"].get("vardiff_grace_sec", 45))
STATS_PATH = ROOT / "data" / "stats.json"
EVENTS_PATH = ROOT / "data" / "events.jsonl"
LOCK_PATH = ROOT / "data" / "stratum.lock"
STATS_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fch-stratum")
_stats_lock = threading.Lock()
_event_lock = threading.Lock()
_clients_lock = threading.Lock()
_clients = []
_stats = {
    "shares_ok": 0, "shares_bad": 0, "blocks_found": 0, "best_share_diff": 0,
    "block_rewards_total": 0.0, "workers": {}, "last_share_time": None,
    "last_share_diff": None, "last_share_hash": None, "last_share_work": None,
    "recent_shares": [], "blocks_log": [],
    "round_height": 0, "round_shares": 0, "round_work": 0.0, "round_best": 0.0,
    "round_effort_pct": 0.0, "network_diff": 0.0,
    "started_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
}

def emit(level, msg):
    line = {"ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), "level": level, "msg": msg}
    try:
        with _event_lock:
            with open(EVENTS_PATH, "a") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            if EVENTS_PATH.exists() and EVENTS_PATH.stat().st_size > 2_000_000:
                rows = EVENTS_PATH.read_text().splitlines()[-500:]
                EVENTS_PATH.write_text("\n".join(rows) + "\n")
    except Exception:
        pass
    if level == "ERROR":
        log.error("%s", msg)
    elif level == "WARN":
        log.warning("%s", msg)
    else:
        log.info("%s", msg)

def _acquire_singleton():
    """Prevent multiple stratum processes (causes chaos + lowdiff)."""
    import fcntl
    fp = open(LOCK_PATH, "w")
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[stratum] already running – exit", file=sys.stderr)
        sys.exit(0)
    fp.write(str(os.getpid()))
    fp.flush()
    return fp  # keep open

def _load_stats():
    global _stats
    try:
        if STATS_PATH.exists():
            for k, v in json.loads(STATS_PATH.read_text()).items():
                _stats[k] = v
    except Exception:
        pass

def _save_stats():
    try:
        with _stats_lock:
            STATS_PATH.write_text(json.dumps(_stats, indent=2))
    except Exception as e:
        log.warning("stats: %s", e)

def _bump_worker(name, ok=True):
    with _stats_lock:
        w = _stats["workers"].setdefault(name, {"ok": 0, "bad": 0})
        if ok:
            w["ok"] = w.get("ok", 0) + 1
            _stats["shares_ok"] = _stats.get("shares_ok", 0) + 1
        else:
            w["bad"] = w.get("bad", 0) + 1
            _stats["shares_bad"] = _stats.get("shares_bad", 0) + 1

def _reset_round(height, net_diff):
    with _stats_lock:
        _stats["round_height"] = height
        _stats["round_shares"] = 0
        _stats["round_work"] = 0.0
        _stats["round_best"] = 0.0
        _stats["round_effort_pct"] = 0.0
        _stats["network_diff"] = net_diff
        _stats["best_share_diff"] = 0

def _add_round_share(pool_diff, share_work, net_diff, height):
    with _stats_lock:
        if _stats.get("round_height") != height:
            _stats["round_height"] = height
            _stats["round_shares"] = 0
            _stats["round_work"] = 0.0
            _stats["round_best"] = 0.0
        _stats["round_shares"] = _stats.get("round_shares", 0) + 1
        _stats["round_work"] = float(_stats.get("round_work") or 0) + float(pool_diff)
        if share_work > float(_stats.get("round_best") or 0):
            _stats["round_best"] = share_work
        if share_work > float(_stats.get("best_share_diff") or 0):
            _stats["best_share_diff"] = share_work
        nd = net_diff or _stats.get("network_diff") or 1.0
        _stats["network_diff"] = nd
        _stats["round_effort_pct"] = min(100.0, 100.0 * float(_stats["round_work"]) / float(nd))

def _record_share(worker, share_work, pool_diff, net_diff, hhex, height, accepted=True):
    pct = (100.0 * share_work / net_diff) if net_diff else 0.0
    entry = {
        "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "worker": worker, "work": share_work, "pool_diff": pool_diff,
        "net_diff": net_diff, "pct": round(pct, 4), "hash": hhex[:16],
        "height": height, "ok": accepted,
    }
    with _stats_lock:
        rs = _stats.setdefault("recent_shares", [])
        rs.append(entry)
        _stats["recent_shares"] = rs[-50:]
        _stats["last_share_work"] = share_work

def rpc(method, params=None):
    try:
        r = requests.post(
            f"http://{RPC_HOST}:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "s", "method": method, "params": params or []},
            auth=HTTPBasicAuth(RPC_USER, RPC_PASS), timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            log.error("RPC %s: %s", method, data["error"])
            return None
        return data.get("result")
    except Exception as e:
        log.error("RPC %s: %s", method, e)
        return None

def sha256d(b):
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()

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
    if len(h) != 64:
        return binascii.hexlify(binascii.unhexlify(h)[::-1]).decode()
    return "".join(h[i:i+8] for i in range(56, -1, -8))

def address_to_scriptpubkey(addr):
    info = rpc("validateaddress", [addr])
    if info and info.get("isvalid") and info.get("scriptPubKey"):
        return binascii.unhexlify(info["scriptPubKey"])
    info2 = rpc("getaddressinfo", [addr])
    if info2 and info2.get("scriptPubKey"):
        return binascii.unhexlify(info2["scriptPubKey"])
    if _base58 is None:
        raise ValueError("base58 needed")
    raw = _base58.b58decode_check(addr)
    if len(raw) != 21:
        raise ValueError("bad address")
    return b"\x76\xa9\x14" + raw[1:] + b"\x88\xac"

def bip34_height(height):
    if height == 0: return b"\x00"
    h, b = height, b""
    while h > 0:
        b += bytes([h & 0xFF]); h >>= 8
    return bytes([len(b)]) + b

def build_coinbase_parts(height, value_sats, script_pubkey, en1_size=4, en2_size=4):
    tag = b"/FCH-Solo/"
    height_script = bip34_height(height)
    scriptsig_len = len(height_script) + en1_size + en2_size + len(tag)
    part1 = struct.pack("<I", 2) + b"\x01" + b"\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)
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
        layer = [sha256d(layer[i] + layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0]


class JobStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}
        self.by_height = {}
        self.current_id = None
        self.last_prevhash = None
        self.last_height = None
        self.script_pubkey = None
        self.network_diff = 0.0

    def ensure_spk(self):
        if self.script_pubkey is None:
            self.script_pubkey = address_to_scriptpubkey(PAYOUT_ADDRESS)
            emit("INFO", f"scriptPubKey ready for {PAYOUT_ADDRESS}")

    def refresh(self):
        self.ensure_spk()
        tmpl = rpc("getblocktemplate", [{"rules": []}]) or rpc("getblocktemplate", [])
        if not tmpl:
            emit("WARN", "getblocktemplate failed")
            return None, False
        height = tmpl["height"]
        prevhash = tmpl["previousblockhash"]
        nbits = tmpl["bits"]
        nbits_s = nbits if isinstance(nbits, str) else f"{nbits:08x}"
        other_tx = [binascii.unhexlify(tx["txid"])[::-1] for tx in tmpl.get("transactions", [])]
        net_diff = target_to_difficulty(bits_to_target(nbits))
        with self.lock:
            self.network_diff = net_diff
            if (self.current_id and self.last_height == height and self.last_prevhash == prevhash
                    and self.current_id in self.jobs):
                job = self.jobs[self.current_id]
                job["ntime"] = tmpl["curtime"]
                job["template"] = tmpl
                job["value"] = tmpl["coinbasevalue"]
                job["other_tx"] = other_tx
                job["net_diff"] = net_diff
                return job, False
            job_id = f"{height:x}-{int(time.time()) & 0xFFFFFF:x}"
            job = {
                "id": job_id, "height": height, "value": tmpl["coinbasevalue"],
                "prevhash": prevhash, "version": tmpl["version"], "nbits": nbits_s,
                "ntime": tmpl["curtime"], "target": bits_to_target(nbits),
                "net_diff": net_diff, "template": tmpl, "spk": self.script_pubkey,
                "other_tx": other_tx, "created": time.time(),
            }
            self.jobs[job_id] = job
            self.by_height[height] = job_id
            self.current_id = job_id
            prev_h = self.last_height
            self.last_height = height
            self.last_prevhash = prevhash
            cutoff = time.time() - 600
            keep = set(sorted(self.by_height.keys())[-8:])
            for jid, j in list(self.jobs.items()):
                if j["height"] not in keep and j.get("created", 0) < cutoff:
                    self.jobs.pop(jid, None)
            if prev_h != height:
                _reset_round(height, net_diff)
                emit("INFO", f"NEW ROUND height={height} netdiff={net_diff:.0f}")
            emit("INFO", f"Job {job_id} height={height} value={job['value']/1e8:.8f} FCH")
            return job, True

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)


store = JobStore()


def broadcast_job(clean=True):
    with _clients_lock:
        clients = [c for c in _clients if c.running]
    for c in clients:
        try:
            c.push_job(clean=clean, force_refresh=False)
        except Exception as e:
            emit("WARN", f"push {c.worker}: {e}")


class Client(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__(daemon=True)
        self.conn, self.addr = conn, addr
        self.worker = "?"
        self.diff = max(START_DIFF, MIN_DIFF)
        self.diff_prev = self.diff
        self.diff_changed_at = 0.0
        self.diff_from_password = False
        self.en1, self.en2_size = os.urandom(4), 4
        self.running = True
        self.shares_ok = self.shares_bad = 0
        self.vardiff_buf = []
        self.shares_since_retarget = 0

    def send(self, obj):
        try:
            self.conn.sendall((json.dumps(obj) + "\n").encode())
        except Exception:
            self.running = False

    def effective_min_diff(self):
        """During grace, accept the lower of old/new so in-flight shares pass."""
        if time.time() - self.diff_changed_at < DIFF_GRACE_SEC:
            return min(self.diff, self.diff_prev)
        return self.diff

    def set_diff(self, d, reason=""):
        d = int(max(MIN_DIFF, min(MAX_DIFF, d)))
        if d == self.diff:
            return
        self.diff_prev = self.diff
        self.diff = d
        self.diff_changed_at = time.time()
        self.shares_since_retarget = 0
        self.send({"id": None, "method": "mining.set_difficulty", "params": [self.diff]})
        emit("INFO", f"VARDIFF {self.worker} {self.diff_prev}→{self.diff} {reason} (grace {DIFF_GRACE_SEC:.0f}s)")

    def retarget_vardiff(self):
        if not VARDIFF or self.diff_from_password:
            return
        now = time.time()
        # don't retarget during grace or with too few shares at current diff
        if now - self.diff_changed_at < DIFF_GRACE_SEC:
            return
        self.shares_since_retarget += 1
        if self.shares_since_retarget < 5:
            return
        self.vardiff_buf = [t for t in self.vardiff_buf if now - t < 90]
        self.vardiff_buf.append(now)
        if len(self.vardiff_buf) < 5:
            return
        window = now - self.vardiff_buf[0]
        if window < 15:
            return
        rate = (len(self.vardiff_buf) - 1) / window
        target_rate = 1.0 / TARGET_SHARE_SEC
        if rate <= 0:
            return
        factor = rate / target_rate
        # soft steps only ±30%
        factor = max(0.7, min(1.3, factor))
        if 0.9 <= factor <= 1.1:
            return  # close enough
        new_d = int(self.diff * factor)
        if new_d >= 1_000_000:
            new_d = int(round(new_d / 50000) * 50000)
        elif new_d >= 10000:
            new_d = int(round(new_d / 1000) * 1000)
        elif new_d >= 1000:
            new_d = int(round(new_d / 100) * 100)
        self.set_diff(new_d, f"rate={rate:.3f}/s want={target_rate:.3f}/s")

    def handle_subscribe(self, mid, params):
        en1_hex = binascii.hexlify(self.en1).decode()
        self.send({
            "id": mid,
            "result": [[["mining.notify", en1_hex], ["mining.set_difficulty", en1_hex]], en1_hex, self.en2_size],
            "error": None,
        })

    def handle_authorize(self, mid, params):
        self.worker = params[0] if params else "?"
        password = params[1] if len(params) > 1 else ""
        if isinstance(password, str) and password.lower().startswith("d="):
            try:
                d = float(password[2:].strip())
                if 16 <= d <= 10_000_000:
                    self.diff = max(MIN_DIFF, int(round(d)))
                    self.diff_prev = self.diff
                    self.diff_from_password = True
            except Exception:
                pass
        self.send({"id": mid, "result": True, "error": None})
        self.send({"id": None, "method": "mining.set_difficulty", "params": [self.diff]})
        self.diff_changed_at = time.time()
        emit("INFO", f"authorize {self.worker} diff={self.diff} vardiff={VARDIFF and not self.diff_from_password}")
        self.push_job(clean=True, force_refresh=True)

    def handle_suggest_difficulty(self, mid, params):
        # Ignore – prevents ASIC from forcing 1000
        self.send({"id": mid, "result": True, "error": None})

    def push_job(self, clean=True, force_refresh=False):
        if force_refresh:
            job, clean_flag = store.refresh()
            if job is None: return
            clean = clean_flag if clean_flag else clean
        else:
            with store.lock:
                jid = store.current_id
            job = store.get(jid) if jid else None
            if job is None:
                job, clean_flag = store.refresh()
                if job is None: return
                clean = clean_flag
        coinb1, coinb2 = build_coinbase_parts(job["height"], job["value"], job["spk"], len(self.en1), self.en2_size)
        branches, hashes = [], job["other_tx"][:]
        while hashes:
            branches.append(binascii.hexlify(hashes[0][::-1]).decode())
            rest = hashes[1:]
            if not rest: break
            if len(rest) % 2: rest = rest + [rest[-1]]
            hashes = [sha256d(rest[i] + rest[i + 1]) for i in range(0, len(rest), 2)]
        nb = job["nbits"] if len(job["nbits"]) == 8 else f"{int(job['nbits'], 16):08x}"
        self.send({
            "id": None, "method": "mining.notify",
            "params": [job["id"], stratum_prevhash(job["prevhash"]), coinb1, coinb2, branches,
                       f"{job['version']:08x}", nb, f"{job['ntime']:08x}", clean],
        })

    def handle_submit(self, mid, params):
        if len(params) < 5:
            self.send({"id": mid, "result": False, "error": [20, "bad params", None]})
            _bump_worker(self.worker, False); _save_stats(); return
        _, job_id, en2_hex, ntime_hex, nonce_hex = params[:5]
        version_hex = params[5] if len(params) >= 6 else None
        job = store.get(job_id)
        if not job:
            self.send({"id": mid, "result": False, "error": [21, "stale job", None]})
            self.shares_bad += 1; _bump_worker(self.worker, False); _save_stats()
            return
        try:
            en2 = binascii.unhexlify(en2_hex)
            if len(en2) != self.en2_size:
                en2 = (en2 + b"\x00" * self.en2_size)[: self.en2_size]
            ntime, nonce = int(ntime_hex, 16), int(nonce_hex, 16)
            VERSION_MASK = 0x1FFFE000
            if version_hex:
                sv = int(version_hex, 16)
                version = sv if sv >= 0x20000000 else (int(job["version"]) & ~VERSION_MASK) | (sv & VERSION_MASK)
            else:
                version = int(job["version"])
        except Exception:
            self.send({"id": mid, "result": False, "error": [20, "bad hex", None]})
            _bump_worker(self.worker, False); _save_stats(); return

        coinb1, coinb2 = build_coinbase_parts(job["height"], job["value"], job["spk"], len(self.en1), self.en2_size)
        coinbase_tx = assemble_coinbase(coinb1, self.en1, en2, coinb2)
        merkle = full_merkle_root(sha256d(coinbase_tx), job["other_tx"])
        header = struct.pack("<I", version) + binascii.unhexlify(job["prevhash"])[::-1] + merkle
        header += struct.pack("<I", ntime) + struct.pack("<I", int(job["nbits"], 16)) + struct.pack("<I", nonce)
        h = sha256d(header)
        h_int = int.from_bytes(h[::-1], "big")
        share_work = target_to_difficulty(h_int)
        net_diff = job.get("net_diff") or store.network_diff or 1.0
        hhex = h[::-1].hex()

        need = self.effective_min_diff()
        if h_int > difficulty_to_target(need):
            self.send({"id": mid, "result": False, "error": [23, "low difficulty", None]})
            self.shares_bad += 1; _bump_worker(self.worker, False); _save_stats()
            return

        # credit at the difficulty the share actually met (capped by current target band)
        credited = min(self.diff, max(need, min(share_work, self.diff)))
        if share_work >= self.diff:
            credited = self.diff
        elif share_work >= self.diff_prev and time.time() - self.diff_changed_at < DIFF_GRACE_SEC:
            credited = self.diff_prev
        else:
            credited = need

        self.send({"id": mid, "result": True, "error": None})
        self.shares_ok += 1
        pct = 100.0 * share_work / net_diff if net_diff else 0
        with _stats_lock:
            _stats["last_share_time"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            _stats["last_share_diff"] = credited
            _stats["last_share_hash"] = hhex[:16]
            _stats["last_share_work"] = share_work
        _add_round_share(credited, share_work, net_diff, job["height"])
        _record_share(self.worker, share_work, credited, net_diff, hhex, job["height"], True)
        _bump_worker(self.worker, True)
        _save_stats()
        with _stats_lock:
            effort = _stats.get("round_effort_pct", 0)
        emit("OK", f"ACCEPT #{self.shares_ok} work={share_work:.0f} ({pct:.3f}%) "
             f"pool={credited} round={effort:.2f}% hash={hhex[:16]}")
        self.vardiff_buf.append(time.time())
        self.retarget_vardiff()

        if h_int <= job["target"]:
            emit("WARN", f"*** BLOCK CANDIDATE *** height={job['height']} hash={hhex}")
            tx_count = 1 + len(job["template"].get("transactions", []))
            block = header + encode_varint(tx_count) + coinbase_tx
            for tx in job["template"].get("transactions", []):
                block += binascii.unhexlify(tx["data"])
            res = rpc("submitblock", [binascii.hexlify(block).decode()])
            if res in (None, ""):
                emit("OK", f"*** BLOCK ACCEPTED *** height={job['height']}")
                with _stats_lock:
                    _stats["blocks_found"] = _stats.get("blocks_found", 0) + 1
                    _stats["block_rewards_total"] = _stats.get("block_rewards_total", 0) + job["value"] / 1e8
                    blog = _stats.setdefault("blocks_log", [])
                    blog.append({
                        "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                        "height": job["height"], "hash": hhex,
                        "reward": job["value"] / 1e8, "address": PAYOUT_ADDRESS,
                        "mature_at_height": job["height"] + 144,
                    })
                    _stats["blocks_log"] = blog[-20:]
                _save_stats()
            else:
                emit("ERROR", f"submitblock rejected: {res}")

    def run(self):
        with _clients_lock:
            _clients.append(self)
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
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or []
                    if method == "mining.subscribe":
                        self.handle_subscribe(mid, params)
                    elif method == "mining.authorize":
                        self.handle_authorize(mid, params)
                    elif method == "mining.submit":
                        self.handle_submit(mid, params)
                    elif method == "mining.extranonce.subscribe":
                        self.send({"id": mid, "result": True, "error": None})
                    elif method == "mining.suggest_difficulty":
                        self.handle_suggest_difficulty(mid, params)
                    elif method == "mining.configure":
                        self.send({"id": mid, "result": {"version-rolling": True, "version-rolling.mask": "1fffe000", "version-rolling.min-bit-count": 16}, "error": None})
                    elif mid is not None:
                        self.send({"id": mid, "result": None, "error": [20, "unknown", None]})
        except Exception as e:
            emit("ERROR", f"client {self.addr}: {e}")
        finally:
            self.running = False
            with _clients_lock:
                if self in _clients:
                    _clients.remove(self)
            try:
                self.conn.close()
            except Exception:
                pass


def job_loop():
    while True:
        try:
            job, clean = store.refresh()
            if job is not None and clean:
                broadcast_job(clean=True)
        except Exception as e:
            emit("ERROR", f"job_loop: {e}")
        time.sleep(JOB_INTERVAL)


def stats_loop():
    while True:
        time.sleep(30)
        with _stats_lock:
            s = dict(_stats)
        emit("INFO", f"STATS h={store.last_height} ok={s.get('shares_ok')} bad={s.get('shares_bad')} "
             f"round={s.get('round_effort_pct',0):.2f}% rs={s.get('round_shares')}")


def main():
    lock_fp = _acquire_singleton()
    _load_stats(); _save_stats()
    emit("INFO", f"Stratum+VarDiff soft start_diff={max(START_DIFF,MIN_DIFF)} grace={DIFF_GRACE_SEC}s")
    emit("INFO", f"Payout {PAYOUT_ADDRESS}")
    try:
        store.ensure_spk(); store.refresh()
    except Exception as e:
        emit("ERROR", f"startup: {e}")
    threading.Thread(target=job_loop, daemon=True).start()
    threading.Thread(target=stats_loop, daemon=True).start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((STRATUM_HOST, STRATUM_PORT))
    sock.listen(16)
    emit("INFO", f"listening :{STRATUM_PORT} (single instance)")
    while True:
        conn, addr = sock.accept()
        Client(conn, addr).start()


if __name__ == "__main__":
    main()
