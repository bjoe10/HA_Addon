#!/usr/bin/env python3
"""Oberfläche lokal ansehen, ohne Geräte: kein Art-Net, kein HA. Die Party „läuft“ mit einem Testlied,
damit Startseite, Vorschau und Status etwas zeigen. Aufruf: python3 dev/vorschau.py  → http://localhost:8766
"""
import os
import sys
import tempfile
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ["LICHTREGIE_DATA"] = tempfile.mkdtemp()
os.environ["LICHTREGIE_HA_CONFIG"] = os.environ["LICHTREGIE_DATA"]
os.environ["LICHTREGIE_HA_API"] = "http://127.0.0.1:9"
os.environ["LICHTREGIE_GERAETE"] = "switch.moving_head_1 switch.moving_head_2 input_boolean.astronaut"
os.environ["LICHTREGIE_LASER_SWITCH"] = "switch.rgb_laser"
for name in ("LICHTREGIE_PLAYER", "LICHTREGIE_ALLOWED_CLIENTS", "LICHTREGIE_AUDIO_PIPE"):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import engine  # noqa: E402
import ha  # noqa: E402
import party  # noqa: E402
import server  # noqa: E402

ha.call = lambda *a, **k: True                                   # keine Aufrufe nach außen
ha.states = lambda entities: {e: ("on" if party.PARTY["on"] else "off") for e in entities}
SONG = {"title": "Testlied", "artist": "Vorschau", "id": "vorschau-1", "duration": 240, "playing": True}
T0 = time.time()
ha.now_playing = lambda: dict(SONG, pos=(time.time() - T0) % 240)
engine.tempo = lambda title, artist: {"bpm": 126, "energy": 0.85, "key": "A", "valence": 0.6}

if __name__ == "__main__":
    import threading
    party.SETTINGS["automatik"] = False
    threading.Thread(target=party.loop, daemon=True).start()
    if "--aus" not in sys.argv:
        party.start("Vorschau")
    port = int(os.environ.get("PORT", "8766"))
    print(f"Vorschau auf http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), server.Handler).serve_forever()
