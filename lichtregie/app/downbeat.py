"""Die „1“ im Takt mit Beat This! (beatthis.py), im Hintergrund.

Alle REPEAT Sekunden, solange eine Show mit eingerastetem Audio-Takt läuft, gehen die letzten WINDOW Sekunden Ton
dieses Liedes an einen eigenen Prozess (niedrige Priorität, 2 Rechenkerne), damit die Show-Schleife nicht ruckelt.
Am Pi 5 dauerten 30 s Ton zuerst 33 s Rechenzeit (am Mac 1,5 s). Seltener rechnen hilft nicht: Mit einer
Rechnung pro Minute über 20 s sank die Trefferquote in den Aufnahmen von 93 % auf 62 % (die „1“ im Intro ist oft
mehrdeutig, spätere Rechnungen korrigieren das). Gemessen mit den Aufnahmen (Fenster/Abstand → Treffer):
30 s/15 s 93 %, 16 s/20 s 95 %, 16 s/30 s 88 %, 12 s/20 s 63 %. Am Pi: 16 s Ton in 7,2 s, also gut ein Drittel
der Zeit rechnend. Die Rechenzeit je Abschnitt steht im Add-on-Log.
Ergebnis: Zeitpunkte der „1“-Schläge (Uhrzeit der Analyse); die Schlagzählung legt den Takt danach fest.
Gemessen am 15.11.2026 mit 6 Aufnahmen vom Gerät: Mit dem richtigen Ton-Vorlauf lag die „1“ von Beat This zu
93 % auf der von Hand markierten „1“ (die bisherige Erkennung aus dem Klangwechsel: in 2 von 6 Liedern).
"""
import json
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

WINDOW = 16.0
MIN_AUDIO = 16.0
REPEAT = 20.0
THREADS = "2"
STATE = {"an": False, "rechenzeit": None, "letzte": 0.0, "eins": [], "beats": [], "bpm": None, "lied": None,
         "schlaege": 0, "fehler": "", "laeuft": False}
_PROC = {"p": None}
_LOCK = threading.Lock()


def _worker():
    p = _PROC["p"]
    if p is None or p.poll() is not None:
        env = dict(os.environ, OPENBLAS_NUM_THREADS=THREADS, OMP_NUM_THREADS=THREADS)
        p = subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve().parent / "beatthis.py"), "--worker"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env,
                             preexec_fn=lambda: os.nice(10))
        _PROC["p"] = p
    return p


def analyze(x):
    """Ton (mono, 44,1 kHz) → (Schläge, „1“-Schläge) in Sekunden ab Beginn; im Worker-Prozess."""
    with _LOCK:
        p = _worker()
        data = np.asarray(x, dtype=np.float32).tobytes()
        p.stdin.write(struct.pack("<I", len(data)) + data)
        p.stdin.flush()
        line = p.stdout.readline()
    if not line:
        raise RuntimeError("Beat-This-Prozess beendet")
    r = json.loads(line)
    return np.array(r["beats"]), np.array(r["downs"])


def loop(engine):
    """Hintergrund-Thread: rechnet, solange eine Show mit Audio-Takt läuft."""
    STATE["an"] = True
    last, last_song = 0.0, None
    while True:
        time.sleep(1.0)
        a = engine.AUDIO
        song = engine.BEAT["start"]
        key = tuple(song[:2]) if song else None
        if (a is None or engine.BEAT["stop"] is None or not engine.SETTINGS["audio"]
                or not engine.SETTINGS.get("beatthis", True) or not a.phase_ok()
                or time.time() - last < REPEAT):
            continue
        # nur Ton dieses Liedes: Es begann (Uhrzeit der Analyse) spätestens Ton-Vorlauf vor dem Start der Show
        avail = time.time() - engine.BEAT.get("since", 0.0) + engine.SETTINGS["ton_vorlauf"] - 0.5
        if avail < MIN_AUDIO:
            continue
        with a.lock:
            x, clock = a.recent_audio(min(WINDOW, avail))
        if x is None or len(x) < MIN_AUDIO * 44100:
            continue
        last, last_song = time.time(), key
        STATE["laeuft"] = True
        try:
            t0 = time.time()
            beats, downs = analyze(x)
            STATE.update(rechenzeit=round(time.time() - t0, 1), letzte=time.time(), fehler="",
                         schlaege=len(beats), eins=[float(t) for t in clock(downs)],
                         beats=[float(t) for t in clock(beats)], bpm=tempo(beats),
                         lied=tuple(song[:2]) if song else None)
        except (OSError, RuntimeError, ValueError) as err:
            STATE["fehler"] = str(err)
            print(f"Beat This: {err}", flush=True)
        STATE["laeuft"] = False


def tempo(beats):
    """Genaues Tempo aus den Schlägen: Ausgleichsgerade über die durchnummerierten Schläge (Lücken überbrückt).
    Der Median der Abstände allein klebt an den 20-ms-Bildern des Modells."""
    b = np.asarray(beats)
    if len(b) < 12:
        return None
    step = np.median(np.diff(b))
    idx = np.concatenate([[0], np.cumsum(np.maximum(1, np.round(np.diff(b) / step)))])
    return round(60.0 / float(np.polyfit(idx, b, 1)[0]), 2)


def status():
    return {k: STATE[k] for k in ("an", "rechenzeit", "schlaege", "fehler", "bpm")} | {
        "vor_s": int(time.time() - STATE["letzte"]) if STATE["letzte"] else None}
