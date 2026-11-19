"""Metadaten vom AirPlay-Empfänger (shairport-sync, Metadaten-Pipe): Titel und die genaue Position im Lied.

Music Assistant schickt mit dem Ton Titel, Interpret und Fortschritt (RTP-Zeitstempel: Anfang, aktuelle Stelle,
Ende des Liedes). shairport-sync meldet außerdem jede Sekunde, welcher Abtastwert zu welcher Zeit ausgegeben wird
(„phbt“, Monotonuhr). Damit ist die Position im Lied auf wenige Millisekunden bekannt, im Takt des Tons, den die
Analyse bekommt. Die Spotify-Position aus HA lag dagegen bis 11 s daneben (sie zeigt, wie weit Spotify ist, nicht
was gerade erklingt).

Music Assistant schickt Titel und Fortschritt des nächsten Liedes, sobald es dessen Ton in den Puffer schiebt: einige
Sekunden, bevor er erklingt. Ein neuer Titel wartet deshalb als „nächster“, bis der Ton an seinem Anfang (RTP) ist.

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
WAIT_MAX = 20.0           # so lange wartet ein neuer Titel höchstens auf seinen Anfang
LEAD = 0.0                # Ton-Vorlauf (engine): der Lautsprecher spielt den Ton so viel später als die Analyse
SONG = ("titel", "interpret", "album", "dauer", "start", "ende", "prgr")
AP = {"titel": None, "interpret": None, "album": None, "dauer": None, "start": None, "ende": None,
      "prgr": None, "phbt": None, "spielt": False, "at": 0.0, "items": 0, "seit": None, "next": None}


def _text(data):
    return data.decode("utf-8", "replace").strip("\x00").strip()


def handle(kind, code, data, now=None):
    """Ein Eintrag aus der Pipe (kind/code als 4-Zeichen-Text, data als Bytes)."""
    now = time.time() if now is None else now
    with LOCK:
        AP["items"] += 1
        AP["at"] = now
        song = AP["next"] or AP           # Angaben nach einem neuen Titel gehören zu ihm
        if kind == "core":
            if code == "minm":
                title = _text(data)
                if title and title != song["titel"]:
                    print(f"AirPlay: Titel „{title}“ (gilt ab seinem ersten Ton)", flush=True)
                    # Neues Lied: wartet als nächstes, das laufende bleibt mit seiner Position, bis der Ton so weit ist
                    AP["next"] = dict.fromkeys(SONG, None) | {"titel": title, "at": now}
            elif code == "asar":
                song["interpret"] = _text(data)
            elif code == "asal":
                song["album"] = _text(data)
            elif code == "astm" and len(data) == 4:
                song["dauer"] = int.from_bytes(data, "big") / 1000.0
        elif kind == "ssnc":
            if code == "prgr":
                # „Anfang/aktuell/Ende“ als RTP-Abtastwerte
                try:
                    start, cur, end = (int(x) for x in _text(data).split("/"))
                except ValueError:
                    return
                first = song["start"] is None
                song.update(start=start, ende=end, prgr=(cur, now))
                AP["spielt"] = True
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


def _switch(t):
    """Den wartenden Titel übernehmen, sobald der Ton (Lautsprecher, t = jetzt) an seinem Anfang ist. Ohne frische
    Zeitmarke (z. B. nach Überspringen, Ton steht) oder nach WAIT_MAX sofort."""
    nxt = AP["next"]
    if nxt is None:
        return
    phbt = AP["phbt"]
    frame = phbt[0] + (t - LEAD - phbt[1]) * RATE if phbt is not None and time.time() - phbt[1] < FRESH else None
    if frame is not None and t - nxt["at"] < WAIT_MAX:
        if nxt["start"] is None:
            return                                       # Fortschritt (Anfang) noch nicht da
        if (int(frame) - nxt["start"]) % (1 << 32) >= (1 << 31):
            return                                       # Anfang liegt noch in der Zukunft
    AP.update({k: nxt[k] for k in SONG})
    AP["next"] = None
    print(f"AirPlay: jetzt „{AP['titel']}“ ({t - nxt['at']:.1f} s nach dem Titel)", flush=True)


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
        _switch(time.time())
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


def now_playing(now=None):
    """Das laufende Lied wie bisher aus HA: {title, artist, duration, pos (s, Ton der Analyse jetzt), playing} oder
    None. Ohne Interpret ist es kein Lied (beim Verbinden meldet Music Assistant „Spotify Connect (…)“ als Titel)."""
    now = time.time() if now is None else now
    pos = position(now)
    with LOCK:
        _switch(now)
        if not AP["titel"] or not AP["interpret"] or now - AP["at"] > 600.0:
            return None
        length = None if AP["start"] is None or AP["ende"] is None else ((AP["ende"] - AP["start"]) % (1 << 32)) / RATE
        return {"title": AP["titel"], "artist": AP["interpret"], "id": None, "duration": length, "pos": pos,
                "playing": AP["spielt"] and now - AP["at"] < 5.0, "source": "AirPlay"}


def status(now=None):
    now = time.time() if now is None else now
    pos = position(now)
    with LOCK:
        return {"titel": AP["titel"], "interpret": AP["interpret"], "spielt": AP["spielt"],
                "position": None if pos is None else round(pos, 1),
                "dauer": None if AP["start"] is None or AP["ende"] is None
                else round(((AP["ende"] - AP["start"]) % (1 << 32)) / RATE),
                "zeitmarke": AP["phbt"] is not None and now - AP["phbt"][1] < FRESH,
                "naechster": AP["next"]["titel"] if AP["next"] else None,
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
