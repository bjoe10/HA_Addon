# RustDesk Server + API

This Home Assistant app runs the RustDesk API, web admin/client, ID server (`hbbs`) and relay (`hbbr`) in one container. It is based on the multi-architecture `lejianwen/rustdesk-server-s6:v0.1.2` image and targets `aarch64` and `amd64`.

## Before starting

Set these options in the app configuration:

- **Public RustDesk host**: public DNS name or IPv4 address, without `http(s)://` or a port. Example: `rustdesk.example.net`.
- **Public API URL**: the externally reachable origin for the API and web UI. With Nginx Proxy Manager and HTTPS, use e.g. `https://rustdesk.example.net`. For LAN-only use, use `http://<HA-IP>:21114`.
- Keep **Allow user self-registration** disabled unless you intentionally want open registration.
- **Require account login** is off by default. If enabled, provide a long random **JWT signing key** (for example `openssl rand -hex 32`).

The add-on uses host networking for RustDesk's P2P and relay ports. If any of ports 21114–21119 are already occupied on the HA host, startup will fail.

## Ports and firewall

| Port | Protocol | Purpose |
|---:|---|---|
| 21114 | TCP | API, admin UI and web client |
| 21115 | TCP | NAT type test |
| 21116 | TCP + UDP | ID/rendezvous server |
| 21117 | TCP | Relay server |
| 21118 | TCP | WebSocket service |
| 21119 | TCP | WebSocket service |

For remote RustDesk clients, forward the server ports to the HA host as required by your network setup: 21115/TCP, 21116/TCP+UDP, 21117/TCP; forward 21118/TCP and 21119/TCP if using WebSocket clients. Keep 21114 private where possible and expose it through a TLS reverse proxy instead of forwarding it directly to the internet.

## Nginx Proxy Manager and Home Assistant

Create a proxy host for the API/web UI, pointing to the HA host on port `21114`; enable WebSocket support and use a valid TLS certificate. The web admin is at `/_admin/`; the classic web client is at `/webclient/`.

To add the admin UI to a Home Assistant dashboard, use a webpage/iframe panel pointing at `https://<your-domain>/_admin/`. If the browser refuses to embed it, use the URL in a new tab; reverse-proxy frame policies can affect iframe embedding.

The API URL configured in the add-on must match the public URL used by the clients. The ID and relay host are advertised separately using the public hostname and ports 21116/21117.

## Persistence and credentials

- RustDesk server keys and server data persist in the app's `/data` volume.
- The API database is mapped to the app's persistent configuration directory at `/app/data`.
- The upstream README documents the initial admin credentials as `admin` / `admin`. Change the password immediately after first login.
- The public key for RustDesk clients is stored at `/data/id_ed25519.pub` and is stable across restarts and upgrades.

## Security notes

- The app is not configured for HA Ingress: RustDesk uses multiple TCP/UDP ports, and the upstream web UI is served from the root path.
- Use HTTPS for the public API/web UI, disable registration unless needed, and do not expose the admin API directly without a reverse proxy and strong credentials.
- `encrypted_only` defaults to enabled. `must_login` defaults to disabled to preserve normal client behavior; enable it only after configuring API accounts and a JWT key.
- The upstream v2 web client is not relied on here; the documented UI path is the classic `/webclient/` client.

## Upstream

- API and web UI: https://github.com/lejianwen/rustdesk-api
- Integrated RustDesk server image: https://github.com/lejianwen/rustdesk-server
- This add-on uses the upstream `v0.1.2` server image tag.
