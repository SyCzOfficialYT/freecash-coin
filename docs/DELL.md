# FreeCash Solo auf Dell / Linux-PC

Besser als Synology DS224+ für IBD (mehr CPU/RAM).

## Start

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER   # danach neu einloggen

git clone https://github.com/SyCzOfficialYT/freecash-coin.git
cd freecash-coin
docker compose -f docker-compose.dell.yml up -d --build
```

Erstes Build: FreeCash-Binary ~700 MB, 10–20 Min möglich.

## URLs

| Dienst | URL |
|--------|-----|
| Dashboard | `http://DELL-IP:5050` |
| Stratum | `stratum+tcp://DELL-IP:3333` |
| ASIC User | `<Holding vom Dashboard>.nerdq1` |
| Pass | `x` |

## Nützlich

```bash
# Logs
docker compose -f docker-compose.dell.yml logs -f

# Sync-Status
docker exec freecash-solo freecash-cli -datadir=/opt/newcoin getblockchaininfo

# Stop
docker compose -f docker-compose.dell.yml down
# Chain behalten: volumes nicht löschen
```

## Tipps Vostro 3520 (4 GB)

- Netzteil, Sleep/Hibernate aus
- SSD nutzen wenn möglich
- wenig parallele Last während IBD
- Firewall: 5050, 3333, 8333 (P2P) freigeben wenn du von außen/LAN minest
