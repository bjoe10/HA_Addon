"""Aufnahme für die Fehlersuche: schneidet den Ton am Empfänger mit und dazu, was die Erkennung entschieden hat.

Eine Aufnahme ist eine ZIP-Datei in DATA/aufnahmen mit
- ton.wav: der Ton, wie ihn die Analyse bekommen hat (mono, 44,1 kHz),
- daten.json: Zeitstempel jedes gelesenen Blocks (zum exakten Nachspielen), die Entscheidungen der Show je Bild
  (20-mal pro Sekunde: Schlagnummer, HA-Schätzung, Phase, Break, Drop, Ereignisse) und die Markierungen von
  Hand („Hier ist die 1“) als Wahrheit.
Nachspielen auf dem Mac: dev/nachspielen.py. Die Aufnahmen bleiben auf dem Gerät, bis sie jemand herunterlädt.
"""
import io
import json
import re
import threading
import time
import wave
import zipfile

import numpy as np

import config

DIR = config.DATA / "aufnahmen"
SECONDS = 90
KEEP = 12                  # so viele Aufnahmen bleiben liegen, ältere werden gelöscht
NAME = re.compile(r"^\d{8}-\d{6}\.zip$")
LOCK = threading.Lock()
REC = {"on": False, "start": 0.0, "until": 0.0, "chunks": [], "blocks": [], "trace": [], "marks": [],
       "haenger": [], "sends": [], "meta": {}, "last_trace": 0.0}


def start(meta, seconds=None):
    now = time.time()
    with LOCK:
        REC.update(on=True, start=now, until=now + (seconds or SECONDS), chunks=[], blocks=[], trace=[],
                   marks=[], haenger=[], sends=[], meta=dict(meta), last_trace=0.0)


def tap(mono, t_end):
    """Vom Audio-Leser für jeden gelesenen Block aufgerufen (mono, float32)."""
    if not REC["on"]:
        return
    REC["chunks"].append(np.clip(np.round(mono * 32768.0), -32768, 32767).astype("<i2"))
    REC["blocks"].append((round(t_end, 4), len(mono)))
    _check(t_end)


def trace(now, row):
    """Von der Show-Schleife in jedem Bild aufgerufen (40 pro Sekunde): Entscheidungen und was an die Köpfe geht."""
    if not REC["on"]:
        return
    REC["last_trace"] = now
    REC["trace"].append(dict(row, t=round(now, 3)))
    _check(now)


def mark(now=None, kind="marks"):
    """„Hier ist die 1“ (marks) oder „Hängt jetzt“ (haenger) von Hand, nur als Markierung (ändert die Show nicht)."""
    if not REC["on"]:
        return False
    REC[kind].append(round(time.time() if now is None else now, 3))
    return True


def sent(t):
    """Vom Art-Net-Sender bei jeder Sendung aufgerufen."""
    if REC["on"]:
        REC["sends"].append(round(t, 4))


def _check(now):
    if REC["on"] and now >= REC["until"]:
        with LOCK:
            if not REC["on"]:
                return
            REC["on"] = False
        threading.Thread(target=_write, daemon=True).start()


def stop():
    _check(float("inf"))


def _write():
    chunks, blocks = REC["chunks"], REC["blocks"]
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype="<i2")
    wav = io.BytesIO()
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(pcm.tobytes())
    data = {"meta": REC["meta"], "start": REC["start"], "blocks": blocks, "trace": REC["trace"],
            "marks": REC["marks"], "haenger": REC["haenger"], "sends": REC["sends"]}
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S", time.localtime(REC["start"])) + ".zip"
        with zipfile.ZipFile(DIR / name, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("ton.wav", wav.getvalue())
            z.writestr("daten.json", json.dumps(data, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
        for old in sorted(p for p in DIR.iterdir() if NAME.match(p.name))[:-KEEP]:
            old.unlink()
        print(f"Aufnahme gespeichert: {name} ({len(pcm) / 44100:.0f} s Ton, {len(REC['marks'])} Markierungen)",
              flush=True)
    except OSError as err:
        print(f"Aufnahme nicht gespeichert: {err}", flush=True)
    REC.update(chunks=[], blocks=[], trace=[], sends=[])


def files():
    try:
        return sorted((p.name for p in DIR.iterdir() if NAME.match(p.name)), reverse=True)
    except OSError:
        return []


def read(name):
    """Inhalt einer Aufnahme für den Download, oder None."""
    if not NAME.match(name):
        return None
    try:
        return (DIR / name).read_bytes()
    except OSError:
        return None


def status(now=None):
    now = time.time() if now is None else now
    _check(now)                # endet auch, wenn kein Ton und keine Show mehr läuft
    return {"laeuft": REC["on"], "rest": max(0, int(REC["until"] - now)) if REC["on"] else 0,
            "ton": bool(REC["blocks"]), "marken": len(REC["marks"]), "haenger": len(REC["haenger"]),
            "dateien": files()}
