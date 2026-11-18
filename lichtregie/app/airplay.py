"""Metadaten vom AirPlay-Empfänger (shairport-sync, Metadaten-Pipe): Titel und die genaue Position im Lied.

Music Assistant schickt mit dem Ton Titel, Interpret und Fortschritt (RTP-Zeitstempel: Anfang, aktuelle Stelle,
Ende des Liedes). shairport-sync meldet außerdem jede Sekunde, welcher Abtastwert zu welcher Zeit ausgegeben wird
(„phbt“, Monotonuhr). Damit ist die Position im Lied auf wenige Millisekunden bekannt, im Takt des Tons, den die
Analyse bekommt. Die Spotify-Position aus HA lag dagegen bis 11 s daneben (sie zeigt, wie weit Spotify ist, nicht
was gerade erklingt).

Format der Pipe: <item><type>hex</type><code>hex</code><length>n</length><data encoding="base64">…</data></item>
"""
import base64
import os
import re
import threading
import time

RATE = 44100
ITEM = re.compile(rb"<item><type>([0-9a-f]{8})</type><code>([0-9a-f]{8})</code><length>(\d+)</length>"
                  rb"(?:\s*<data encoding=\"base64\">\s*([^<]*)</data>)?\s*</item>", re.S)
FRESH = 5.0               # so lange gilt eine Zeitmarke von shairport-sync („phbt“) als aktuell
LOCK = threading.Lock()
AP = {"titel": None, "interpret": None, "album": None, "dauer": None, "start": None, "ende": None,
      "prgr": None, "phbt": None, "spielt": False, "at": 0.0, "items": 0, "seit": None}


def _text(data):
    return data.decode("utf-8", "replace").strip("\x00").strip()


def handle(kind, code, data, now=None):
    """Ein Eintrag aus der Pipe (kind/code als 4-Zeichen-Text, data als Bytes)."""
    now = time.time() if now is None else now
    with LOCK:
        AP["items"] += 1
        AP["at"] = now
        if kind == "core":
            if code == "minm":
                title = _text(data)
                if title and title != AP["titel"]:
                    print(f"AirPlay: Titel „{title}“", flush=True)
                AP["titel"] = title or AP["titel"]
            elif code == "asar":
                AP["interpret"] = _text(data)
            elif code == "asal":
                AP["album"] = _text(data)
            elif code == "astm" and len(data) == 4:
                AP["dauer"] = int.from_bytes(data, "big") / 1000.0
        elif kind == "ssnc":
            if code == "prgr":
                # „Anfang/aktuell/Ende“ als RTP-Abtastwerte
                try:
                    start, cur, end = (int(x) for x in _text(data).split("/"))
                except ValueError:
                    return
                first = AP["start"] is None
                AP.update(start=start, ende=end, prgr=(cur, now), spielt=True)
                if first:
                    print(f"AirPlay: Fortschritt kommt an (Lied {((end - start) % (1 << 32)) / RATE:.0f} s, "
                          f"bei {((cur - start) % (1 << 32)) / RATE:.1f} s)", flush=True)
            elif code == "phbt":
                if AP["phbt"] is None:
                    print("AirPlay: Zeitmarken kommen an", flush=True)
                # „Abtastwert/Zeit in ns (Monotonuhr)“: zu dieser Zeit wird dieser Abtastwert ausgegeben
                try:
                    frame, ns = (int(x) for x in _text(data).split("/"))
                except ValueError:
                    return
                AP["phbt"] = (frame, now - (time.monotonic() - ns / 1e9))
            elif code in ("pbeg", "prsm"):
                AP["spielt"] = True
            elif code in ("pend", "pfls", "paus"):
                AP["spielt"] = False


def _frame_at(t):
    """Welcher RTP-Abtastwert zur Uhrzeit t ausgegeben wird (aus der jüngsten Zeitmarke), oder None."""
    phbt, prgr = AP["phbt"], AP["prgr"]
    if phbt is not None and abs(t - phbt[1]) < FRESH + 60.0 and time.time() - phbt[1] < FRESH:
        return phbt[0] + (t - phbt[1]) * RATE
    if prgr is not None:
        return prgr[0] + (t - prgr[1]) * RATE
    return None


def position(t):
    """Position im Lied (s) für den Ton, den die Analyse zur Uhrzeit t bekommt; None, wenn unbekannt."""
    with LOCK:
        if not AP["spielt"] or AP["start"] is None or time.time() - AP["at"] > 30.0:
            return None
        frame = _frame_at(t)
        if frame is None:
            return None
        # RTP-Zeitstempel sind 32 Bit und laufen über; Abstand modulo 2^32
        pos = ((int(frame) - AP["start"]) % (1 << 32)) / RATE
        length = ((AP["ende"] - AP["start"]) % (1 << 32)) / RATE if AP["ende"] is not None else None
        if length and pos > length + 2.0:
            return None
        return pos


def same_title(title):
    """Gehört der AirPlay-Titel zu diesem Titel (aus HA)? Groß-/Kleinschreibung egal."""
    with LOCK:
        mine = AP["titel"]
    return bool(mine and title) and mine.casefold() == str(title).casefold()


def status(now=None):
    now = time.time() if now is None else now
    pos = position(now)
    with LOCK:
        return {"titel": AP["titel"], "interpret": AP["interpret"], "spielt": AP["spielt"],
                "position": None if pos is None else round(pos, 1),
                "dauer": None if AP["start"] is None or AP["ende"] is None
                else round(((AP["ende"] - AP["start"]) % (1 << 32)) / RATE),
                "zeitmarke": AP["phbt"] is not None and now - AP["phbt"][1] < FRESH,
                "eintraege": AP["items"], "vor_s": int(now - AP["at"]) if AP["at"] else None}


def feed(buf, chunk, now=None):
    """Bytes aus der Pipe anhängen, vollständige Einträge verarbeiten; Rückgabe: der unvollständige Rest."""
    buf += chunk
    last = 0
    for m in ITEM.finditer(buf):
        kind = bytes.fromhex(m.group(1).decode()).decode("latin-1")
        code = bytes.fromhex(m.group(2).decode()).decode("latin-1")
        data = base64.b64decode(m.group(4)) if m.group(4) else b""
        handle(kind, code, data, now)
        last = m.end()
    rest = buf[last:]
    return rest[-65536:]          # nie unbegrenzt wachsen (Cover-Bilder sind abgeschaltet)


def reader(path, stop=None):
    """Liest die Metadaten-Pipe (zum Lesen und Schreiben geöffnet, wie die Ton-Pipe: kein Dateiende)."""
    while stop is None or not stop.is_set():
        try:
            if not os.path.exists(path):
                os.mkfifo(path)
            fd = os.open(path, os.O_RDWR)
        except OSError as err:
            print(f"AirPlay-Metadaten {path} nicht lesbar: {err}", flush=True)
            time.sleep(10.0)
            continue
        print(f"AirPlay-Metadaten: lese {path}", flush=True)
        AP["seit"] = time.time()
        buf = b""
        try:
            while stop is None or not stop.is_set():
                chunk = os.read(fd, 4096)
                if chunk:
                    buf = feed(buf, chunk)
        except OSError as err:
            print(f"AirPlay-Metadaten Fehler: {err}", flush=True)
            time.sleep(1.0)
        finally:
            os.close(fd)
