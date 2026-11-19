#!/usr/bin/env python3
"""Test der AirPlay-Metadaten (airplay.py): Pipe-Format in Stücken, Titel, Position mit Zeitmarke, Überlauf der
RTP-Zeitstempel, Ende der Wiedergabe. Aufruf: python3 dev/test_airplay.py"""
import base64, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import airplay
def item(kind, code, data=None):
    s = f"<item><type>{kind.encode().hex()}</type><code>{code.encode().hex()}</code><length>{len(data or b'')}</length>"
    if data is not None:
        s += f"\n<data encoding=\"base64\">\n{base64.b64encode(data).decode()}</data>"
    return (s + "</item>\n").encode()
now = time.time()
start = 4294967000 - 44100 * 10          # läuft gleich über 2^32
stream = (item("ssnc", "mdst") + item("core", "minm", "ich jogge".encode()) + item("core", "asar", b"Haller")
          + item("ssnc", "pbeg") + item("ssnc", "prgr", f"{start}/{start + 44100 * 30}/{(start + 44100 * 128) % (1 << 32)}".encode()))
ns = int(time.monotonic() * 1e9)
frame = (start + 44100 * 31) % (1 << 32)
stream += item("ssnc", "phbt", f"{frame}/{ns}".encode())
buf = b""
for i in range(0, len(stream), 37):                 # in kleinen Stücken, Einträge zerrissen
    buf = airplay.feed(buf, stream[i:i + 37])
pos = airplay.position(time.time())
st = airplay.status()
print(st, pos)
assert abs(pos - 31.0) < 0.05 and st["dauer"] == 128
assert airplay.position(time.time() + 2.0) - pos > 1.9
airplay.handle("ssnc", "pend", b"")
assert airplay.position(time.time()) is None
# Liedwechsel: Music Assistant meldet den neuen Titel, bevor sein Ton kommt. Das laufende Lied gilt weiter (mit
# Position), bis der Ton am Lautsprecher (Ton-Vorlauf später als die Analyse) den Anfang des neuen erreicht
airplay.handle("ssnc", "pbeg", b"")
assert airplay.now_playing()["title"] == "ich jogge"
airplay.LEAD = 1.0
now = time.time()
airplay.handle("core", "minm", "morgen".encode())
airplay.handle("core", "asar", b"Mayberg")
assert airplay.position(time.time()) is not None, "Position des laufenden Liedes fehlt"
assert airplay.now_playing()["title"] == "ich jogge", "neuer Titel zu früh (noch kein Anfang bekannt)"
f_now = int(airplay._frame_at(now))
nstart = (f_now + 44100 * 3) % (1 << 32)              # Ton des neuen Liedes kommt in 3 s bei der Analyse an
airplay.handle("ssnc", "prgr", f"{nstart}/{nstart}/{(nstart + 44100 * 200) % (1 << 32)}".encode())
assert airplay.status()["naechster"] == "morgen"
assert airplay.now_playing(now + 3.5)["title"] == "ich jogge", "neuer Titel vor dem Lautsprecher"
lp = airplay.now_playing(now + 4.1)
assert lp["title"] == "morgen" and lp["artist"] == "Mayberg" and round(lp["duration"]) == 200, lp
assert airplay.status()["naechster"] is None
# Beim Verbinden meldet Music Assistant „Spotify Connect (…)“ als Titel, ohne Interpret und ohne Anfang: gilt
# spätestens nach WAIT_MAX, und ohne Interpret ist es kein Lied
airplay.handle("core", "minm", "Spotify Connect (Party modus)".encode(), now)
assert airplay.now_playing(now + 1)["title"] == "morgen"
assert airplay.now_playing(now + airplay.WAIT_MAX + 1) is None
print("Liedwechsel und Titel ohne Interpret ok")
print("AirPlay-Metadaten ok")
