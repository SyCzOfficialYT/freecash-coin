# Portainer – nur Container starten

## Voraussetzung (einmalig auf dem Host)

```bash
# freecashd mit RPC
./scripts/make-node-conf.sh   # oder manuell ~/.freecash/freecash.conf
freecashd -daemon
# warten bis synced
```

## Stack

1. Repo nach z.B. `/volume1/docker/freecash-coin` klonen
2. Portainer → Stacks → Compose aus `docker-compose.yml`
3. Deploy

**Fertig.** Der Entry-Point:

- legt `config.yaml` an falls nötig
- ruft `getnewaddress` auf und schreibt die Holding-Adresse
- startet Stratum (:3333) + Dashboard (:5000)

## ASIC

```
stratum+tcp://NAS-IP:3333
Username: <Holding-Adresse vom Dashboard>.nerdq1
Password: x
```

Dashboard: `http://NAS-IP:5000` – Holding-Adresse + Live-Terminal.
