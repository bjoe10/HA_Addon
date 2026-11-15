#!/usr/bin/env python3
"""Spielt eine Aufnahme vom Gerät (ZIP aus „Aufnahme für die Fehlersuche“) durch Analyse und Schlagzählung.

Der Ton wird in denselben Blöcken und mit denselben Zeitstempeln eingespeist wie am Gerät; die HA-Schätzung der
Taktposition kommt aus der Aufnahme. Ausgabe: Tempo, Sicherheit, Ereignisse und wie die Markierungen von Hand
(„Hier ist die 1“) zur gezählten „1“ liegen (Position im Takt und Abstand zum Schlag in ms).
Aufruf: python3 dev/nachspielen.py aufnahme.zip [weitere.zip …]
"""
import io
import json
import sys
import wave
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import audio  # noqa: E402
from beatcount import BeatCounter  # noqa: E402


def load(path):
    z = zipfile.ZipFile(path)
    data = json.loads(z.read("daten.json"))
    with wave.open(io.BytesIO(z.read("ton.wav"))) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    return data, pcm


def replay(data, pcm, versatz=None):
    """Rückgabe: Liste (t, b, locked) je Bild der Aufnahme, Analyzer, Zähler."""
    versatz = data["meta"].get("audio_versatz", 80.0) if versatz is None else versatz
    trace = [r for r in data["trace"] if r.get("b_ha") is not None]
    an, c = audio.Analyzer(), BeatCounter()
    bpm = None
    out, pos, ti = [], 0, 0
    for t_end, n in data["blocks"]:
        an.feed(pcm[pos:pos + n], t_end)
        pos += n
        while ti < len(trace) and trace[ti]["t"] <= t_end:
            r = trace[ti]
            ti += 1
            if r["bpm"] != bpm:                      # neues Lied in der Aufnahme
                bpm = r["bpm"]
                an.new_song()
                an.set_bpm_hint(bpm)
                c = BeatCounter()
                c.seen_drop, c.seen_change = an.drop_at, an.change_at
            now = r["t"]
            if not an.signal(now):
                continue
            locked = an.phase_ok(now)
            frac = an.phase(now + versatz / 1000.0) if locked else None
            ch = an.changes_since(c.seen_bc) if locked else None
            b = c.update(now, r["b_ha"], frac, an.drop_at, an.change_at, bpm, ch)
            out.append((now, b, locked))
    return out, an, c, bpm


def judge(marks, frames, bpm):
    """Markierungen gegen eine Zählung: Position im Takt je Markierung, Abstand zum nächsten Schlag (ms)."""
    if not marks or not frames:
        return None
    ts = np.array([f[0] for f in frames])
    bs = np.array([f[1] for f in frames])
    pos, ms = [], []
    for m in marks:
        i = int(np.argmin(np.abs(ts - m)))
        if abs(ts[i] - m) > 0.2:
            continue
        b = bs[i] + (m - ts[i]) * bpm / 60.0
        pos.append(int(round(b)) % 4)
        ms.append((b - round(b)) * 60000.0 / bpm)
    return Counter(pos), (float(np.median(ms)) if ms else 0.0), (float(np.std(ms)) if ms else 0.0)


for path in sys.argv[1:]:
    data, pcm = load(path)
    print(f"\n== {Path(path).name}: {data['meta'].get('titel')} · {len(pcm) / 44100:.0f} s Ton, "
          f"{len(data['trace'])} Bilder, {len(data['marks'])} Markierungen")
    frames, an, c, bpm = replay(data, pcm)
    if not frames:
        print("   keine Show-Bilder mit Ton in der Aufnahme")
        continue
    st = an.status(frames[-1][0])
    print(f"   Tempo {bpm} BPM (Analyse {st['bpm']}), Sicherheit {st['sicher']}, eingerastet in "
          f"{100 * sum(f[2] for f in frames) / len(frames):.0f} % der Bilder")
    print(f"   „1“: {c.bar_info()}, Verteilung {[round(x, 2) for x in c.bar_bins]}")
    print(f"   Ereignisse: {[e[1] for e in c.events]}")
    geraet = [(r["t"], r["b"], r["locked"]) for r in data["trace"] if r.get("b") is not None]
    for name, fr in (("am Gerät", geraet), ("nachgespielt", frames)):
        res = judge(data["marks"], fr, bpm)
        if res:
            print(f"   Markierungen {name}: Position im Takt {dict(sorted(res[0].items()))} (0 = die „1“), "
                  f"Abstand zum Schlag median {res[1]:+.0f} ms, Streuung {res[2]:.0f} ms")
