#!/usr/bin/env python3
"""Test der Schlagzählung (Takt und Phrase).

Teil 1: BeatCounter allein, mit genauer Phase und falscher HA-Position (+5 Schläge, ±0,5 Schlag Zittern).
Teil 2: Ganze Kette mit synthetischem Lied: Abschnitte à 32 Schläge mit wechselndem Klang, Break und Drop.
Erwartet: Nach Drop/Phrasenwechsel liegt die Zählung auf dem echten Raster; sie springt nie außer bei Korrekturen.
Aufruf: python3 dev/test_beatcount.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import audio  # noqa: E402
from beatcount import BeatCounter  # noqa: E402

BPM = 124.0
BEAT = 60.0 / BPM
OFFSET = 0.137
rng = np.random.default_rng(3)


def ha_pos(b_true, t, wrong):
    """HA-Position: um `wrong` Schläge daneben, alle 2 s ein neuer Fehler bis ±0,5 Schlag."""
    jit = np.random.default_rng(int(t // 2)).uniform(-0.5, 0.5)
    return b_true + wrong + jit


def check_jumps(trace):
    """Zwischen Bildern darf b nur um den Zeitfortschritt wachsen (außer an Korrekturstellen)."""
    jumps = []
    for (t0, b0), (t1, b1) in zip(trace, trace[1:]):
        step = b1 - b0 - (t1 - t0) / BEAT
        if abs(step) > 0.2:
            jumps.append((round(t1, 2), round(step, 2)))
    return jumps


# --- Teil 1: Zähler allein ---------------------------------------------------------------------------
def part1(wrong, drop_beat):
    c = BeatCounter()
    trace = []
    t0 = 500.0
    for i in range(int(60 * 40)):
        t = t0 + i / 40
        b_true = (t - t0) / BEAT
        drop_at = t0 + drop_beat * BEAT if b_true >= drop_beat + 0.5 else 0.0
        b = c.update(t, ha_pos(b_true, t, wrong), b_true % 1.0, drop_at, 0.0, BPM)
        trace.append((t, b))
    err = trace[-1][1] - (trace[-1][0] - t0) / BEAT
    return err, check_jumps(trace), [e[1] for e in c.events]


for wrong, drop_beat in ((5, 64), (-7, 96), (3, 96)):
    err, jumps, ev = part1(wrong, drop_beat)
    print(f"HA {wrong:+d} Schläge daneben, Drop bei Schlag {drop_beat}: Restfehler {err:+.2f}, "
          f"Sprünge {jumps}, Ereignisse {ev}")
    assert abs(err) < 0.05, "Zählung nicht auf dem Raster"
    assert len(jumps) == len(ev), "Sprung ohne Korrektur"

# ohne Audio: HA durchreichen
c = BeatCounter()
assert abs(c.update(1.0, 10.3) - 10.3) < 1e-9

# --- Teil 2: ganze Kette -----------------------------------------------------------------------------
RATE = audio.RATE
SECTIONS = ["intro", "voll", "break", "drop", "anders"]          # je 32 Schläge


def song():
    total = OFFSET + 32 * len(SECTIONS) * BEAT + 1.0
    t = np.arange(int(total * RATE)) / RATE
    x = np.zeros_like(t)
    for k, name in enumerate(SECTIONS):
        a, b = OFFSET + 32 * k * BEAT, OFFSET + 32 * (k + 1) * BEAT
        m = (t >= a) & (t < b)
        tt = t[m]
        pad = {"intro": 220, "voll": 330, "break": 440, "drop": 165, "anders": 587}[name]
        x[m] += 0.08 * np.sin(2 * np.pi * pad * tt)
        if name in ("voll", "drop"):
            x[m] += 0.05 * np.sign(np.sin(2 * np.pi * 880 * tt))       # helle Lead-Fläche
        if name == "anders":
            x[m] += 0.04 * rng.standard_normal(m.sum())                 # Rauschteppich
        for j in range(32):
            bt = a + j * BEAT
            i = int(bt * RATE)
            if name != "break":
                n = int(0.15 * RATE)
                ts = np.arange(n) / RATE
                kick = 0.9 * np.sin(2 * np.pi * (55 + 60 * np.exp(-ts * 30)) * ts) * np.exp(-ts * 18)
                x[i:i + n] += kick[: len(x) - i]
            if name in ("voll", "drop", "anders"):
                h = int((bt + BEAT / 2) * RATE)
                n = int(0.04 * RATE)
                x[h:h + n] += 0.15 * rng.standard_normal(n) * np.exp(-np.arange(n) / RATE * 80)
    return np.clip(x, -1, 1).astype(np.float32)


x = song()
an = audio.Analyzer()
an.set_bpm_hint(BPM)
c = BeatCounter()
t0 = 2000.0
trace, changes = [], []
chunk = 1102                                   # ~25 ms je Bild wie im Server (40 fps)
for i in range(0, len(x), chunk):
    part = x[i:i + chunk]
    now = t0 + (i + len(part)) / RATE
    an.feed(part, now)
    if not an.signal(now):
        continue
    b_true = (now - t0 - OFFSET) / BEAT
    frac = an.phase(now) if an.phase_ok(now) else None
    b = c.update(now, ha_pos(b_true, now, 5), frac, an.drop_at, an.change_at, BPM)
    trace.append((now, b, b_true))
    if an.change_at and (not changes or changes[-1] != an.change_at):
        changes.append(an.change_at)

ch_beats = [round((ct - t0 - OFFSET) / BEAT, 1) for ct in changes]
print(f"Phrasenwechsel erkannt bei Schlag {ch_beats} (echt: 32, 64, 96, 128)")
print(f"Drop erkannt bei Schlag {(an.drop_at - t0 - OFFSET) / BEAT:.1f} (echt: 96)")
print(f"Korrekturen: {[e[1] for e in c.events]}")
end_err = [b - bt for t, b, bt in trace if (t - t0 - OFFSET) / BEAT > 100]
print(f"Fehler nach dem Drop: median {np.median(end_err):+.2f}, max {max(map(abs, end_err)):.2f} Schläge")
jumps = check_jumps([(t, b) for t, b, _ in trace])
print(f"Sprünge: {jumps}")
assert max(map(abs, end_err)) < 0.3, "Nach dem Drop nicht auf dem Raster"
hits = sum(any(abs(cb - g) <= 3 for cb in ch_beats) for g in (32, 64, 96, 128))
assert hits >= 3, "zu wenige Phrasenwechsel erkannt"

# --- Teil 3: Audio-Zeit läuft zu langsam (am Gerät gesehen, 0.8.10) ----------------------------------
# Die Audiophase läuft mit 73 % der echten Geschwindigkeit, HA stimmt. Erwartet: Nach zwei Korrekturen zählt
# das Lied nach HA weiter und bleibt in der Nähe der echten Position, statt stehen zu bleiben.
c = BeatCounter()
t0 = 3000.0
for i in range(90 * 40):
    t = t0 + i / 40
    b_true = (t - t0) / BEAT
    b = c.update(t, ha_pos(b_true, t, 0), (b_true * 0.73) % 1.0, 0.0, 0.0, BPM)
ev = [e[1] for e in c.events]
print(f"Audio zu langsam: nach 90 s Fehler {b - b_true:+.1f} Schläge, Ereignisse {ev}")
assert c.audio_off, "Audio-Zählung nicht abgeschaltet"
assert abs(b - b_true) < 2.0, "Zählung läuft nicht mit der Musik"

# --- Teil 4: Leser und Pegel ---------------------------------------------------------------------------
# Ungerade Leseblöcke dürfen den Ton nicht verschieben (früher: Rest verworfen → Rauschen)
pcm = (np.clip(x[: RATE * 4], -1, 1) * 32767).astype("<i2")
pcm = np.repeat(pcm, 2).tobytes()
a1, a2 = audio.Analyzer(), audio.Analyzer()
a1.feed_pcm(pcm, 10.0)
pos = 0
for size in [1001, 2047, 3, 4093, 517] * 1000:
    if pos >= len(pcm):
        break
    a2.feed_pcm(pcm[pos:pos + size], 10.0)
    pos += size
assert abs(a1.level - a2.level) < 1e-6 and abs(a1.bass_peak - a2.bass_peak) < 1e-6, "ungerade Blöcke verschieben den Ton"
print("Leser: ungerade Blöcke ok")

# Eine zu laute Stelle darf das nächste Stück nicht dauerhaft zum „Break“ machen
an = audio.Analyzer()
loud = (np.sin(2 * np.pi * 60 * np.arange(RATE) / RATE) * 0.99).astype(np.float32)
an.feed(loud, 1.0)
quiet = x[RATE * 20: RATE * 60] * 0.1
for i in range(0, len(quiet), 4410):
    an.feed(quiet[i:i + 4410].astype(np.float32), 1.0 + (i + 4410) / RATE)
print(f"Nach lauter Stelle: Break {an.break_on}")
assert not an.break_on, "Break bleibt nach lauter Stelle hängen"
an.feed(loud, 50.0)
an.new_song()
assert not an.break_on and an.bass_peak <= an.bass + 1e-6, "neues Lied setzt die Pegel nicht zurück"


# --- Teil 5: die „1“ im Takt aus dem Klangwechsel ------------------------------------------------------
# Kick auf jedem Schlag (kein Hinweis auf die „1“), Akkord und Bass-Ton wechseln auf jeder „1“. HA liegt um
# `wrong` Schläge daneben. Erwartet: Die Zählung findet die „1“ (Rest modulo 4 ≈ 0) und bleibt dort.
def bar_song(bars=40):
    chords = [(220, 277, 330), (196, 247, 294), (175, 220, 262), (247, 311, 370)]
    bass = [55, 49, 44, 62]
    total = OFFSET + bars * 4 * BEAT + 1.0
    t = np.arange(int(total * RATE)) / RATE
    y = np.zeros_like(t)
    for k in range(bars):
        a, e = OFFSET + 4 * k * BEAT, OFFSET + 4 * (k + 1) * BEAT
        m = (t >= a) & (t < e)
        for f in chords[k % 4]:
            y[m] += 0.05 * np.sin(2 * np.pi * f * t[m])
        y[m] += 0.12 * np.sin(2 * np.pi * bass[k % 4] * 2 * t[m])
        for j in range(4):
            i = int((a + j * BEAT) * RATE)
            n = int(0.15 * RATE)
            ts = np.arange(n) / RATE
            kick = 0.9 * np.sin(2 * np.pi * (55 + 60 * np.exp(-ts * 30)) * ts) * np.exp(-ts * 18)
            y[i:i + n] += kick[: len(y) - i]
    return np.clip(y, -1, 1).astype(np.float32)


for wrong in (2, -1, 1):
    y = bar_song()
    an = audio.Analyzer()
    an.set_bpm_hint(BPM)
    c = BeatCounter()
    t0 = 5000.0 + wrong
    errs = []
    for i in range(0, len(y), 1102):
        part = y[i:i + 1102]
        now = t0 + (i + len(part)) / RATE
        an.feed(part, now)
        if not an.signal(now):
            continue
        b_true = (now - t0 - OFFSET) / BEAT
        locked = an.phase_ok(now)
        frac = an.phase(now) if locked else None
        ch = an.changes_since(c.seen_bc) if locked else None
        b = c.update(now, b_true + wrong, frac, 0.0, 0.0, BPM, ch)
        if b_true > 100:
            errs.append(b - b_true)
    off = [((e + 2) % 4) - 2 for e in errs]
    print(f"„1“ aus dem Klang, HA {wrong:+d} daneben: Rest modulo 4 max {max(map(abs, off)):.2f}, "
          f"{c.bar_info()}, Ereignisse {[e[1] for e in c.events]}")
    assert c.bar_locked and max(map(abs, off)) < 0.3, "„1“ nicht gefunden"

# Von Hand gesetzt: der Takt-Anker greift nicht mehr ein
c = BeatCounter()
c.shift(1, 0.0)
assert c.bar_manual and c.bar_info()["quelle"] == "von Hand"
print("Schlagzählung ok")
