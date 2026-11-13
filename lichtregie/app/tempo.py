"""Tempo und Stimmung pro Titel über die FreqBlog Music API, mit Cache in DATA/tempo.json."""
import json
import urllib.parse
import urllib.request

import config

URL = "https://api.freqblog.com/lookup"


def _cache_file():
    return config.DATA / "tempo.json"


def _cache():
    try:
        return json.loads(_cache_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _store(cache):
    _cache_file().parent.mkdir(parents=True, exist_ok=True)
    _cache_file().write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def tempo(title, artist):
    """{bpm, time_signature, key, energy, …} oder None. Neue Titel analysiert FreqBlog erst im
    Hintergrund, dann kommt zunächst None und ein paar Sekunden später das Ergebnis."""
    key = f"{artist} – {title}"
    cache = _cache()
    if key in cache and "energy" in cache[key]:
        return cache[key]
    api_key = config.freqblog_key()
    if not api_key:
        return None
    query = urllib.parse.urlencode({"track": title, "artist": artist})
    req = urllib.request.Request(f"{URL}?{query}", headers={"X-Api-Key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    result = {k: data.get(k) for k in ("bpm", "time_signature", "key", "bpm_confidence", "energy",
                                       "danceability", "valence", "loudness_db")}
    if result["bpm"] is None:
        return None
    cache[key] = result
    _store(cache)
    return result
