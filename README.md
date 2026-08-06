# freecash-coin

**FreeCash (FCH) Solo-Mining** für NerdQaxe++ – **ein Portainer-Stack, fertig**.

Enthält:

- **freecashd** (Full Node, offizielles Release v1.0.5)
- **Stratum** (NerdQaxe-kompatibel)
- **Dashboard** (Holding-Adresse + Live-CLI-Terminal)
- Auto `getnewaddress` + Validierung

---

## Portainer (empfohlen)

Datei: **`portainer-stack.yml`** → kompletten Inhalt in Portainer Stack einfügen → Deploy.

Details: [docs/PORTAINER.md](docs/PORTAINER.md)

```
Dashboard:  http://NAS-IP:5000
Stratum:    stratum+tcp://NAS-IP:3333
Username:   <Holding vom Dashboard>.nerdq1
Password:   x
```

---

## Lokal

```bash
git clone https://github.com/SyCzOfficialYT/freecash-coin.git
cd freecash-coin
docker compose up -d --build
```

---

## Ports (host network)

| Dienst | Port |
|--------|------|
| P2P | 8333 |
| RPC | 8332 |
| Stratum | 3333 |
| Dashboard | 5000 |
