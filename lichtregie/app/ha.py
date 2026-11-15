"""Zugriff auf Home Assistant: Dienste aufrufen und den laufenden Titel lesen."""
import json
import urllib.request
from datetime import datetime, timezone

import config


def _request(path, data=None, timeout=8):
    req = urllib.request.Request(
        f"{config.HA_API}/{path}", data=json.dumps(data).encode("utf-8") if data is not None else None,
        method="POST" if data is not None else "GET",
        headers={"Authorization": f"Bearer {config.ha_token()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "null")


def call(domain, service, data):
    """Ruft einen HA-Dienst auf. True bei Erfolg."""
    try:
        _request(f"services/{domain}/{service}", data)
        return True
    except Exception as err:
        print(f"HA-Aufruf {domain}.{service} fehlgeschlagen: {err}", flush=True)
        return False


def now_playing():
    """Der laufende Titel aus HA, oder None, wenn nichts läuft oder HA nicht antwortet."""
    try:
        if not config.PLAYER:
            return None
        data = _request(f"states/{config.PLAYER}", timeout=5)
    except Exception:
        return None
    attrs = data.get("attributes", {})
    if not attrs.get("media_title"):
        return None
    playing = data.get("state") == "playing"
    # Position hochrechnen: HA aktualisiert sie nur alle paar Sekunden
    pos = attrs.get("media_position")
    updated = attrs.get("media_position_updated_at")
    estimate = None
    if pos is not None and updated:
        estimate = float(pos)
        if playing:
            estimate += (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).total_seconds()
    return {"title": attrs["media_title"], "artist": attrs.get("media_artist", ""),
            "id": attrs.get("media_content_id"),
            "duration": attrs.get("media_duration"), "pos": estimate, "playing": playing}


def states(entities):
    """Zustand mehrerer Entitäten: {entity_id: "on"/"off"/…}; nicht erreichbare fehlen."""
    out = {}
    for entity in entities:
        try:
            out[entity] = _request(f"states/{entity}", timeout=4).get("state")
        except Exception:
            pass
    return out
