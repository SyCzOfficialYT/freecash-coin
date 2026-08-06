# Local Stratum for True Solo

A full production SHA-256 solo stratum must:

1. Call `getblocktemplate` (or equivalent) on freecashd
2. Build stratum jobs (prevhash, coinb1/coinb2, merkle branches, version, nbits, ntime, …)
3. Hand out work to ASICs with adjustable difficulty
4. Validate shares
5. When a share meets network difficulty → assemble the block and `submitblock`

## Recommended starting points for FreeCash

- **fch-eloipool** – https://github.com/SKlayer/fch-eloipool (FreeCash-specific eloipool fork)
- **ckpool** in BTCSOLO mode – adapt RPC endpoints and coinbase rules for FCH
- **miningcore** – add a FreeCash coin definition

Once you have a working stratum binary/image, add it to `docker-compose.yml` and point the NerdQaxe++ at it.

This repository currently focuses on a reliable full node + Mining-Dutch-style monitoring dashboard so you can run the node safely on your NAS while preparing the stratum layer.
