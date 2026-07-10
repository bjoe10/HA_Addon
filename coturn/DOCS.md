# Coturn TURN Server

TURN/STUN server für Nextcloud Talk und andere WebRTC-Anwendungen.

## Voraussetzungen

- Eine öffentliche Domain mit SSL-Zertifikat (Let's Encrypt)
- Portweiterleitung im Router:
  - 3478 UDP + TCP
  - 5349 UDP + TCP
  - **49160–49200 UDP** (Relay-Port-Bereich – ohne diese Freigabe ist die Verbindung langsam/instabil, da Coturn auf Fallback-Wege ausweichen muss)

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
| `min_port` | Unterer Relay-Port | `49160` |
| `max_port` | Oberer Relay-Port | `49200` |

Der Relay-Port-Bereich ist bewusst klein gehalten (41 Ports = genug für mehrere gleichzeitige Calls). Größerer Bereich = mehr gleichzeitige Verbindungen möglich, aber auch mehr Ports zum Freigeben.

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
| 49160-49200 | UDP | Relay-Medienstream |

## Zertifikatserneuerung

Let's Encrypt erneuert Zertifikate automatisch alle 90 Tage. Coturn liest die Zertifikate nur beim Start ein – nach jeder Erneuerung muss das Addon neu gestartet werden, sonst läuft TLS mit dem alten (bald abgelaufenen) Zertifikat weiter.

Empfehlung: Eine HA-Automation die bei "Certificate expiring"-Events (oder monatlich) `hassio.addon_restart` mit `addon: local_coturn` aufruft.
