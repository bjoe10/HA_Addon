"""Kleine JSON-Dateien in DATA (Themen, Tempo, Party-Stand, Lampen, Einstellungen): lesen und schreiben, Fehler
werden geschluckt (fehlt oder ist kaputt → leer; nicht schreibbar → nichts)."""
import json


def load(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def save(path, data, **kw):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, **kw), encoding="utf-8")
        return True
    except OSError:
        return False
