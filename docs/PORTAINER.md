# Portainer – Stratum + Dashboard

## Voraussetzung

`bitcoincashIId` läuft auf dem NAS/Host mit RPC auf `127.0.0.1:8342` (siehe README).

## Stack anlegen

1. Repo auf dem NAS klonen, z. B. `/volume1/docker/freecash-coin`
2. `cp config/config.example.yaml config/config.yaml` und Passwort + Adresse setzen
3. Portainer → Stacks → Add stack
4. Compose aus `docker-compose.yml` einfügen (Pfad zu Volumes anpassen falls nötig)
5. Deploy

Beide Services nutzen `network_mode: host`:

- Stratum lauscht auf Host-Port **3333**
- Dashboard auf **5000**
- RPC erreichbar unter 127.0.0.1:8342

## NerdQaxe

```
stratum+tcp://NAS-IP:3333
Username: bitcoincashii:DEINE_ADRESSE.nerdq1
Password: x   # oder d=256
```

## Logs

Portainer → Container → Logs (ACCEPT share … = funktioniert).
