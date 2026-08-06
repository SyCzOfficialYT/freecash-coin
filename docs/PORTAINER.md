# Portainer – nur YAML, fertig

## Warum vorher keine Node im Container war

Stratum braucht `getblocktemplate` / `submitblock` von **freecashd**.  
Ohne Node im Stack musste die Node separat laufen.  
Jetzt: **All-in-One** – freecashd + Stratum + Dashboard in **einem** Container.

## So geht’s

1. Portainer → **Stacks** → **Add stack**
2. Inhalt von [`portainer-stack.yml`](../portainer-stack.yml) einfügen
3. **Deploy**

Erstes Build lädt das offizielle FreeCash-Release (~700 MB) und kann 5–15 Min dauern.

## Danach

| Was | Wo |
|-----|-----|
| Dashboard | `http://NAS-IP:5000` |
| Holding-Adresse | oben im Dashboard (auto) |
| Stratum | `stratum+tcp://NAS-IP:3333` |
| ASIC User | `F….nerdq1` (vom Dashboard) |
| Passwort | `x` |

Sync der Chain: bis IBD fertig ist, sind Jobs/Shares eingeschränkt – Terminal zeigt den Status.

## Volumes

- `freecash-chain` → Blockchain + Wallet (nicht löschen!)
- `freecash-app` → Share-Stats / Terminal-Log
- `freecash-config` → config.yaml mit Holding-Adresse
