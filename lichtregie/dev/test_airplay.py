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
assert abs(pos - 31.0) < 0.05 and airplay.same_title("Ich Jogge") and st["dauer"] == 128
assert airplay.position(time.time() + 2.0) - pos > 1.9
airplay.handle("ssnc", "pend", b"")
assert airplay.position(time.time()) is None
# Liedwechsel: neuer Titel → die Position des vorigen Liedes gilt nicht mehr, bis sein Fortschritt kommt
airplay.handle("ssnc", "pbeg", b"")
assert airplay.now_playing()["title"] == "ich jogge"
airplay.handle("core", "minm", "morgen".encode())
assert airplay.position(time.time()) is None, "Position des vorigen Liedes gilt weiter"
assert airplay.now_playing() is None, "ohne Interpret kein Lied"
airplay.handle("core", "asar", b"Mayberg")
airplay.handle("ssnc", "prgr", f"{1000}/{1000 + 44100 * 2}/{1000 + 44100 * 200}".encode())
lp = airplay.now_playing()
assert lp["title"] == "morgen" and lp["artist"] == "Mayberg" and round(lp["duration"]) == 200, lp
# Beim Verbinden meldet Music Assistant „Spotify Connect (…)“ als Titel, ohne Interpret: kein Lied
airplay.handle("core", "minm", "Spotify Connect (Party modus)".encode())
assert airplay.now_playing() is None
print("Liedwechsel und Titel ohne Interpret ok")
print("AirPlay-Metadaten ok")
