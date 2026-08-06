# Portainer Deployment (NAS)

## 1. Prepare data directory

On your NAS create a persistent folder, e.g.:

- Synology: `/volume1/docker/freecash/data`
- Unraid: `/mnt/user/appdata/freecash/data`
- TrueNAS: `/mnt/tank/apps/freecash/data`

Make sure the user running Docker can write to it.

## 2. Create stack in Portainer

1. Portainer → Stacks → Add stack
2. Name: `freecash-solo`
3. Paste the content of `docker-compose.yml` (or upload the file)
4. Under Environment variables add the values from `.env.example` (especially `RPC_PASSWORD` and `NODE_DATA`)
5. Deploy the stack

## 3. First start

- The node will start syncing. This can take hours/days depending on hardware and network.
- Watch logs: Portainer → Containers → freecash-node → Logs
- Dashboard becomes available at `http://NAS-IP:8080` once the container is healthy.

## 4. Security

- RPC is bound to `127.0.0.1` on the host by default.
- Do **not** publish 8332 to the public internet.
- Change `RPC_PASSWORD` to a long random string.

## 5. Updates

Pull new images / rebuild dashboard when you update the repo, then recreate the stack.
