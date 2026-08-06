# freecash-coin

**Production-oriented FreeCash (FCH) Solo Mining Stack for Docker / Portainer on NAS**

True solo mining with your own node + ASIC (NerdQaxe++ and any SHA-256 ASIC).

When you run your own full node + stratum, **every valid block you find is 100% yours**. No pool operator, no shared shares.

---

## Why own node?

- Multiple miners on a public pool = your hashrate competes for the same shares.
- Own node + SOLO stratum = your ASIC works only for **your** coinbase address.
- FreeCash uses SHA-256 → any BTC/BCH ASIC works (including NerdQaxe++ ~4.8 TH/s).

Block time ~1 minute, current reward ~8.19 FCH (+ fees). Difficulty is low enough that home ASICs have a realistic chance of finding blocks.

---

## Architecture

```
[NerdQaxe++ ASIC] 
        │ stratum+tcp
        ▼
[Stratum / Solo Proxy]  ← optional (eloipool / ckpool adapted / miningcore)
        │ getblocktemplate RPC
        ▼
[freecashd Full Node]   ← Docker volume for blockchain
        │
        ▼
[Flask Dashboard]       ← Mining-Dutch style UI (port 8080)
```

---

## Quick Start (Portainer on NAS)

1. Clone or download this repo on your NAS.
2. Create a stack in Portainer with the provided `docker-compose.yml`.
3. Set environment variables (see `.env.example`).
4. Map a persistent volume for blockchain data (important – sync takes time).
5. Start the stack.
6. Wait for full sync (`getblockchaininfo` → `blocks` == `headers`).
7. Point your NerdQaxe++ to the stratum endpoint (or keep Mining-Dutch SOLO as fallback).

Detailed Portainer steps and ASIC config are in `docs/PORTAINER.md` and `docs/NERDQAXE.md`.

---

## Components

| Service       | Purpose                          | Port (default) |
|---------------|----------------------------------|----------------|
| freecashd     | Full node + RPC                  | 8332 (RPC), 8333 (P2P) |
| dashboard     | Flask UI (Mining-Dutch layout)   | 8080           |
| stratum       | Solo stratum (optional)          | 3333           |

---

## Dashboard Features (Mining-Dutch style)

- Network: Nethash estimate, Difficulty, Height, Price (if available)
- Mode table (SOLO focused)
- Personal hashrate / workers / effort / estimated time to block
- Round info & highest shares
- Recent blocks found (from node)
- Auto-refresh every 5–10 s
- Dark theme matching modern pool dashboards

---

## Important Notes (Production)

- **Blockchain size**: Plan for several GB + growth. Use a fast SSD volume.
- **RPC security**: Never expose RPC to the internet. Use `rpcallowip` only for Docker network / localhost.
- **Stratum**: A full production SHA-256 solo stratum (correct GBT → jobs → share validation → block submission) is non-trivial. This repo provides the node + dashboard foundation. For true local stratum we recommend adapting [eloipool](https://github.com/SKlayer/fch-eloipool) or ckpool in BTCSOLO mode with FreeCash RPC.
- **Maturity**: FreeCash coinbase maturity is long (check current rules). Blocks need confirmations before spendable.
- **Backup**: Always backup your wallet.dat / seed and the datadir.

---

## Research Sources

- https://learnmeabitcoin.com/technical/mining/ (block header, HASH256, target, nonce, coinbase)
- Official FreeCash: https://github.com/freecashorg/freecash
- Mining-Dutch FCH dashboard (layout reference)
- NerdQaxe++ firmware (ESP-Miner based)

---

## License

MIT – use at your own risk. Crypto mining involves financial risk and electricity costs.

---

Made for true solo miners who want every share (and every block) for themselves.
