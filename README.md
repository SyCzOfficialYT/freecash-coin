# freecash-coin

**FreeCash (FCH) Solo-Mining Stack** für NerdQaxe++ / SHA-256 ASICs.

Eigene Node + lokaler Stratum → **jeder Share und jeder Block gehört dir**.

> **Nicht** BCH2 / Bitcoin Cash II. Das ist **FreeCash** (freecash.org / freecashorg/freecash).

---

## Architektur

```
NerdQaxe++  →  stratum+tcp://DEINE_IP:3333
                    ↓
              stratum/server.py   (getblocktemplate → Jobs → Shares → submitblock)
                    ↓
              freecashd           (Full Node, RPC 8332)
                    ↓
              monitor/app.py      (Dashboard :5000)
```

---

## Voraussetzungen

- Linux (NAS / VPS / PC)
- FreeCash Full Node: https://github.com/freecashorg/freecash/releases  
  (Windows-Zip, Mac-DMG oder Linux-Docker-Image)
- Python 3.10+
- NerdQaxe++ (oder anderer SHA-256 ASIC)

---

## 1. freecashd einrichten

```bash
mkdir -p ~/.freecash
# oder: scripts/make-node-conf.sh ausführen
```

`~/.freecash/freecash.conf` (Passwort = wie in `config/config.yaml`):

```ini
server=1
daemon=1
listen=1
port=8333
rpcport=8332
rpcuser=fchrpc
rpcpassword=CTSTnIiXEv9blO04eRKv8je8EUiMyL9M
rpcallowip=127.0.0.1
txindex=1
```

```bash
freecashd -daemon
freecash-cli getblockchaininfo   # warten bis synced
freecash-cli getnewaddress       # F… Adresse → in config.yaml eintragen
```

Docker-Alternative: Release-Assets von freecashorg (`Freecash_*-linux-docker`).

---

## 2. Dieses Repo

```bash
git clone https://github.com/SyCzOfficialYT/freecash-coin.git
cd freecash-coin
git pull

# config.yaml ist vorkonfiguriert – NUR payout_address auf deine F… Adresse setzen
nano config/config.yaml

pip install -r requirements.txt
chmod +x scripts/start.sh scripts/make-node-conf.sh
./scripts/start.sh
```

- **Stratum:** Port `3333`
- **Dashboard:** `http://DEINE_IP:5000`

---

## 3. NerdQaxe++

| Feld | Wert |
|------|------|
| URL | `stratum+tcp://DEINE_IP:3333` |
| Username | `FDeineAdresse.nerdq1` |
| Password | `x` oder `d=256` |

Username = **FreeCash-Adresse** (beginnt mit `F`) + optional `.worker`.

---

## Ports

| Dienst | Port |
|--------|------|
| FreeCash P2P | 8333 |
| FreeCash RPC | 8332 (nur lokal) |
| Stratum | 3333 |
| Dashboard | 5000 |

---

## Herkunft des Stratum-Codes

Share-Logik und NerdQaxe-Kompatibilität (prevhash word-order, version-rolling) stammen aus dem getesteten Solo-Stack und sind auf **FreeCash / freecashd** umgestellt.
