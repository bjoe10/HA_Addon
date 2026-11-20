#!/usr/bin/env python3
"""Lichtregie: Web-Server und Start (nur Standardbibliothek).

Im Add-on läuft er hinter HA-Ingress (Seitenleiste „Lichtregie“), lokal auf dem Mac über dev/run_local.sh.
Aufbau: party.py (Hauptschalter), engine.py (Show-Motor), show.py (Show-Regeln), heads.py/laser.py/lamps.py (Geräte),
audio.py + beatcount.py (Live-Audio und Schlagzählung), ha.py/tempo.py (Daten), web/ (Oberfläche).
"""
import json
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import airplay
import config
import engine
import ha
import heads
import lamps
import laser
import downbeat
import party
import record
import settings
from artnet import ART_PORT, FPS, artdmx
from settings import SETTINGS

WEB = Path(__file__).resolve().parent / "web"
SENT = deque(maxlen=1000)    # Zeitpunkte der Art-Net-Sendungen (für die Messung der Ruckler)
DROPPED = {}                 # Knoten → verworfene Pakete (Knoten aus oder nicht erreichbar)
MANUAL = {"at": 0.0}         # letzte Bedienung von Hand (Köpfe/Laser einrichten): dann wird auch ohne Party gesendet
MANUAL_SEC = 300.0
AFTER_STOP = party.PARK_SEC + 2.0   # nach dem Party-Stopp noch senden: Köpfe dunkel in die Parkposition


def sending(now=None):
    """Wird gesendet? Nur während der Party, kurz danach (Parken) und beim Einrichten von Hand. Sonst sind die
    Steckdosen der Köpfe und des Lasers aus, und es gibt nichts zu steuern."""
    now = time.time() if now is None else now
    return ((party.PARTY["on"] or now - party.PARTY["since"] < AFTER_STOP
             or now - MANUAL["at"] < MANUAL_SEC) and not party.booting(now))
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}


