# freecash-coin

**Runnable Solo-Mining Stack** – portiert aus dem funktionierenden [fch-node](https://github.com/SyCzOfficialYT/fch-node) (Branch `Test`).

Dein NerdQaxe++ bekommt Shares. Lokaler Stratum + Mining-Dutch-Style Dashboard.

> Aktuell auf **BCH2 (Bitcoin Cash II)** ausgelegt – exakt der Code, der bei dir Shares liefert.  
> FreeCash (FCH) kann später mit denselben Dateien umgestellt werden (RPC/Ports/Adresse/Coinbase-Tag).

---

## Architektur

```
NerdQaxe++  →  stratum+tcp://DEINE_IP:3333
                    ↓
              stratum/server.py   (GBT → Jobs → Share-Validierung → submitblock)
                    ↓
              bitcoincashIId      (Full Node, RPC 8342)
                    ↓
              monitor/app.py      (Dashboard :5000)
```

---

## Schnellstart (ohne Docker)

### 1. Node

Binary von: https://github.com/BitcoincashII/bitcoincashII-core/releases

```bash
mkdir -p ~/.bitcoincashII
cat > ~/.bitcoincashII/bitcoincashII.conf << 'EOF'
server=1
daemon=1
listen=1
port=8339
rpcport=8342
rpcuser=bch2rpc
rpcpassword=HIER_STARKES_PASSWORT
rpcallowip=127.0.0.1
txindex=1
EOF

bitcoincashIId -daemon
bitcoincashII-cli getblockchaininfo   # warten bis initialblockdownload=false
bitcoincashII-cli createwallet "mining"
bitcoincashII-cli getnewaddress
```

### 2. Dieses Repo

```bash
git clone https://github.com/SyCzOfficialYT/freecash-coin.git
cd freecash-coin
cp config/config.example.yaml config/config.yaml
# RPC-Passwort + ggf. payout_address anpassen
nano config/config.yaml

pip install -r requirements.txt
chmod +x scripts/start.sh
./scripts/start.sh
```

- **Stratum:** Port `3333`
- **Dashboard:** `http://DEINE_IP:5000`

### 3. NerdQaxe++

| Feld | Wert |
|------|------|
| URL | `stratum+tcp://DEINE_IP:3333` |
| Username | `bitcoincashii:DEINE_ADRESSE.nerdq1` |
| Password | `x` oder `d=256` |

---

## Portainer / Docker

Siehe `docs/PORTAINER.md`.  
Node läuft typischerweise **auf dem Host** (Sync + Wallet); Stratum + Dashboard als Container mit `network_mode: host`.

---

## Wichtige Dateien

| Pfad | Rolle |
|------|--------|
| `stratum/server.py` | Produktions-Stratum (NerdQaxe prevhash, version-rolling, d=) |
| `stratum/asic_compat.py` | ESP-Miner Header-Hilfen (optional) |
| `monitor/` | Flask Dashboard (Mining-Dutch Layout) |
| `config/config.example.yaml` | Vorlage – Kopie nach `config.yaml` |
| `scripts/start.sh` | Startet Stratum + Dashboard |
| `data/stats.json` | Share-Stats (wird vom Stratum geschrieben) |

---

## Ports

| Dienst | Port |
|--------|------|
| BCH2 P2P | 8339 |
| BCH2 RPC | 8342 (nur lokal) |
| Stratum | 3333 |
| Dashboard | 5000 |

---

## Herkunft

Übernommen und bereinigt aus **SyCzOfficialYT/fch-node** (funktionierender Share-Stack für NerdQaxe++).
