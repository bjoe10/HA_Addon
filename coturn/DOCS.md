# Coturn TURN Server

TURN/STUN server für Nextcloud Talk und andere WebRTC-Anwendungen.

## Voraussetzungen

- Eine öffentliche Domain mit SSL-Zertifikat (Let's Encrypt)
- Portweiterleitung im Router:
  - 3478 UDP + TCP
  - 5349 UDP + TCP

## Konfiguration

| Option | Beschreibung | Beispiel |
|--------|-------------|---------|
| `external_ip` | Deine öffentliche IP oder Domain | `nc.yourdomain.com` |
| `static_auth_secret` | Zufälliger Secret-String | `openssl rand -hex 32` |
| `realm` | Deine Domain | `yourdomain.com` |
| `listening_port` | TURN Port (Standard: 3478) | `3478` |
| `tls_port` | TURN TLS Port (Standard: 5349) | `5349` |
| `use_tls` | TLS aktivieren | `true` |
| `cert_path` | Pfad zum SSL-Zertifikat | `/ssl/fullchain.pem` |
| `key_path` | Pfad zum SSL-Key | `/ssl/privkey.pem` |

## Secret generieren

Ein sicheres Secret kannst du so generieren:
```bash
openssl rand -hex 32
```

## Nextcloud Talk Konfiguration

Nach dem Start des Addons in Nextcloud Admin → Talk → TURN-Server eintragen:

- `turn:deine-domain.de:3478` → UDP+TCP
- `turns:deine-domain.de:5349` → TLS

Als Secret den gleichen Wert wie `static_auth_secret` verwenden.

## Router Portweiterleitung

| Port | Protokoll | Beschreibung |
|------|-----------|-------------|
| 3478 | UDP + TCP | TURN/STUN |
| 5349 | UDP + TCP | TURN/STUN TLS |
