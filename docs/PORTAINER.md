# Portainer – FreeCash Solo

## Voraussetzung

`freecashd` läuft auf dem Host mit RPC `127.0.0.1:8332` und deiner `freecash.conf`.

## Stack

1. Repo klonen, `config/config.yaml` → echte **F…** Adresse setzen
2. Portainer → Stack aus `docker-compose.yml`
3. `network_mode: host` → Stratum :3333, Dashboard :5000

## NerdQaxe

```
stratum+tcp://NAS-IP:3333
Username: FDeineFreeCashAdresse.nerdq1
Password: x
```
