#!/usr/bin/env python3
"""Test der Audioanalyse mit synthetischer Tanzmusik: Kick auf jedem Schlag, Hi-Hat dazwischen,
8 Takte Break ohne Kick (nur Fläche), dann Drop. Prüft Schlagphase, Break- und Drop-Erkennung.
Aufruf: python3 dev/test_audio.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import audio  # noqa: E402

RATE = audio.RATE
BPM = 124.0
BEAT = 60.0 / BPM
OFFSET = 0.137          # erster Kick liegt bei 0,137 s (Phase unbekannt für die Analyse)
rng = np.random.default_rng(1)


def song(seconds, kick_on):
    t = np.arange(int(seconds * RATE)) / RATE
    x = 0.08 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.25 * t))   # Fläche
    beats = np.arange(OFFSET, seconds, BEAT)
    for b in beats:
        i = int(b * RATE)
        if kick_on(b):
            n = int(0.15 * RATE)
            tt = np.arange(n) / RATE
            kick = 0.9 * np.sin(2 * np.pi * (55 + 60 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 18)
            x[i:i + n] += kick[: len(x) - i]
        j = int((b + BEAT / 2) * RATE)      # Hi-Hat auf dem Offbeat
        n = int(0.04 * RATE)
        if j + n < len(x):
            x[j:j + n] += 0.15 * rng.standard_normal(n) * np.exp(-np.arange(n) / RATE * 80)
    return np.clip(x, -1, 1).astype(np.float32)


def run(hint):
    break_from, break_to = 20.0, 20.0 + 32 * BEAT          # 8 Takte Break ab 20 s
    x = song(50.0, lambda b: not (break_from <= b < break_to))
    an = audio.Analyzer()
    an.set_bpm_hint(hint)
    t0 = 1000.0
    chunk = 2048
    errs, breaks, drops = [], [], []
    for i in range(0, len(x), chunk):
        part = x[i:i + chunk]
        t_end = t0 + (i + len(part)) / RATE
        an.feed(part, t_end)
        song_t = (i + len(part)) / RATE
        if an.phase_ok(t_end) and (song_t < break_from or song_t > break_to + 4):
            ph = an.phase(t0 + OFFSET)            # Phase am echten Schlag sollte ~0 sein
            errs.append(min(ph, 1 - ph) * BEAT * 1000)
        lv = an.live(t_end, BPM)
        if lv["break"]:
            breaks.append(song_t)
        if lv["drop"] and lv["drop_beats"] < 1:
            drops.append(song_t)
    return errs, breaks, drops, an


for hint in (BPM, None):
    errs, breaks, drops, an = run(hint)
    label = "mit Tempo-Vorgabe" if hint else "ohne Vorgabe"
    print(f"{label}: erkanntes Tempo {60 / an.period:.1f} BPM, "
          f"Phasenfehler median {np.median(errs):.0f} ms, 95 % unter {np.percentile(errs, 95):.0f} ms "
          f"({len(errs)} Messungen)")
    print(f"   Break erkannt von {min(breaks):.1f} s bis {max(breaks):.1f} s (echt: 20,0 bis {20 + 32 * BEAT:.1f} s)"
          if breaks else "   kein Break erkannt")
    first_kick = min(b for b in np.arange(OFFSET, 50, BEAT) if b >= 20 + 32 * BEAT)
    print(f"   Drop erkannt bei {drops[0]:.2f} s (erster Kick nach dem Break: {first_kick:.2f} s)"
          if drops else "   kein Drop erkannt")
    assert np.median(errs) < (10 if hint else 50), "Phase zu ungenau"
    assert breaks and drops, "Break/Drop nicht erkannt"
# Lied ohne Tempo-Vorgabe, danach eines mit: Die Autokorrelation rechnet in float32. Eine float32-Periode machte
# auch den Schlag-Zeitpunkt (Uhrzeit ~1,8 Mrd. s) zu float32, auf 128 s genau: Phase immer 0, Zählung stand still
_y = np.zeros(int(20 * RATE), dtype=np.float32)
for _j in range(int(20 / (60 / 124))):
    _i = int(_j * 60 / 124 * RATE); _n = int(0.15 * RATE); _ts = np.arange(_n) / RATE
    _y[_i:_i + _n] += (0.9 * np.sin(2 * np.pi * (55 + 60 * np.exp(-_ts * 30)) * _ts) * np.exp(-_ts * 18))[:len(_y) - _i]
an = audio.Analyzer()
_T0 = 1.795e9
for _k in range(0, len(_y) - 4096, 4096):
    an.feed(_y[_k:_k + 4096], _T0 + (_k + 4096) / RATE)
an.set_bpm_hint(124.0)
for _k in range(0, len(_y) - 4096, 4096):
    an.feed(_y[_k:_k + 4096], _T0 + 20 + (_k + 4096) / RATE)
_p = [an.phase(_T0 + 39.0 + d) for d in (0.0, 0.1, 0.2)]
assert type(an.t_beat) is float and type(an.period) is float, (type(an.t_beat), type(an.period))
assert len({round(x, 3) for x in _p}) == 3, _p
print(f"Ohne Vorgabe, dann mit: Raster bleibt float64, Phase läuft ({[round(x, 2) for x in _p]})")
print("Audioanalyse ok")
