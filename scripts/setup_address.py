#!/usr/bin/env python3
"""
FreeCash Holding-Adresse automatisch erzeugen, prüfen und in config.yaml schreiben.

- Platzhalter / ungültige Adresse → freecash-cli getnewaddress (oder RPC)
- validateaddress prüfen
- config/config.yaml aktualisieren
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import requests
import yaml
from requests.auth import HTTPBasicAuth

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"

PLACEHOLDER_RE = re.compile(r"CHANGE|xxxxxxxx|FCHANGE", re.I)


def load_cfg():
    if not CONFIG_PATH.exists():
        print(f"FEHLER: {CONFIG_PATH} fehlt")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def save_payout(addr: str, cfg: dict):
    cfg.setdefault("pool", {})["payout_address"] = addr
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"config.yaml aktualisiert: payout_address = {addr}")


def rpc(cfg, method, params=None):
    r = cfg["rpc"]
    try:
        resp = requests.post(
            f"http://{r['host']}:{r['port']}",
            json={"jsonrpc": "1.0", "id": "setup", "method": method, "params": params or []},
            auth=HTTPBasicAuth(r["user"], r["password"]),
            timeout=30,
        )
        data = resp.json()
        if data.get("error"):
            return None, data["error"]
        return data.get("result"), None
    except Exception as e:
        return None, str(e)


def cli_getnewaddress() -> str | None:
    try:
        out = subprocess.check_output(
            ["freecash-cli", "getnewaddress"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        addr = out.strip().splitlines()[-1].strip()
        return addr if addr.startswith("F") else None
    except FileNotFoundError:
        return None
    except subprocess.CalledProcessError as e:
        # Wallet vielleicht noch nicht geladen
        err = (e.output or "") + str(e)
        if "Wallet file not specified" in err or "wallet" in err.lower():
            try:
                subprocess.check_call(["freecash-cli", "createwallet", "mining"], timeout=60)
            except Exception:
                try:
                    subprocess.check_call(["freecash-cli", "loadwallet", "mining"], timeout=30)
                except Exception:
                    pass
            try:
                out = subprocess.check_output(["freecash-cli", "getnewaddress"], text=True, timeout=60)
                addr = out.strip().splitlines()[-1].strip()
                return addr if addr.startswith("F") else None
            except Exception:
                return None
        return None
    except Exception:
        return None


def ensure_wallet_rpc(cfg):
    """Versucht createwallet/loadwallet über RPC."""
    wallets, _ = rpc(cfg, "listwallets")
    if wallets is not None and len(wallets) == 0:
        rpc(cfg, "createwallet", ["mining"])
        rpc(cfg, "loadwallet", ["mining"])


def validate(cfg, addr: str) -> tuple[bool, str]:
    if not addr or not addr.startswith("F"):
        return False, "Adresse muss mit F beginnen (FreeCash)"
    if PLACEHOLDER_RE.search(addr):
        return False, "Platzhalter-Adresse"
    info, err = rpc(cfg, "validateaddress", [addr])
    if err:
        # Offline: mind. Format prüfen
        if len(addr) >= 26:
            return True, "RPC validate nicht erreichbar – Format ok (F…)"
        return False, f"validateaddress fehlgeschlagen: {err}"
    if not info:
        return False, "validateaddress lieferte nichts"
    if not info.get("isvalid", False):
        return False, f"Node meldet ungültig: {info}"
    return True, "valid"


def main():
    cfg = load_cfg()
    current = (cfg.get("pool") or {}).get("payout_address") or ""

    ok, msg = validate(cfg, current)
    if ok and not PLACEHOLDER_RE.search(current):
        print(f"Holding-Adresse bereits gesetzt und gültig: {current}")
        print(f"  Status: {msg}")
        print("  → Dashboard zeigt diese Adresse (Coins sammeln sich hier).")
        print("  → Dieselbe Adresse zum Exchange senden / als Deposit nutzen.")
        return 0

    print(f"Aktuelle Adresse unbrauchbar ({current!r}): {msg}")
    print("Erzeuge neue Adresse…")

    ensure_wallet_rpc(cfg)
    addr = cli_getnewaddress()
    if not addr:
        result, err = rpc(cfg, "getnewaddress", [])
        if result:
            addr = result
        else:
            # manche Nodes brauchen Label
            result, err = rpc(cfg, "getnewaddress", ["holding"])
            addr = result

    if not addr:
        print("FEHLER: konnte keine Adresse erzeugen.")
        print("  Stelle sicher: freecashd läuft, Wallet existiert, RPC ok.")
        print("  Manuell: freecash-cli createwallet mining && freecash-cli getnewaddress")
        return 1

    ok, msg = validate(cfg, addr)
    if not ok:
        print(f"FEHLER: neue Adresse {addr} nicht gültig: {msg}")
        return 1

    save_payout(addr, cfg)
    print()
    print("=" * 50)
    print("HOLDING-ADRESSE (Coinbase / Wallet / Exchange)")
    print(addr)
    print("=" * 50)
    print("NerdQaxe Username:  " + addr + ".nerdq1")
    print("Dashboard zeigt diese Adresse und den Wallet-Saldo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
