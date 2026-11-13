"""Einstellungen der Lichtregie aus Umgebungsvariablen.

Im Add-on setzt run.sh die Werte (HA-Zugang über den Supervisor), lokal auf dem Mac dev/run_local.sh.
Die Art-Net-Nodes und Kanäle werden aus der HA-configuration.yaml gelesen (Plattform artnet_led).
"""
import os
import re
from pathlib import Path

DATA = Path(os.environ.get("LICHTREGIE_DATA", "/data"))
PORT = int(os.environ.get("LICHTREGIE_PORT", "8099"))
HA_API = os.environ.get("LICHTREGIE_HA_API", "http://supervisor/core/api").rstrip("/")
PLAYER = os.environ.get("LICHTREGIE_PLAYER", "").strip()
HA_CONFIG_DIRS = [Path(p) for p in os.environ.get("LICHTREGIE_HA_CONFIG", "/homeassistant:/config").split(":")]


def ha_token():
    """Im Add-on der Supervisor-Token, lokal ein Token aus einer Datei."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:
        return token
    path = os.environ.get("LICHTREGIE_HA_TOKEN_FILE")
    return Path(path).expanduser().read_text(encoding="utf-8").strip() if path else ""


def freqblog_key():
    key = os.environ.get("LICHTREGIE_FREQBLOG_KEY", "").strip()
    if key:
        return key
    path = os.environ.get("LICHTREGIE_FREQBLOG_KEY_FILE")
    if path and Path(path).expanduser().exists():
        return Path(path).expanduser().read_text(encoding="utf-8").strip()
    return ""


# --- Art-Net-Nodes und Kanäle -----------------------------------------------------------------------
# Namen der Kanäle in der artnet_led-Konfiguration (klein geschrieben), je Kopf
_BASE = {"pan": "pan", "tilt": "tilt", "color": "color", "gobo": "grobo", "strobe": "strobe",
         "dimmer": "dimmer", "speed": "motor speed", "auto": "auto mode", "config": "config mode"}
NAMES = {1: dict(_BASE), 2: {k: v + "2" for k, v in _BASE.items()}}
# Rückfall, wenn configuration.yaml nicht lesbar ist (Stand der Einrichtung im November 2026)
DEFAULT = {
    1: ("192.168.178.144", 1, {"pan": 1, "tilt": 3, "color": 5, "gobo": 6, "strobe": 7, "dimmer": 8,
                               "speed": 9, "auto": 10, "config": 11}),
    2: ("192.168.178.146", 1, {"pan": 12, "tilt": 14, "color": 16, "gobo": 17, "strobe": 18, "dimmer": 19,
                               "speed": 20, "auto": 21, "config": 22}),
}


def parse_artnet(text):
    """Liest die artnet_led-Einträge aus der configuration.yaml, zeilenweise ohne YAML-Bibliothek
    (Tags wie !include stören so nicht). Rückgabe: Liste von {host, universe, devices: {name: kanal}}."""
    nodes, cur, chan = [], None, None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[0].isspace():          # neuer Schlüssel auf oberster Ebene
            cur = None
            continue
        m = re.match(r"\s*-\s*platform:\s*(\S+)", line)
        if m:
            cur = {"host": None, "universe": 1, "devices": {}} if m.group(1) == "artnet_led" else None
            if cur is not None:
                nodes.append(cur)
            chan = None
            continue
        if cur is None:
            continue
        m = re.match(r"\s*host:\s*(\S+)", line)
        if m:
            cur["host"] = m.group(1)
            continue
        m = re.match(r"\s*(\d+):\s*$", line)
        if m:
            cur["universe"] = int(m.group(1))
            continue
        m = re.match(r"\s*-\s*channel:\s*(\d+)", line)
        if m:
            chan = int(m.group(1))
            continue
        m = re.match(r"\s*name:\s*(.+)", line)
        if m and chan is not None:
            cur["devices"][m.group(1).strip().lower()] = chan
            chan = None
    return nodes


def heads_from_text(text):
    """Zuordnung je Kopf: (host, universe, {funktion: kanal}). Fehlt etwas, gilt der Rückfall."""
    nodes = parse_artnet(text) if text else []
    result, source = {}, {}
    for k in (1, 2):
        result[k], source[k] = DEFAULT[k], "Standardwerte"
        for node in nodes:
            ch = {key: node["devices"][name] for key, name in NAMES[k].items() if name in node["devices"]}
            if "pan" in ch and "tilt" in ch and node["host"]:
                result[k] = (node["host"], node["universe"], {**DEFAULT[k][2], **ch})
                source[k] = "configuration.yaml"
                break
    return result, source


def _read_ha_config():
    for d in HA_CONFIG_DIRS:
        f = d / "configuration.yaml"
        if f.exists():
            return f.read_text(encoding="utf-8")
    return None


HEADS, HEADS_SOURCE = heads_from_text(_read_ha_config())
NODES = {k: v[0] for k, v in HEADS.items()}
UNIVERSE = {k: v[1] for k, v in HEADS.items()}
LAYOUT = {k: v[2] for k, v in HEADS.items()}
