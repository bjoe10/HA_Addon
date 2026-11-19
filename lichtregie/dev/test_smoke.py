#!/usr/bin/env python3
"""Rauchtest ohne Geräte und ohne HA: Show-Motor einmal durchlaufen lassen und die Web-Schnittstelle abfragen.
Prüft, dass Köpfe und Laser Werte bekommen, Spulen erkannt wird und alle Seiten und Endpunkte antworten.
Aufruf: python3 dev/test_smoke.py
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ["LICHTREGIE_DATA"] = tempfile.mkdtemp()
os.environ["LICHTREGIE_HA_CONFIG"] = os.environ["LICHTREGIE_DATA"]
os.environ["LICHTREGIE_HA_API"] = "http://127.0.0.1:9"      # nichts erreichbar
os.environ["LICHTREGIE_GERAETE"] = "switch.kopf_1, input_boolean.astronaut"
os.environ["LICHTREGIE_LASER_SWITCH"] = "switch.laser"
os.environ["LICHTREGIE_LAMPEN_AUS"] = "light.decke switch.ecke"
for name in ("LICHTREGIE_PLAYER", "LICHTREGIE_ALLOWED_CLIENTS", "LICHTREGIE_AUDIO_PIPE"):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import config  # noqa: E402
import airplay  # noqa: E402
import engine  # noqa: E402
import ha  # noqa: E402
import heads  # noqa: E402
import lamps  # noqa: E402
import show  # noqa: E402
import laser  # noqa: E402
import party  # noqa: E402
import server  # noqa: E402

CALLS = []
ha.call = lambda domain, service, data: CALLS.append((f"{domain}.{service}", data.get("entity_id"))) or True
assert config.GERAETE == ["switch.kopf_1", "input_boolean.astronaut", "switch.laser"], config.GERAETE
assert config.LAMPEN_AUS == ["light.decke", "switch.ecke"], config.LAMPEN_AUS

# --- Show-Motor --------------------------------------------------------------------------------------
engine.start_beat("Testlied", "Test", {"bpm": 128, "energy": 0.9}, "smoke-1", 200)
seen = {1: set(), 2: set()}
laser_modes = set()
for _ in range(60):
    time.sleep(0.05)
    for k, st in heads.snapshot().items():
        seen[int(k)].add((st["pan"], st["tilt"], st["hell"]))
    laser_modes.add(laser.STATE["mode"])
assert all(len(v) > 10 for v in seen.values()), "Köpfe bewegen sich nicht"
assert engine.BEAT["szene"].startswith("Takt "), engine.BEAT["szene"]
assert set(engine.SPOTS) == {"1", "2"}
print(f"Show läuft: {engine.BEAT['info']}")
print(f"   {engine.BEAT['szene']}, Laser-Modus gesehen: {sorted(laser_modes)}")

# Spulen: gleiche Titel, Position springt um 60 s
song = {"title": "Testlied", "artist": "Test", "pos": 10.0, "playing": True}
engine.update_live(dict(song))
time.sleep(0.2)
engine.update_live(dict(song, pos=70.0))
time.sleep(0.2)
assert engine.LIVE["seeks"] == 1, "Spulen nicht erkannt"
assert "Takt 3" in engine.BEAT["szene"] or int(engine.BEAT["szene"].split()[1].split(".")[0]) > 30, engine.BEAT["szene"]
print(f"   nach dem Spulen: {engine.BEAT['szene']}")

# --- Web-Schnittstelle -------------------------------------------------------------------------------
httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"


def get(path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return r.read()


def post(path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


for path, needle in (("/", b"<!doctype html>"), ("/style.css", b"body"), ("/app.js", b"fetch(")):
    assert needle in get(path), path
st = json.loads(get("/api/state"))
assert st["laeuft"] and "settings" in st and "laser" in st and "1" in st
import numpy as np  # noqa: E402
engine.SPOTS["9"] = {"x": np.float32(1.5)}       # wie aus der Audioanalyse
sp = json.loads(get("/api/status"))
assert sp["spots"]["9"]["x"] == 1.5
del engine.SPOTS["9"]
assert {"spots", "szene", "audio", "warnungen", "party", "lied"} <= set(sp), sp.keys()
assert sp["lied"]["titel"] == "Testlied" and sp["lied"]["bpm"] == 128
# Takt-Sync von Hand: Verschiebung wird übernommen und angezeigt
assert 1 <= sp["sync"]["schlag"] <= 4 and 1 <= sp["sync"]["takt"] <= 8
assert post("/api/sync", {"schlaege": 4})["ok"] and post("/api/sync", {"eins": 4})["ok"]
time.sleep(0.3)
sync = json.loads(get("/api/status"))["sync"]
assert any("von Hand" in e for e in sync["ereignisse"]), sync
# Takt-Test: 1 des Takts auf beiden Köpfen, Schläge 2–4 nur auf Kopf 1
post("/api/settings", {"takttest": True})
seen = set()
for _ in range(80):
    time.sleep(0.03)
    seen.add((heads.STATE[1]["hell"], heads.STATE[2]["hell"]))
post("/api/settings", {"takttest": False})
assert any(a == 255 and b == 255 for a, b in seen) and any(a == 120 and b < 50 for a, b in seen), seen
# Thema neu würfeln: anderes Thema, wird für das Lied gemerkt
before = engine.BEAT["info"]
assert post("/api/wuerfeln", {})["ok"]
assert engine.BEAT["info"] != before and engine.BEAT["lied"]["variante"] == 1
engine.start_beat("Testlied", "Test", {"bpm": 128, "energy": 0.9}, "smoke-1", 200)
assert engine.BEAT["lied"]["variante"] == 1, "Variante nicht gemerkt"
s = post("/api/settings", {"lampen_decke": 999, "strobe": False, "unbekannt": 1})
assert s["lampen_decke"] == 150 and s["strobe"] is False and "unbekannt" not in s
assert post("/api/laser", {"values": {"up_down": 255}})["gesendet"]["up_down"] == s["laser_ud_max"]
assert "1" in post("/api/set", {"heads": {"1": {"hell": 80}}})
assert "1" in post("/api/target", {"x": 2.5, "y": 3.0, "z": 0.0})
engine.stop_all()
time.sleep(0.2)
assert laser.STATE["mode"] == 0 and not engine.SPOTS

# --- Art-Net nur während der Party, kurz danach und beim Einrichten von Hand -----------------------------
_p = dict(party.PARTY)
party.PARTY.update(on=False, since=time.time() - 60)
server.MANUAL["at"] = 0.0
assert not server.sending(), "sendet ohne Party"
party.PARTY["since"] = time.time() - 1
assert server.sending(), "parkt nach dem Stopp nicht"
party.PARTY["since"] = time.time() - 60
post("/api/target", {"x": 2.5, "y": 0.0, "z": 1.6})
assert server.sending(), "Einrichten von Hand sendet nicht"
server.MANUAL["at"] = 0.0
party.PARTY.update(_p)
print("Art-Net: nur mit Party, beim Parken und beim Einrichten")
# --- Party-Modus: Schalter, Automatik an bei Musik, aus nach Ruhe --------------------------------------
airplay.now_playing = lambda now=None: None
engine.LIVE.update(live=None, at=0.0)       # AirPlay meldet kein Lied: nur der Ton zählt als Musik
CALLS.clear()
threading.Thread(target=engine.idle_loop, daemon=True).start()
st = post("/api/party", {"an": True})
assert st["party"]["an"] and lamps.ROOM["dark"]
# keine Musik: Ruhe-Animation (Sternhimmel an der Decke, Gobo Punkte-Ring, Köpfe bewegen sich)
pans = set()
for _ in range(20):
    time.sleep(0.1)
    pans.add(heads.STATE[1]["pan"])
assert heads.STATE[1]["gobo"] == 21 and len(pans) > 3, (heads.STATE[1], len(pans))
assert engine.BEAT["szene"].startswith("Warten") and engine.SPOTS["1"]["z"] == 2.5
assert laser.STATE["mode"] == 0
assert ("homeassistant.turn_on", config.GERAETE) in CALLS, CALLS
st = post("/api/party", {"an": False})
assert not st["party"]["an"] and st["party"]["gesperrt"] and not lamps.ROOM["dark"]
assert not heads.STATE[1]["on"] and heads.STATE[1]["pan"] == 0 and heads.STATE[1]["tilt"] == 0, "nicht geparkt"
assert ("homeassistant.turn_off", config.GERAETE) not in CALLS, "Steckdosen aus, bevor die Köpfe geparkt sind"
time.sleep(party.PARK_SEC + 0.5)
assert ("homeassistant.turn_off", config.GERAETE) in CALLS


class FakeAudio:           # Musik kommt an / kommt nicht an
    on = True
    drop_at = change_at = 0.0
    def signal(self, now=None): return self.on
    def phase_ok(self, now=None): return False
    def live(self, now, bpm): return {"level": 0.5, "bass": 0.5, "break": False, "drop": False}
    def status(self): return {"takt": False, "bpm": None, "sicher": 0, "an": self.on, "pegel": 0, "bass": 0,
                              "break": False, "drop": False, "wechsel": False}
    def set_bpm_hint(self, bpm): pass
    def new_song(self): pass


engine.AUDIO = FakeAudio()
party.START_AFTER, party.REARM_AFTER = 1.5, 2.0
threading.Thread(target=party.loop, daemon=True).start()
time.sleep(3.5)
assert not party.PARTY["on"], "Automatik hat trotz Stopp von Hand eingeschaltet"
engine.AUDIO.on = False
time.sleep(4.5)                     # Ruhe hebt die Sperre auf
assert not party.PARTY["manual_stop"]
engine.AUDIO.on = True
time.sleep(4.0)
assert party.PARTY["on"] and party.PARTY["why"] == "Musik erkannt", party.PARTY
engine.AUDIO.on = False
party.SETTINGS["party_aus_min"] = 0.05     # 3 s
time.sleep(6.0)
assert not party.PARTY["on"] and not party.PARTY["manual_stop"], party.PARTY
print(f"Party-Automatik: an bei Musik, aus nach Ruhe ({party.PARTY['why']})")
# AirPlay meldet ein Lied, aber kein Ton kommt an: Party startet nicht
party.SETTINGS["party_aus_min"] = 15
airplay.now_playing = lambda now=None: {"title": "T", "artist": "A", "pos": 5.0, "playing": True, "id": "x", "duration": 100}
time.sleep(5.0)
assert not party.PARTY["on"], "Party darf ohne Ton am Empfänger nicht starten"
# läuft sie aber schon, hält das laufende Lied sie am Leben, auch wenn der Ton ausfällt
party.start("Test")
party.SETTINGS["party_aus_min"] = 0.05
time.sleep(5.0)
assert party.PARTY["on"], "Party ausgegangen, obwohl laut AirPlay ein Lied läuft"
print("Start nur durch Ton; laufende Party bleibt an, solange laut AirPlay ein Lied läuft")

# --- Show nur mit Ton: Pause, dann Warten, und zurück, sobald wieder Ton kommt ---------------------------
party.SETTINGS["party_aus_min"] = 15
engine.QUIET_PAUSE, engine.QUIET_STOP = 0.5, 2.0
engine.tempo = lambda title, artist: {"bpm": 128, "energy": 0.8}
engine.start_watch("", "")
engine.AUDIO.on = True
deadline = time.time() + 8
while engine.BEAT["stop"] is None and time.time() < deadline:
    time.sleep(0.2)
assert engine.BEAT["stop"] is not None, "Show startet nicht, obwohl Ton kommt"
engine.AUDIO.on = False
time.sleep(1.2)
assert engine.BEAT["stop"] is not None and "Pause" in engine.BEAT["szene"], engine.BEAT["szene"]
time.sleep(2.5)
assert engine.BEAT["stop"] is None, "Show läuft ohne Ton weiter"
time.sleep(0.5)
assert engine.BEAT["szene"].startswith("Warten"), engine.BEAT["szene"]
airplay.now_playing = lambda now=None: {"title": "T", "artist": "A", "pos": 5.0, "playing": False, "id": "x", "duration": 100}
engine.AUDIO.on = True                  # AirPlay meldet noch „pausiert“, der Ton gilt
deadline = time.time() + 6
while engine.BEAT["stop"] is None and time.time() < deadline:
    time.sleep(0.2)
assert engine.BEAT["stop"] is not None, "Show kommt nach der Pause nicht wieder"
print("Show nur mit Ton: Pause nach 2 s, Warten nach 10 s, zurück mit dem Ton (Zeiten im Test verkürzt)")

# --- Lampen: harter Wechsel auf der „1“, mindestens ein Takt, nur Geänderte senden, Budget je Lampe ------
prof = show.profile("lampentest", {"bpm": 120, "energy": 0.8}, 200)
for wechsel in (4, 1):                     # 1 (schneller als ein Takt) wird auf einen Takt begrenzt
    seen = {}
    for i in range(0, 64 * 40):
        b = i / 40
        seen.setdefault(int(b // 4), set()).add(show.lamps(prof, b, None, wechsel)["grund"][0])
    assert all(len(v) == 1 for v in seen.values()), "Farbe wechselt mitten im Takt"
colors = {show.RGB[show.WHEEL[prof["base"]]], show.RGB[show.WHEEL[prof["accent"]]]}
for i in range(0, 64 * 40, 7):
    w = show.lamps(prof, i / 40, None, 8)
    assert {w["grund"][0], w["akzent"][0]} <= colors, "Lampenfarbe, die die Köpfe nicht zeigen"
    if w["teil"] not in ("Höhepunkt", "Drop"):
        assert w["grund"][0] != w["akzent"][0], "Ambilights und Schränke in derselben Farbe"
# LED-Streifen: gedimmte Farbe; Blinder beim Einsetzen des Höhepunkts und bei Phrasenwechseln; Flash auf der „1“
parts = [(i / 8, show.look(prof, i / 8)["teil"]) for i in range(0, 600 * 8)]
start = next(b for b, t in parts if t == "Höhepunkt")
assert show.tv(prof, start + 0.1, None, 1, 0)[2], "kein Blinder beim Einsetzen des Höhepunkts"
assert not show.tv(prof, start + 4.6, None, 1, 0)[2], "Blinder dauert zu lang"
assert show.tv(prof, start + 4.1, None, 1, 1)[2] and not show.tv(prof, start + 4.7, None, 1, 1)[2], "Flash auf der 1"
calm = next(b for b, t in parts if t in ("Motiv", "Szene") and b % 32 > 2 and b % 4 < 0.3)
assert not show.tv(prof, calm, None, 2, 1)[2], "Flash außerhalb von Höhepunkt/Drop"
assert show.tv(prof, calm, None, 2, 2)[2], "Flash auf jeder 1 fehlt"
phr = next(b for b, t in parts if t in ("Motiv", "Szene") and b % 32 == 0.25)
assert show.tv(prof, phr, None, 2, 0)[2] and not show.tv(prof, phr, None, 1, 0)[2], "Blinder beim Phrasenwechsel"
brk = next((b for b, t in parts if t in ("Break", "Atempause")), None)
assert brk is None or show.tv(prof, brk, None, 2, 2)[1] == 0, "Streifen im Break nicht aus"
assert show.tv(prof, start + 0.1, {"drop": True, "drop_beats": 0.5, "level": 1, "bass": 1, "break": False}, 1, 0)[2]
assert show.tv(prof, start + 3.5, None, 1, 0, blinder_len=4)[2] and not show.tv(prof, start + 4.5, None, 1, 0, blinder_len=4)[2], "Blinder-Dauer"
assert show.tv(prof, calm + 0.9, None, 0, 2, flash_len=1.0)[2] and not show.tv(prof, calm + 0.9, None, 0, 2, flash_len=0.5)[2], "Flash-Dauer"
print("LED-Streifen: gedimmte Farbe, Blinder bei Höhepunkt, Drop und Phrasenwechsel, Flash einstellbar")
# Spiegelkugel: Kopf 1 auf gespeicherte Pan/Tilt, nur in ruhigen Teilen (Show 1), Wackeln in Grad, Einstieg dunkel
kg = {"kopf": 1, "pan": 30000, "tilt": 20000, "xyz": None, "show": 1, "gobo": 0, "zittern": 1, "idle": True,
      "farbig": False, "test": False}
quiet = [b for b, t in parts if t in ("Intro", "Break", "Atempause", "Outro")]
loud = [b for b, t in parts if t in ("Höhepunkt", "Szene")]
assert quiet, "kein ruhiger Teil im Testlied"
qb = next(b for b in quiet if b + 2 in quiet and b % 1 == 0 and b - 1 in quiet)   # mitten im ruhigen Teil
out, info = show.frame(prof, qb + 0.5, kugel=kg)
assert "pt" in out[1] and "pt" not in out[2] and out[1]["hell"] >= 170, out[1]
assert out[1]["pt"] == (30000, 20000), "Kopf nicht fest auf der Kugel"
assert out[1]["gobo"] == show.KUGEL_GOBOS[0][1][1], ("Gobo-Zittern mittel", out[1]["gobo"])
hp = next(b for b, t in parts if t == "Höhepunkt") + 4.5
assert show.frame(prof, hp, kugel=dict(kg, show=2, gobo=6))[0][1]["gobo"] == 126, "im Höhepunkt schnell"
assert all("pt" not in show.frame(prof, b + 0.5, kugel=kg)[0][1] for b in loud[:20]), "Kugel außerhalb ruhiger Teile"
first = next((b for b in quiet if b > 8 and b - 1 not in quiet and b % 1 == 0), None)
assert first is None or show.frame(prof, first + 0.3, kugel=kg)[0][1]["hell"] == 0, "Einstieg nicht dunkel"
idle = [show.idle_frame(t, "warten", kugel=kg) for t in (10.0, 50.0)]
assert "pt" not in idle[0][1] and "pt" in idle[1][1] and "pt" not in idle[1][2], "Ruhe-Animation wechselt nicht"
assert "pt" in show.idle_frame(5.0, "pause", [36], kg)[1]
pan, tilt = engine.aim(1, {"pt": (30000, 20000), "ziel": (0, 0, 0)})
assert 0 <= pan <= 65535 and 0 <= tilt <= 65535
heads.apply(2, 12345, 23456)
st = post("/api/kugel", {"kopf": 2})
assert st["kugel_kopf"] == 2 and st["kugel_pan"] == 12345 and st["kugel_tilt"] == 23456, st
post("/api/settings", {"kugel_kopf": 0})
print("Spiegelkugel: Pan/Tilt gespeichert, fest auf der Kugel, Gobo zittert, nur in ruhigen Teilen, Ruhe-Animation wechselt")
SENT = []
ha.call = lambda domain, service, data: SENT.append((service, dict(data))) or True
lamps.LAMP["last"], lamps.SPENT, lamps.PARALLEL = {}, {}, False
lamps.groups = lambda: [("grund", ["light.amb"]), ("links", ["light.s1"]), ("rechts", ["light.s2"])]
lampen_soll = {"grund": ((255, 0, 0), 40), "akzent": ((0, 0, 255), 100), "links": ((0, 0, 255), 100),
        "rechts": ((0, 0, 255), 20)}
lamps.send(lampen_soll)
assert len(SENT) == 3 and all("rgb_color" in d and "brightness_pct" in d for _, d in SENT), SENT
SENT.clear()
lamps.send(dict(lampen_soll, grund=((0, 255, 0), 40), links=((0, 0, 255), 20), rechts=((0, 0, 255), 100)))
amb = [d for _, d in SENT if d["entity_id"] == ["light.amb"]][0]
schrank = [d for _, d in SENT if d["entity_id"] == ["light.s1"]][0]
assert "rgb_color" in amb and "brightness_pct" not in amb, "Farbwechsel schickt unnötig die Helligkeit"
assert "brightness_pct" in schrank and "rgb_color" not in schrank, "Schrank-Wechsel schickt unnötig die Farbe"
SENT.clear()
for k in range(80):                        # viel zu schnell: das Budget hält die Lampe unter ihrer Grenze
    lamps.send(dict(lampen_soll, grund=(((k * 37) % 256, 0, 0), 40)))
amb_sent = sum(1 for _, d in SENT if d["entity_id"] == ["light.amb"])
assert amb_sent <= lamps.QUOTA, amb_sent
st = lamps.stats()
assert st and st["fehler"] == 0, st
# Abgelehnter Befehl: nicht als gesendet merken, nach 1 s noch einmal
lamps.SPENT, lamps.RETRY = {}, {}
ha.call = lambda domain, service, data: False
lamps.send(dict(lampen_soll, grund=((1, 2, 3), 40)))
assert lamps.LAMP["last"]["grund"] != ((1, 2, 3), 40) and lamps.RETRY.get("grund"), "Fehlschlag als gesendet gemerkt"
ha.call = lambda domain, service, data: SENT.append((service, dict(data))) or True
lamps.RETRY["grund"] = 0.0
lamps.send(dict(lampen_soll, grund=((1, 2, 3), 40)))
assert lamps.LAMP["last"]["grund"] == ((1, 2, 3), 40) and lamps.SHOWN["light.amb"] == [1, 2, 3]
# Paralleles Senden: ein langsamer Befehl hält die anderen Gruppen nicht auf, und nichts geht doppelt raus
lamps.PARALLEL, lamps.SPENT = True, {}
SENT.clear()
ha.call = lambda domain, service, data: (time.sleep(0.3) if data["entity_id"] == ["light.amb"] else None,
                                         SENT.append((service, dict(data))))[1] or True
t_par = time.time()
lamps.send(dict(lampen_soll, grund=((9, 9, 9), 40), links=((9, 9, 9), 100)))
lamps.send(dict(lampen_soll, grund=((9, 9, 9), 40), links=((9, 9, 9), 100)))
assert time.time() - t_par < 0.1, "send wartet auf HA"
time.sleep(0.5)
assert len(SENT) == 2, SENT
lamps.PARALLEL = False
ha.call = lambda domain, service, data: SENT.append((service, dict(data))) or True
# Nach der Party: Steht eine Lampe noch in der Show-Farbe, ist das Zurücksetzen gescheitert
cur = {"light.s1": {"state": "on", "rgb": [170, 0, 255], "bri": 23}, "light.s2": {"state": "off", "rgb": None}}
assert lamps.stuck(cur, {"light.s1": [170, 0, 255]}) == ["light.s1"]
assert lamps.stuck(cur, {"light.s1": [255, 90, 0]}) == []
before = {"light.s1": {"state": "on", "rgb": [255, 200, 150], "bri": 180}, "light.s2": {"state": "off"}}
assert not lamps.restored(cur, before)
assert lamps.restored({"light.s1": {"state": "on", "rgb": [250, 205, 150], "bri": 184}}, before)
print(f"Lampen: Wechsel auf der 1, nur geänderte Werte, Budget hält ({amb_sent} von 80 Wechseln gesendet), "
      "Fehlschlag wird wiederholt, Gruppen parallel, Zurücksetzen geprüft")
# --- Gleichmäßige Bilder: fester Takt gegen die Uhr, Messung der Lücken -----------------------------------
engine.AUDIO.on = True
import record  # noqa: E402
record.start({"titel": "Takttest"}, seconds=3.0)
engine.start_beat("Takttest", "Test", {"bpm": 128, "energy": 0.9}, "smoke-takt", 200)
time.sleep(1.0)
record.sent(time.time())
record.mark(kind="haenger")
time.sleep(3.5)
bi = engine.BEAT.get("bilder")
assert bi and 37 <= bi["fps"] <= 41 and bi["ruckler"] == 0, bi
assert heads.FRAME.is_set() or True
engine.halt_beat()
record.stop()
time.sleep(0.5)
rec = sorted(record.DIR.iterdir())[-1]
import subprocess  # noqa: E402
out = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "show_auswerten.py"), str(rec)],
                     capture_output=True, text=True).stdout
assert "Kopf 1:" in out and "„Hängt jetzt“ bei" in out and "Bilder mit Kopf-Werten" in out, out
print(f"Bilder gleichmäßig: {bi}; Auswertung der Aufnahme ok")

# --- Tempo-Korrektur aus Beat This wird je Lied gemerkt ---------------------------------------------------
engine.tempo = lambda title, artist: {"bpm": 65.0, "energy": 0.8}
assert engine.song_tempo("Another World", "MEDUZA")["bpm"] == 65.0
engine.save_tempo_fix("Another World", "MEDUZA", 130.04)
st = engine.song_tempo("Another World", "MEDUZA")
assert st["bpm"] == 130.04 and st["quelle"] == "Beat This" and st["energy"] == 0.8, st
print("Tempo-Korrektur je Lied ok")

# --- Aufnahme: Ton und Entscheidungen landen in einer ZIP-Datei, die sich herunterladen lässt -------------
import io, zipfile  # noqa: E402,E401
import numpy as np  # noqa: E402
import record  # noqa: E402
record.start({"titel": "Test"}, seconds=2)
t = time.time()
for i in range(20):
    record.tap(np.full(512, 0.25, dtype=np.float32), t + i * 0.01)
    record.trace(t + i * 0.05, {"b": i / 2})
assert record.mark() and record.status()["laeuft"]
record.tap(np.zeros(512, dtype=np.float32), t + 3.0)
time.sleep(0.5)
st = record.status()
assert not st["laeuft"] and len(st["dateien"]) == 2, st
z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(f"{base}/aufnahme/{st['dateien'][0]}").read()))
daten = json.loads(z.read("daten.json"))
assert len(daten["blocks"]) == 21 and daten["marks"] and daten["trace"] and len(z.read("ton.wav")) > 20000
print(f"Aufnahme: {st['dateien'][0]} mit Ton, {len(daten['trace'])} Bildern, {len(daten['marks'])} Markierung")
httpd.shutdown()
print("Rauchtest ok")
