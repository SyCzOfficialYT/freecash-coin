# NerdQaxe++ Configuration for FreeCash Solo

The NerdQaxe++ (and NerdQaxe / NerdOCTAxe family) speaks standard Stratum and supports any SHA-256 coin.

## Web UI Settings

1. Connect to the miner’s Wi-Fi or find its IP on your LAN.
2. Open the AxeOS / ESP-Miner web interface.
3. Go to **Settings → Stratum**.

### Primary Stratum (your own node – once stratum is running)

```
Stratum Host:   <NAS-IP or hostname>
Stratum Port:   3333
Username:       FYourFreeCashAddress.nerdqaxe01
Password:       x
```

- Username = your **FCH address** + optional `.workername`
- Password is usually ignored (`x` is fine)

### Fallback (recommended while testing)

Keep Mining-Dutch SOLO as fallback so you never go offline:

```
Fallback Host:  mining-dutch.nl   (or the exact FCH stratum host from their getting-started page)
Fallback Port:  (check current FCH port on Mining-Dutch)
Username:       FYourFreeCashAddress.SyCzYT
Password:       x
```

## Important

- FreeCash addresses start with `F`.
- Make sure the node is fully synced before expecting valid work.
- Until a local stratum is attached to `freecashd`, the ASIC cannot get jobs from the node alone.
- You can continue mining on Mining-Dutch SOLO and run the node + dashboard in parallel for monitoring and future true-solo migration.

## Dual-pool / hashrate split

Newer NerdQaxe firmware supports dual stratum. You can send e.g. 80 % to your future local stratum and 20 % to Mining-Dutch as safety net.