def sender(stop):
    """Sendet die DMX-Puffer per Art-Net an die Nodes: direkt nach jedem fertigen Show-Bild (heads.FRAME), ohne Show
    spätestens alle 1/FPS Sekunden; nur solange sending() es erlaubt."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Nie warten: Ist ein Knoten aus (Steckdose der Köpfe nach der Party, Laser-Steckdose aus, Knoten bootet), sucht der
    # Pi ihn im Netz und hält die Pakete zurück; ist der Puffer voll, blockierte das Senden bis zu 1,7 s, und alle
    # Köpfe stockten mit. Jetzt wird ein Paket, das nicht sofort raus kann, verworfen; 25 ms später kommt das nächste
    sock.setblocking(False)

    def send(data, universe, node):
        try:
            sock.sendto(artdmx(universe, data, seq), (node, ART_PORT))
        except OSError:                  # BlockingIOError (Puffer voll), Host nicht erreichbar
            DROPPED[node] = DROPPED.get(node, 0) + 1

    seq = 1
    laser_off = 0             # nach dem Abschalten des Lasers in der Oberfläche noch so viele Bilder „aus“ senden
    while not stop.is_set():
        heads.FRAME.wait(1.0 / FPS)
        heads.FRAME.clear()
        if not sending():
            laser_off = 0
            continue
        SENT.append(time.time())
        record.sent(SENT[-1])
        for k, head in heads.HEADS.items():
            with head.lock:
                data = bytes(head.buf)
            send(data, config.UNIVERSE[k], config.NODES[k])
        if SETTINGS["laser"] or laser_off > 0:
            # Nur senden, wenn freigegeben; sonst behält HA den Laser. Beim Abschalten noch 1 s „aus“ senden: Der
            # Art-Net-Knoten hält sonst das letzte Bild, und der Laser zeigt die letzte Figur ohne Animation weiter
            if SETTINGS["laser"]:
                laser_off = FPS
            else:
                if laser_off == FPS:
                    laser.off()
                laser_off -= 1
            with laser.LOCK:
                data = bytes(laser.BUF)
            send(data, config.LASER[1], config.LASER[0])
        seq = (seq + 1) % 256 or 1
    sock.close()


def state():
    data = heads.snapshot()
    live = engine.LIVE.get("live")
    data.update(
        info=engine.BEAT["info"], laeuft=engine.BEAT["stop"] is not None, szene=engine.BEAT["szene"],
        erkannt=f"{live.get('title', '-')} ({time.time() - engine.LIVE['at']:.0f} s her)" if live else "noch nichts",
        ueberwachung=engine.WATCH["stop"] is not None, settings=SETTINGS, laser=laser.snapshot(),
        led=bool(config.LAMPEN_TV))
    return data


SLOW = {"at": 0.0, "data": {}}


def _slow(now):
    """Messwerte, die einmal pro Sekunde reichen. Die Oberfläche fragt 5-mal pro Sekunde; jedes Mal das
    Aufnahmeverzeichnis lesen und über Tausende Messwerte rechnen kostete Rechenzeit neben der Show."""
    if now - SLOW["at"] >= 1.0:
        SLOW.update(at=now, data={"senden": sending(now) and (g := heads.gaps(SENT)) and dict(g, verworfen=dict(DROPPED)) or None, "lampen": lamps.stats(now),
                                  "aufnahme": record.status(now), "beatthis": downbeat.status(), "airplay": airplay.status(now),
                                  "bilder": engine.BEAT.get("bilder")})
    return SLOW["data"]


def status():
    """Alles für die Startseite, mehrmals pro Sekunde abgefragt."""
    live = engine.LIVE.get("live")
    fresh = live is not None and time.time() - engine.LIVE["at"] < 20
    warn = [engine.AUDIO_WARN["text"]] if engine.AUDIO_WARN["text"] else []
    if party.PARTY["on"] and not fresh and time.time() - party.PARTY["since"] > 20:
        warn.append("AirPlay meldet keinen Titel (schickt Music Assistant keine Metadaten?). "
                    "Die Show läuft nur nach dem Audio.")
    return {"spots": engine.SPOTS, "szene": engine.BEAT["szene"], "info": engine.BEAT["info"],
            "audio": engine.AUDIO.status() if engine.AUDIO is not None else None,
            "party": party.status(), "lied": engine.BEAT["lied"], "sync": engine.BEAT["sync"],
            "fps": engine.BEAT.get("fps"), **_slow(time.time()),
            "spielt": bool(fresh and live.get("playing")),
            "titel": f"{live['title']} – {live['artist']}" if fresh else None,
            "warnungen": warn}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, data):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, data, code=200):
        # Werte aus der Audioanalyse sind teils numpy-Zahlen (float32); die als normale Zahlen senden
        self._send(code, "application/json",
                   json.dumps(data, default=lambda o: o.item() if hasattr(o, "item") else str(o)).encode("utf-8"))

    def _allowed(self):
        """Im Add-on (Host-Netzwerk) nur Anfragen über den HA-Ingress-Proxy annehmen."""
        if config.ALLOWED_CLIENTS and self.client_address[0] not in config.ALLOWED_CLIENTS:
            self._send(403, "text/plain", b"nur ueber Home Assistant")
            return False
        return True

    def do_GET(self):
        if not self._allowed():
            return
        if self.path in STATIC:
            name, ctype = STATIC[self.path]
            self._send(200, ctype, (WEB / name).read_bytes())
        elif self.path == "/api/state":
            self._json(state())
        elif self.path == "/api/status":
            self._json(status())
        elif self.path.startswith("/aufnahme/"):      # Aufnahme herunterladen
            data = record.read(self.path.rsplit("/", 1)[1])
            if data is None:
                return self._send(404, "text/plain", b"nicht gefunden")
            self._send(200, "application/zip", data)
        else:
            self._send(404, "text/plain", b"nicht gefunden")

    def do_POST(self):
        if not self._allowed():
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, "text/plain", b"ungueltiges JSON")
        if self.path in ("/api/set", "/api/target", "/api/laser"):
            MANUAL["at"] = time.time()         # Einrichten von Hand: senden, auch ohne Party
        if self.path == "/api/set":            # einzelne Kopf-Kanäle von Hand
            for k, v in body.get("heads", {}).items():
                heads.apply(int(k), v.get("pan"), v.get("tilt"), v.get("on"), v.get("farbe"), v.get("gobo"),
                            v.get("strobe"), v.get("hell"))
            self._json(heads.snapshot())
        elif self.path == "/api/target":       # Punkt im Raumbild angetippt
            heads.aim_manual(float(body["x"]), float(body["y"]), float(body["z"]))
            self._json(heads.snapshot())
        elif self.path == "/api/kugel":        # dieser Kopf zeigt auf die Spiegelkugel: Pan/Tilt merken
            k = 2 if int(body.get("kopf", 1)) == 2 else 1
            snap = heads.snapshot()[str(k)]
            target = heads.LAST_TARGET["value"]
            SETTINGS.update(kugel_kopf=k, kugel_pan=snap["pan"], kugel_tilt=snap["tilt"],
                            kugel_xyz=[target["x"], target["y"], target["z"]] if target else None)
            settings.save()
            self._json(SETTINGS)
        elif self.path == "/api/save":
            self._json(heads.save_point())
        elif self.path == "/api/party":        # Party-Schalter
            if body.get("an"):
                party.start()
            else:
                party.stop()
            self._json(status())
        elif self.path == "/api/sync":         # Schlagzählung von Hand korrigieren
            if "schlaege" in body:
                engine.shift_beats(int(body["schlaege"]))
                self._json({"ok": True})
            else:
                self._json({"ok": engine.mark_one(32 if body.get("eins") == 32 else 4)})
        elif self.path == "/api/aufnahme":     # Aufnahme für die Fehlersuche: starten, stoppen, „1“ markieren
            if body.get("marke"):
                return self._json({"ok": record.mark()})
            if body.get("haenger"):
                return self._json({"ok": record.mark(kind="haenger")})
            if body.get("an"):
                record.start({"lied": engine.BEAT["lied"], "titel": status()["titel"],
                              "ton_vorlauf": SETTINGS["ton_vorlauf"], "offset": SETTINGS["offset"]})
            else:
                record.stop()
            self._json(record.status())
        elif self.path == "/api/geraete_neustart":   # Steckdosen aus und wieder ein
            self._json({"ok": party.restart_devices()})
        elif self.path == "/api/wuerfeln":     # neues Thema für das laufende Lied
            self._json({"ok": engine.reroll()})
        elif self.path == "/api/settings":
            changed = settings.update(body)
            laser.apply({})                    # neue Grenzen sofort anwenden
            if "nebel" in changed:             # Nebel ändert die Szenenauswahl
                engine.restart_beat()
            self._json(SETTINGS)
        elif self.path == "/api/laser":        # Laserkanäle von Hand
            if body.get("preset"):
                laser.apply(laser.PRESET)
            laser.apply(body.get("values", {}))
            self._json(laser.snapshot())
        elif self.path == "/api/laser_power":
            ok = bool(config.LASER_SWITCH) and ha.call(
                "switch", "turn_on" if body.get("on") else "turn_off", {"entity_id": config.LASER_SWITCH})
            self._json({"ok": ok})
        else:
            self._send(404, "text/plain", b"nicht gefunden")

    def log_message(self, *args):
        pass


def main():
    for k in heads.HEADS:        # Mitte, dunkel: hell werden die Köpfe erst mit der Party
        heads.apply(k, 32768, 32768, False)
    stop = threading.Event()
    threading.Thread(target=sender, args=(stop,), daemon=True).start()
    threading.Thread(target=lamps.lamp_loop, daemon=True).start()
    threading.Thread(target=party.loop, daemon=True).start()
    threading.Thread(target=engine.idle_loop, daemon=True).start()
    if engine.AUDIO is not None:
        engine.AUDIO.tap = record.tap
        threading.Thread(target=downbeat.loop, args=(engine,), daemon=True).start()
        threading.Thread(target=engine.audio_watch_loop, daemon=True).start()
        if config.AIRPLAY_META:
            threading.Thread(target=airplay.reader, args=(config.AIRPLAY_META,), daemon=True).start()
        if config.AUDIO_CMD:
            threading.Thread(target=engine.audio.reader_cmd, args=(engine.AUDIO, config.AUDIO_CMD), daemon=True).start()
        else:
            threading.Thread(target=engine.audio.reader, args=(engine.AUDIO, config.AUDIO_PIPE), daemon=True).start()
    source = f"Programm {config.AUDIO_CMD}" if config.AUDIO_CMD else f"Pipe {config.AUDIO_PIPE}"
    print(f"Audioanalyse: {'an, ' + source if engine.AUDIO is not None else 'aus'}", flush=True)
    print(f"Geräte der Party: {config.GERAETE or '-'}", flush=True)
    print(f"Lampen: Grundfarbe {config.LAMPEN_GRUND or '-'}, Akzent {config.LAMPEN_AKZENT or '-'}, "
          f"aus während der Party {config.LAMPEN_AUS or '-'}, LED-Streifen {config.LAMPEN_TV or '-'}", flush=True)
    for k in heads.HEADS:
        print(f"Kopf {k}: Node {config.NODES[k]}, Universe {config.UNIVERSE[k]}, Kanäle {config.LAYOUT[k]} "
              f"({config.HEADS_SOURCE[k]})", flush=True)
    print(f"Spotify-Player (nur für die Warnung „kein Audio“): {config.PLAYER or 'nicht eingestellt'}, "
          f"Tempo-Schlüssel: {'gesetzt' if config.freqblog_key() else 'fehlt'}", flush=True)
    print(f"Lichtregie läuft auf Port {config.PORT}", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", config.PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # Nur bei Strg+C (lokal). Im Add-on endet der Prozess sofort; der Party-Stand bleibt gespeichert und
        # wird nach dem Neustart fortgesetzt
        party.stop("beendet")
        engine.stop_all()
        lamps.restore()      # Lampen zurück auf den Zustand vor der Party
        for k in heads.HEADS:
            heads.apply(k, on=False)
        time.sleep(0.5)
        stop.set()
        server.server_close()
        print("Beendet, Köpfe dunkel.", flush=True)


if __name__ == "__main__":
    main()
