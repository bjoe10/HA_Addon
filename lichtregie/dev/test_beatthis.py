#!/usr/bin/env python3
"""Test von Beat This im Add-on (beatthis.py, downbeat.py) und der Übernahme der „1“ in die Schlagzählung.

1. Worker-Prozess: Ton hin, Schläge zurück (synthetisches Stück, 120 BPM, Kick und Bass-Ton je Takt).
2. Schlagzählung: „1“-Schläge, die einen Schlag neben der gezählten „1“ liegen, verschieben den Takt.
Die Gleichheit mit dem Original (PyTorch) wurde mit musik-analyse geprüft: gleiche Schläge und „1“ auf 40 s
einer Aufnahme, Logits höchstens 0,04 daneben (float16-Gewichte).
Aufruf: python3 dev/test_beatthis.py
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import downbeat  # noqa: E402
from beatcount import BeatCounter  # noqa: E402

R, BPM = 44100, 120.0
BEAT = 60.0 / BPM
t = np.arange(int(24 * R)) / R
x = np.zeros_like(t)
bass = [55, 65.4, 49, 73.4]
for j in range(int(24 / BEAT)):
    i = int(j * BEAT * R)
    n = int(0.2 * R)
    ts = np.arange(n) / R
    seg = 0.8 * np.sin(2 * np.pi * (50 + 80 * np.exp(-ts * 30)) * ts) * np.exp(-ts * 15)
    seg += 0.3 * np.sin(2 * np.pi * bass[(j // 4) % 4] * 2 * ts) * np.exp(-ts * 3)
    x[i:i + n] += seg[: len(x) - i]
    h = int((j + 0.5) * BEAT * R)
    x[h:h + 2000] += 0.1 * np.random.default_rng(j).standard_normal(len(x[h:h + 2000]))
x = np.clip(x, -1, 1).astype(np.float32)

t0 = time.time()
beats, downs = downbeat.analyze(x)
took = time.time() - t0
step = np.median(np.diff(beats)) if len(beats) > 2 else 0
print(f"Beat This im Worker: {len(beats)} Schläge (Abstand {step:.3f} s, erwartet {BEAT:.3f}), {len(downs)} „1“, "
      f"{took:.1f} s für 24 s Ton")
assert len(beats) > 30 and abs(step - BEAT) < 0.02, "Schläge falsch"

c = BeatCounter()
for i in range(400):                               # gezählt wird einen Schlag zu weit
    now = 1000.0 + i / 40
    c.update(now, (now - 1000.0) / BEAT + 1, ((now - 1000.0) / BEAT) % 1.0, 0.0, 0.0, BPM)
true_ones = [1000.0 + k * 4 * BEAT for k in range(1, 5)]
s = c.model_anchor(now, true_ones, BPM)
b_true = (now - 1000.0) / BEAT
print(f"Takt-Anker aus Beat This: Verschiebung {s:+d}, Rest {(c.last_b - b_true) % 4:.2f}, {c.bar_info()}")
assert s == -1 and c.bar_model and abs(((c.last_b - b_true + 2) % 4) - 2) < 0.05
# Hängender Rechenprozess: nach TIMEOUT beenden, Fehler melden, beim nächsten Mal neu starten
import subprocess  # noqa: E402
real_worker, real_timeout = downbeat._worker, downbeat.TIMEOUT
hung = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],   # liest, antwortet nie
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
downbeat._PROC["p"], downbeat._worker, downbeat.TIMEOUT = hung, lambda: hung, 0.5
try:
    downbeat.analyze(x[:R])
    raise AssertionError("hängender Prozess nicht erkannt")
except RuntimeError as err:
    assert "antwortet nicht" in str(err) and hung.poll() is not None and downbeat._PROC["p"] is None, err
downbeat._worker, downbeat.TIMEOUT = real_worker, real_timeout
print("Hängender Rechenprozess wird beendet und neu gestartet")
print("Beat This ok")
