# Enabling Docker IPv6 for Direttore

The production `docker-compose.yml` uses dual-stack networking by default (`ENABLE_IPV6=true`). This requires the Docker daemon to have IPv6 support enabled before you run `docker compose up`.

## 1. Configure the Docker daemon

Create or edit `/etc/docker/daemon.json`:

```json
{
  "ipv6": true,
  "ip6tables": true
}
```

- `"ipv6": true` — enables IPv6 in Docker networking subsystem
- `"ip6tables": true` — enables kernel IPv6 NAT for containers (equivalent of IPv4 masquerade; required for containers to reach the internet over IPv6)

If the file already exists, merge these keys into the existing JSON object — do not overwrite other settings.

## 2. Apply the change

```bash
sudo systemctl restart docker
```

Verify the daemon restarted cleanly:

```bash
sudo systemctl status docker
```

## 3. Verify IPv6 is active

After starting the stack (`docker compose up -d`), check that the `proxy` network has an IPv6 subnet:

```bash
docker network inspect direttore_proxy | grep -A 10 '"IPAM"'
```

Expected output includes:
```json
"Config": [
    { "Subnet": "172.20.0.0/16" },
    { "Subnet": "fd00:0:1::/64" }
]
```

Check that ip6tables masquerade is active:

```bash
sudo ip6tables -t nat -L POSTROUTING -n
```

You should see a `MASQUERADE` rule for the `fd00:0:1::/64` subnet.

## 4. Stack mode reference

The compose file supports three modes via environment variables in `.env`:

| Mode | `TRAEFIK_HOST_IP` | `TRAEFIK_BIND_ADDR` | `ENABLE_IPV6` |
|---|---|---|---|
| Dual-stack / IPv6-preferred (default) | `::` | `[::]` | `true` |
| IPv6-only | `::` | `[::]` | `true` + drop IPv4 at host firewall |
| IPv4-only | `0.0.0.0` | `0.0.0.0` | `false` |

For **IPv6-only**, set the dual-stack values and additionally block IPv4 inbound at the host firewall (e.g. `iptables -I INPUT -p tcp --dport 80 -j DROP` and similarly for 443). The compose file itself is identical for dual-stack and IPv6-only modes.

For **IPv4-only**, set `ENABLE_IPV6=false` — the IPv6 IPAM subnet is not created and `TRAEFIK_HOST_IP=0.0.0.0` maps the ports to IPv4 only. The daemon.json change is not required in this mode.

## 5. Troubleshooting

**`docker compose up` fails with "IPv6 is disabled"**
→ The daemon.json change was not applied or Docker was not restarted.

**Traefik shows "bind: cannot assign requested address" for `[::]:80`**
→ The kernel module `ip6table_filter` may not be loaded. Run `sudo modprobe ip6table_filter` and retry.

**`curl -6 https://your-domain` times out**
→ Check that your DNS has an AAAA record pointing to the host, and that the host firewall allows TCP/443 on IPv6 (`ip6tables -L INPUT -n`).

**Let's Encrypt HTTP-01 challenge fails**
→ The ACME challenge requires port 80 to be reachable from the internet. Ensure your firewall allows inbound TCP/80 from all sources (Traefik redirects to HTTPS after the challenge succeeds).
