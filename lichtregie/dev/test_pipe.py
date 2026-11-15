#!/usr/bin/env python3
"""Test des Pipe-Lesers wie mit shairport-sync: Der Schreiber öffnet die Pipe nicht blockierend (schlägt ohne
Leser fehl), schreibt Ton, schließt sie beim Liedwechsel und öffnet sie sofort wieder. Es darf nichts verloren
gehen. Aufruf: python3 dev/test_pipe.py
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import audio  # noqa: E402

path = os.path.join(tempfile.mkdtemp(), "test.pcm")
os.mkfifo(path)
an = audio.Analyzer()
threading.Thread(target=audio.reader, args=(an, path), daemon=True).start()
time.sleep(0.3)

t = np.arange(int(audio.RATE * 0.5)) / audio.RATE
tone = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
pcm = np.repeat(tone[:, None], 2, axis=1).tobytes()
for song in range(5):                          # fünf Lieder, jedes mit eigenem Öffnen/Schließen
    fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)   # wie shairport: ENXIO, wenn kein Leser da ist
    before = an.data_at
    os.write(fd, pcm[:60000])
    os.close(fd)
    time.sleep(0.15)
    assert an.data_at > before, f"Lied {song + 1}: nichts angekommen"
assert an.signal(an.data_at), "Ton nicht als Signal erkannt"
print("Pipe ok: 5 Liedwechsel ohne Lücke")
