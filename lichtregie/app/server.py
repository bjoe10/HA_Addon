#!/usr/bin/env python3
"""Lichtregie: Show-Server für die Moving Heads (nur Standardbibliothek).

Im Add-on läuft er hinter HA-Ingress (Seitenleiste „Lichtregie“), lokal auf dem Mac über dev/run_local.sh.
Die Web-Oberfläche zeigt den Raum perspektivisch; antippen richtet die Köpfe auf Boden, Wand oder Decke.
Die Show liest den Spotify-Titel aus HA, holt Tempo und Stimmung und steuert die Köpfe per Art-Net.
Einstellungen und Nodes: config.py.
"""
import json
import socket
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import show
from artnet import ART_PORT, FPS, Head, artdmx
from geometry import pan_tilt
from tempo import tempo

NODES = config.NODES
PORT = config.PORT
HEADS = {k: Head(config.LAYOUT[k], 0) for k in (1, 2)}
STATE = {k: {"pan": 32768, "tilt": 32768, "on": True, "farbe": 0, "gobo": 0, "strobe": 0, "hell": 255} for k in HEADS}
COLOR_CH = {k: config.LAYOUT[k]["color"] for k in HEADS}    # DMX-Kanäle aus configuration.yaml
GOBO_CH = {k: config.LAYOUT[k]["gobo"] for k in HEADS}
STROBE_CH = {k: config.LAYOUT[k]["strobe"] for k in HEADS}
STATE_LOCK = threading.Lock()
# Letzter Zielpunkt aus dem Bild, in Raumkoordinaten (ohne Spiegelung), für „Punkt merken“
LAST_TARGET = {"value": None}
CALIB_FILE = config.DATA / "kalibrierpunkte.jsonl"


def apply(k, pan=None, tilt=None, on=None, farbe=None, gobo=None, strobe=None, hell=None):
    with STATE_LOCK:
        st = STATE[k]
        if hell is not None:
            st["hell"] = max(0, min(255, int(hell)))
        if strobe is not None:
            st["strobe"] = max(0, min(255, int(strobe)))
        if farbe is not None:
            st["farbe"] = max(0, min(255, int(farbe)))
        if gobo is not None:
            st["gobo"] = max(0, min(255, int(gobo)))
        if pan is not None:
            st["pan"] = max(0, min(65535, int(pan)))
        if tilt is not None:
            st["tilt"] = max(0, min(65535, int(tilt)))
        if on is not None:
            st["on"] = bool(on)
        head = HEADS[k]
        head.position(st["pan"], st["tilt"])
        with head.lock:
            head.set8(head.ch["dimmer"], st["hell"] if st["on"] else 0)
            head.set8(COLOR_CH[k], st["farbe"])
            head.set8(GOBO_CH[k], st["gobo"])
            head.set8(STROBE_CH[k], st["strobe"])


def snapshot():
    with STATE_LOCK:
        return {str(k): dict(v) for k, v in STATE.items()}


def save_point():
    """Hängt den aktuellen Kalibrierpunkt an die Datei an: Zielpunkt aus dem Bild plus die
    endgültigen 16-Bit-Werte beider Köpfe nach dem Feinjustieren."""
    with STATE_LOCK:
        heads = {str(k): {"pan": v["pan"], "tilt": v["tilt"]} for k, v in STATE.items()}
    entry = {"zeit": datetime.now().isoformat(timespec="seconds"),
             "ziel": LAST_TARGET["value"], "kopf": heads}
    with CALIB_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    count = sum(1 for _ in CALIB_FILE.open(encoding="utf-8"))
    return {"count": count, "ziel": entry["ziel"]}


def now_playing():
    """Liest den laufenden Titel aus HA. Gibt None zurück, wenn nichts läuft oder HA nicht antwortet."""
    try:
        if not config.PLAYER:
            return None
        req = urllib.request.Request(f"{config.HA_API}/states/{config.PLAYER}",
                                     headers={"Authorization": f"Bearer {config.ha_token()}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    attrs = data.get("attributes", {})
    if not attrs.get("media_title"):
        return None
    playing = data.get("state") == "playing"
    # Position aus HA hochrechnen: HA aktualisiert sie nur alle paar Sekunden
    pos = attrs.get("media_position")
    updated = attrs.get("media_position_updated_at")
    estimate = None
    if pos is not None and updated:
        estimate = float(pos)
        if playing:
            estimate += (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).total_seconds()
    return {"title": attrs["media_title"], "artist": attrs.get("media_artist", ""),
            "id": attrs.get("media_content_id"),
            "duration": attrs.get("media_duration"), "pos": estimate, "playing": playing}


LIVE = {"live": None, "at": 0.0}
BEAT = {"stop": None, "info": "aus", "szene": "", "start": None}
# Einstellungen aus der Web-App: Strobe an/aus, Nebel an/aus, Phasen-Versatz in Schlägen, Vorlauf in Sekunden
SETTINGS = {"strobe": True, "nebel": False, "offset": 0.0, "vorlauf": 0.4, "tempo": 2.0,
            "anschub": True, "vorsteuerung": 0.45}
SETTINGS_FILE = config.DATA / "settings.json"
try:   # Schalter aus der Web-App überdauern einen Neustart
    SETTINGS.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
except (OSError, ValueError):
    pass


def save_settings():
    try:
        config.DATA.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(SETTINGS), encoding="utf-8")
    except OSError:
        pass
VORSTEUERUNG_STUFEN = [0.0, 0.2, 0.3, 0.45]  # Sekunden; 0 = aus
SPOTS = {}  # aktuelle Zielpunkte für die Vorschau im Raumbild

# Anschub (gemessen: Überschießen macht Sprünge schneller, mit leichtem Nachwackeln):
# bei einem Sprung kurz ein weiter entferntes Ziel vorgeben, dann das echte.
KICK_FAKTOR = 1.5      # Zusatzweg als Vielfaches des Sprungs (1,5 = Ziel liegt beim 2,5-fachen)
KICK_ZEIT = 0.12       # Sekunden
KICK_AB_PAN = 450      # ab ca. 4° Pan in einem Bild gilt es als Sprung
KICK_AB_TILT = 1760    # ab ca. 4° Tilt
_LAST_GOAL = {}
_KICK = {}
_VEL = {}
VOR_MAX_PAN = 1700    # Vorsteuerung höchstens ca. 15° Pan
VOR_MAX_TILT = 6600   # bzw. ca. 15° Tilt


def _clamp16(v):
    return max(0, min(65535, int(v)))


def with_kick(k, pan, tilt):
    """Gibt die tatsächlich zu sendenden Pan/Tilt-Werte zurück.
    - Sprung (ab ca. 4° in einem Bild): Anschub, kurz ein weiter entferntes Ziel.
    - Fließende Bewegung: Vorsteuerung, das Ziel um Geschwindigkeit × Zeitkonstante vorausgeben,
      damit der Kopf trotz interner Glättung nicht hinterherläuft."""
    now = time.time()
    prev = _LAST_GOAL.get(k)
    _LAST_GOAL[k] = (pan, tilt, now)
    jump = bool(prev) and (abs(pan - prev[0]) > KICK_AB_PAN or abs(tilt - prev[1]) > KICK_AB_TILT)
    if SETTINGS["anschub"] and jump:
        _KICK[k] = (now + KICK_ZEIT, _clamp16(pan + KICK_FAKTOR * (pan - prev[0])),
                    _clamp16(tilt + KICK_FAKTOR * (tilt - prev[1])))
    vp, vt = _VEL.get(k, (0.0, 0.0))
    if jump:
        vp = vt = 0.0
    elif prev:
        dt = max(1e-3, now - prev[2])
        vp = 0.5 * vp + 0.5 * (pan - prev[0]) / dt
        vt = 0.5 * vt + 0.5 * (tilt - prev[1]) / dt
    _VEL[k] = (vp, vt)
    kick = _KICK.get(k)
    if kick and now < kick[0]:
        return kick[1], kick[2]
    tau = SETTINGS["vorsteuerung"]
    lead_pan = max(-VOR_MAX_PAN, min(VOR_MAX_PAN, tau * vp))
    lead_tilt = max(-VOR_MAX_TILT, min(VOR_MAX_TILT, tau * vt))
    return _clamp16(pan + lead_pan), _clamp16(tilt + lead_tilt)


def show_loop(prof, t0, stop):
    """Show-Motor mit 40 Bildern/s. Die Taktposition hängt an der Liedposition aus HA,
    ohne Position (pausiert) an der Zeit seit dem Start."""
    bpm = prof["bpm"]
    started = time.time()
    while not stop.is_set():
        # Liedwechsel: die ersten 0,6 s dunkel, damit Farb- und Goborad unsichtbar auf das neue Thema laufen
        blackout = time.time() - started < 0.6
        pos = song_position()
        sec = pos if pos is not None else (time.time() - t0)
        b = sec * bpm / 60.0 + SETTINGS["offset"]
        b_move = b + SETTINGS["vorlauf"] * bpm / 60.0   # Bewegung vorziehen, damit sie auf dem Schlag ankommt
        out, info = show.frame(prof, b, b_move, strobe_on=SETTINGS["strobe"], tempo=SETTINGS["tempo"])
        for k, v in out.items():
            x, y, z = v["ziel"]
            # Das Modell in ziel.py ist in x gespiegelt, deshalb 5 - x
            pan, tilt = pan_tilt(k, (5.0 - x, y, z), current_pan=_LAST_GOAL.get(k, (STATE[k]["pan"],))[0])
            pan, tilt = with_kick(k, pan, tilt)
            if blackout:
                v = dict(v, hell=0, strobe=0)
            apply(k, pan, tilt, True, v["farbe"], v["gobo"], v["strobe"], v["hell"])
            SPOTS[str(k)] = {"x": x, "y": y, "z": z, "hell": v["hell"], "farbe": v["farbe"]}
        BEAT["szene"] = f"Takt {int(b // 4) + 1} · {info}"
        stop.wait(1.0 / FPS)


def song_position():
    """Geschätzte Position im Lied in Sekunden, oder None wenn nicht spielt."""
    live = LIVE.get("live")
    if not live or live.get("pos") is None or not live.get("playing"):
        return None
    return float(live["pos"]) + (time.time() - LIVE["at"])


def start_beat(title, artist, info, track_id=None, duration=None):
    """Startet die Show für einen Titel. info = Tempo-Daten (mindestens bpm)."""
    halt_beat()
    prof = show.profile(track_id or f"{artist}|{title}", info, duration, nebel=SETTINGS["nebel"])
    stop = threading.Event()
    BEAT["stop"] = stop
    BEAT["start"] = (title, artist, info, track_id, duration)
    BEAT["info"] = f"{title} – {artist}: {prof['bpm']:.1f} BPM, {show.describe(prof)}"
    threading.Thread(target=show_loop, args=(prof, time.time(), stop), daemon=True).start()


def halt_beat():
    if BEAT["stop"] is not None:
        BEAT["stop"].set()
        BEAT["stop"] = None
        time.sleep(0.05)
        for k in HEADS:          # kein Strobe nach dem Stopp
            apply(k, strobe=0)
    SPOTS.clear()
    BEAT["szene"] = ""


def stop_all():
    halt_beat()
    if WATCH["stop"] is not None:
        WATCH["stop"].set()
        WATCH["stop"] = None
    BEAT["info"] = "aus"


WATCH = {"stop": None}


def watch_loop(stop, current):
    """Prüft alle 5 s den Titel in HA. Bei einem neuen Titel wird das Tempo geholt und der Takt neu gestartet.
    Pausiert die Musik, läuft der Takt weiter (kein Flackern)."""
    while not stop.wait(2):
        live = now_playing()
        if not live:
            continue
        LIVE.update(live=live, at=time.time())
        key = (live["title"], live["artist"])
        if key == current:
            # Gleicher Titel, aber der Takt ist nicht (mehr) aktiv: neu starten
            if BEAT["stop"] is None and live.get("playing"):
                found = tempo(live["title"], live["artist"])
                if found and found.get("bpm"):
                    start_beat(live["title"], live["artist"], found, live.get("id"), live.get("duration"))
            continue
        current = key
        found = tempo(live["title"], live["artist"])
        if found and found.get("bpm"):
            start_beat(live["title"], live["artist"], found, live.get("id"), live.get("duration"))
        else:
            halt_beat()
            BEAT["info"] = f"{live['title']}: kein Tempo gefunden"


def start_watch(title, artist):
    if WATCH["stop"] is not None:
        WATCH["stop"].set()
    stop = threading.Event()
    WATCH["stop"] = stop
    threading.Thread(target=watch_loop, args=(stop, (title, artist)), daemon=True).start()


def sender(stop):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = 1
    while not stop.is_set():
        for k, head in HEADS.items():
            with head.lock:
                data = bytes(head.buf)
            sock.sendto(artdmx(config.UNIVERSE[k], data, seq), (NODES[k], ART_PORT))
        seq = (seq + 1) % 256 or 1
        time.sleep(1.0 / FPS)
    sock.close()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.178.1", 80))  # sendet nichts, ermittelt nur die lokale Adresse
        return s.getsockname()[0]
    finally:
        s.close()


HTML = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moving Heads</title>
<style>
 body{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:16px;background:#111;color:#eee;max-width:520px;margin:auto}
 h1{font-size:22px;margin:4px 0 12px} h2{font-size:17px;margin:0 0 8px}
 .card{background:#1d1d1f;border-radius:14px;padding:14px;margin-bottom:12px}
 label{display:block;font-size:15px;margin:12px 0 4px}
 .val{float:right;color:#9bd;font-variant-numeric:tabular-nums}
 input[type=range]{width:100%;height:34px}
 button{font-size:18px;padding:14px;border:0;border-radius:12px;background:#333;color:#eee;width:100%;margin-top:10px}
 button.primary{background:#0a84ff} button.danger{background:#8a1c1c}
 .row{display:flex;gap:10px}
 #room{display:block;width:100%;background:#0c0c0e;border-radius:12px;touch-action:none;user-select:none}
 .hint,.coords{font-size:13px;color:#aaa;margin:8px 0}
</style></head><body>
<h1>Moving Heads</h1>

<div class="card">
 <h2>Raum antippen</h2>
 <p class="hint">Mit dem Finger auf das Bild. Der Punkt springt auf die Fläche, die dort zu sehen ist: Boden, Wand oder Decke.</p>
 <canvas id="room"></canvas>
 <p class="coords" id="coords"></p>
 <button id="save">Punkt merken</button>
</div>

<div class="card">
 <h2>Show</h2>
 <div class="row"><button id="tStrobe">Strobe</button><button id="tNebel">Nebel</button></div>
 <div class="row"><button id="tempo1">Bewegung ×1</button><button id="tempo2">Bewegung ×2</button></div>
 <div class="row"><button id="tKick">Anschub</button><button id="tVor">Vorsteuerung</button></div>
 <p class="coords" id="szene">–</p>
 <label>Titel</label>
 <input id="ttl" placeholder="wird aus HA gelesen" style="width:100%;font-size:16px;padding:8px;border-radius:8px;border:0;background:#2a2a2d;color:#eee;box-sizing:border-box">
 <label>Interpret</label>
 <input id="art" placeholder="wird aus HA gelesen" style="width:100%;font-size:16px;padding:8px;border-radius:8px;border:0;background:#2a2a2d;color:#eee;box-sizing:border-box">
 <label>BPM (leer = aus der Datenbank)</label>
 <input id="bpm" placeholder="leer lassen" style="width:100%;font-size:16px;padding:8px;border-radius:8px;border:0;background:#2a2a2d;color:#eee;box-sizing:border-box">
 <div class="row"><button class="primary" id="start">Start</button><button class="danger" id="stop">Stopp</button></div>
 <p class="coords" id="beatinfo">aus</p>
</div>

<div id="heads"></div>

<div class="row">
 <button id="allon">Alle an</button>
 <button class="danger" id="alloff">Alle aus</button>
</div>

<script>
const $ = id => document.getElementById(id);
const timers = {};
let state = {};

// Farbtabelle Farbrad-Kanal (Beobachtung am Gerät): Startwert je Farbe, darüber gilt der Bereich
const FARBEN = [[0, 'weiß'], [17, 'rot'], [22, 'grün'], [36, 'blau'], [44, 'gelb'], [54, 'orange'],
  [64, 'eisblau'], [73, 'lila'], [85, 'eisblau/lila'], [93, 'eisblau/orange'], [101, 'orange/gelb'],
  [113, 'gelb/blau'], [121, 'grün/blau'], [132, 'grün/rot']];
function farbName(v) {
  if (v >= 140) return 'Auto-Programm';
  let name = 'weiß';
  for (const [start, n] of FARBEN) if (v >= start) name = n;
  return name;
}
// Gobo-Muster (Beobachtung am Gerät): Startwert je Muster
const GOBOS = [[0, 'voll offen'], [13, 'Atom-Ring'], [21, 'Punkte-Ring'], [27, 'Punkte-Blume'], [34, 'grobe Löcher'],
  [43, 'Blubberblasen'], [50, 'Swirl'], [57, 'Striche'], [58, 'unbekannt'],
  // Zittern: je Muster drei Stufen, langsam bis schnell (nur Atom ist bestätigt, die anderen angenommen)
  [73, 'Atom zittern langsam'], [74, 'Atom zittern mittel'], [76, 'Atom zittern schnell'],
  [80, 'Punkte-Ring zittern 1'], [82, 'Punkte-Ring zittern 2'], [85, 'Punkte-Ring zittern 3'],
  [89, 'Punkte-Blume zittern 1'], [90, 'Punkte-Blume zittern 2'], [93, 'Punkte-Blume zittern 3'],
  [97, 'grobe Löcher zittern 1'], [99, 'grobe Löcher zittern 2'], [100, 'grobe Löcher zittern 3'],
  [105, 'Blasen zittern 1'], [108, 'Blasen zittern 2'], [111, 'Blasen zittern 3'],
  [113, 'Swirl zittern 1'], [115, 'Swirl zittern 2'], [117, 'Swirl zittern 3'],
  [121, 'Striche zittern 1'], [123, 'Striche zittern 2'], [126, 'Striche zittern 3']];
const GOBO_SCHNELL = GOBOS.map(([v, n]) => [n, v]);
function goboName(v) {
  let name = 'voll offen';
  for (const [start, n] of GOBOS) if (v >= start) name = n;
  return name;
}
// Strobe (Beobachtung am Gerät): 0 und 255 = Licht dauerhaft an, dazwischen blinkt es, je höher desto schneller
function strobeName(v) {
  if (v === 0 || v === 255) return 'kein Strobe (an)';
  return v === 200 ? 'Strobe, guter Wert' : 'Strobe, schneller je höher';
}
const SCHNELL = [['weiß', 0], ['rot', 17], ['grün', 22], ['blau', 36], ['gelb', 44], ['orange', 54], ['eisblau', 64], ['lila', 73]];
const MISCH = [['eisblau/lila', 85], ['eisblau/orange', 93], ['orange/gelb', 101], ['gelb/blau', 113], ['grün/blau', 121], ['grün/rot', 132]];
function presets() {
  for (const k of [1, 2]) {
    let html = '';
    for (const [n, v] of SCHNELL.concat(MISCH)) html += `<button data-v="${v}" style="width:auto;padding:8px 10px;font-size:14px;margin:4px 4px 0 0">${n}</button>`;
    $('pr' + k).innerHTML = html;
    $('pr' + k).querySelectorAll('button').forEach(b => b.addEventListener('click', () =>
      post('api/set', {heads: {[k]: {farbe: +b.dataset.v}}})));
    let gh = '';
    for (const [n, v] of GOBO_SCHNELL) gh += `<button data-v="${v}" style="width:auto;padding:8px 10px;font-size:14px;margin:4px 4px 0 0">${n}</button>`;
    $('gp' + k).innerHTML = gh;
    $('gp' + k).querySelectorAll('button').forEach(b => b.addEventListener('click', () =>
      post('api/set', {heads: {[k]: {gobo: +b.dataset.v}}})));
  }
}

// --- Kamera: aus Sicht der Kopfwand (y = 6), leicht von oben, Blick Richtung TV-Wand ---
const CAM = {pos: [2.5, 5.9, 2.2], target: [2.5, 0, 0.8], fov: 62 * Math.PI / 180};
const BOX = {min: [0, 0, 0], max: [5, 6, 2.5]};
const FACE = ['Wand x=5 bzw. x=0', 'Wand y=0 (TV) bzw. y=6 (Kopfwand)', 'Boden bzw. Decke'];
let padXY = {x: 2.5, y: 3.0, z: 0};
let spots = {}, settings = {strobe: true, nebel: false};
const RADFARBE = {0: '#ffffff', 17: '#ff3b30', 22: '#34c759', 36: '#3a6bff', 44: '#ffd60a',
  54: '#ff9500', 64: '#7fdcff', 73: '#bf5af2'};
let canvas = $('room'), ctx = canvas.getContext('2d');
let W = 300, H = 225;

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = a => { const l = Math.hypot(a[0], a[1], a[2]); return [a[0] / l, a[1] / l, a[2] / l]; };

function basis() {
  const f = norm(sub(CAM.target, CAM.pos));
  const r = norm(cross(f, [0, 0, 1]));  // Bild wie im Raum: Blick von der Kopfwand zum TV
  const u = cross(r, f);
  return {f, r, u};
}

// Raumpunkt -> Bildanteile (0..1), null wenn hinter der Kamera
function project(P) {
  const B = basis();
  const v = sub(P, CAM.pos);
  const zc = dot(v, B.f);
  if (zc <= 0.01) return null;
  const h = Math.tan(CAM.fov / 2), aspect = W / H;
  return [0.5 + dot(v, B.r) / zc / (2 * h * aspect), 0.5 - dot(v, B.u) / zc / (2 * h)];
}

// Bildanteile -> Fläche des Raums, auf die der Strahl trifft (Kamera steht im Raum)
function pick(fu, fv) {
  const B = basis();
  const h = Math.tan(CAM.fov / 2), aspect = W / H;
  const a = (fu - 0.5) * 2 * h * aspect, b = (0.5 - fv) * 2 * h;
  const d = add(add(B.f, scale(B.r, a)), scale(B.u, b));
  let t = Infinity, axis = 0;
  for (let i = 0; i < 3; i++) {
    let ti = null;
    if (d[i] > 1e-9) ti = (BOX.max[i] - CAM.pos[i]) / d[i];
    else if (d[i] < -1e-9) ti = (BOX.min[i] - CAM.pos[i]) / d[i];
    if (ti !== null && ti > 0 && ti < t) { t = ti; axis = i; }
  }
  const P = add(CAM.pos, scale(d, t));
  for (let i = 0; i < 3; i++) P[i] = Math.min(BOX.max[i], Math.max(BOX.min[i], P[i]));
  return {P, face: axis};
}

function drawRoom() {
  ctx.clearRect(0, 0, W, H);
  // Boden und Wände leicht getönt, damit die Flächen unterscheidbar sind
  const corners = [];
  for (const x of [0, 5]) for (const y of [0, 6]) for (const z of [0, 2.5]) corners.push([x, y, z]);
  ctx.strokeStyle = '#4a4a52'; ctx.lineWidth = 1.5;
  for (let i = 0; i < corners.length; i++) for (let j = i + 1; j < corners.length; j++) {
    const a = corners[i], b = corners[j];
    const diff = [0, 1, 2].filter(k => a[k] !== b[k]);
    if (diff.length !== 1) continue;
    const pa = project(a), pb = project(b);
    if (!pa || !pb) continue;
    ctx.beginPath(); ctx.moveTo(pa[0] * W, pa[1] * H); ctx.lineTo(pb[0] * W, pb[1] * H); ctx.stroke();
  }
  // TV-Wand als Rechteck (TV ca. 1,2 m breit, Mitte 2,5 m, Höhe 0,5 bis 1,3 m)
  const tv = [[1.9, 0, 0.5], [3.1, 0, 0.5], [3.1, 0, 1.3], [1.9, 0, 1.3]].map(project);
  if (tv.every(p => p)) {
    ctx.fillStyle = '#1b2a3a'; ctx.beginPath();
    tv.forEach((p, i) => i ? ctx.lineTo(p[0] * W, p[1] * H) : ctx.moveTo(p[0] * W, p[1] * H));
    ctx.closePath(); ctx.fill();
  }
  // Spots der laufenden Show (Vorschau), in der Farbe des Farbrads, Deckkraft nach Helligkeit
  for (const k of ['1', '2']) {
    const s = spots[k];
    if (!s) continue;
    const p = project([s.x, s.y, s.z]);
    if (!p) continue;
    ctx.globalAlpha = s.hell > 0 ? 0.25 + 0.75 * s.hell / 255 : 0.08;
    ctx.fillStyle = RADFARBE[s.farbe] || '#ffffff';
    ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 20;
    ctx.beginPath(); ctx.arc(p[0] * W, p[1] * H, 13, 0, 2 * Math.PI); ctx.fill();
    ctx.shadowBlur = 0; ctx.globalAlpha = 1;
    ctx.fillStyle = '#000'; ctx.font = '11px sans-serif'; ctx.fillText(k, p[0] * W - 3, p[1] * H + 4);
  }
  // Aktueller Zielpunkt
  const c = project([padXY.x, padXY.y, padXY.z]);
  if (c) {
    ctx.fillStyle = '#0a84ff'; ctx.shadowColor = '#0a84ff'; ctx.shadowBlur = 16;
    ctx.beginPath(); ctx.arc(c[0] * W, c[1] * H, 9, 0, 2 * Math.PI); ctx.fill();
    ctx.shadowBlur = 0;
  }
}

function resize() {
  const w = Math.min(canvas.parentElement.clientWidth - 32, 520);
  W = Math.max(240, Math.round(w)); H = Math.round(W * 0.75);
  const dpr = window.devicePixelRatio || 1;
  canvas.style.height = H + 'px';
  canvas.width = W * dpr; canvas.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  drawRoom();
}

function post(path, body) {
  return fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify(body)})
    .then(r => r.json()).then(s => { state = s; showState(); });
}
function throttled(key, fn) {
  clearTimeout(timers[key]); timers[key] = setTimeout(fn, 60);
}

let lastSend = 0, pendingTimer = null;
// Das Modell in ziel.py/kalibrierung_fit.py hat die x-Achse gespiegelt gegenüber dem Raum
// (Messpunkte allein unterscheiden das nicht). Deshalb wird x hier zurückgespiegelt.
function sendTarget() { post('api/target', {x: 5 - padXY.x, y: padXY.y, z: padXY.z}); }
$('save').addEventListener('click', () => {
  fetch('api/save', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
    .then(r => r.json()).then(s => {
      $('coords').textContent = `gemerkt: Nr. ${s.count} (${s.ziel ? 'Ziel ' + s.ziel.x.toFixed(2) + ' / ' + s.ziel.y.toFixed(2) + ' / ' + s.ziel.z.toFixed(2) : 'ohne Zielpunkt'})`;
    });
});
function touchRoom(e) {
  const r = canvas.getBoundingClientRect();
  const fu = (e.clientX - r.left) / r.width, fv = (e.clientY - r.top) / r.height;
  const {P, face} = pick(Math.min(1, Math.max(0, fu)), Math.min(1, Math.max(0, fv)));
  padXY = {x: P[0], y: P[1], z: P[2]};
  $('coords').textContent =
    `x ${P[0].toFixed(2)} m, y ${P[1].toFixed(2)} m, z ${P[2].toFixed(2)} m · ${FACE[face]}`;
  drawRoom();
  const now = Date.now();
  if (now - lastSend >= 50) { lastSend = now; sendTarget(); }
  else { clearTimeout(pendingTimer); pendingTimer = setTimeout(() => { lastSend = Date.now(); sendTarget(); }, 50); }
}
canvas.addEventListener('pointerdown', e => { canvas.setPointerCapture(e.pointerId); touchRoom(e); });
canvas.addEventListener('pointermove', e => { if (canvas.hasPointerCapture(e.pointerId)) touchRoom(e); });
canvas.addEventListener('pointerup', e => { canvas.releasePointerCapture(e.pointerId); });
window.addEventListener('resize', resize);

function buildHeads() {
  let html = '';
  for (const k of [1, 2]) {
    html += `<div class="card"><h2>Kopf ${k}</h2>
      <label>Pan <span class="val" id="pv${k}"></span>
        <input type="range" min="0" max="65535" id="p${k}"></label>
      <label>Tilt <span class="val" id="tv${k}"></span>
        <input type="range" min="0" max="65535" id="t${k}"></label>
      <label>Helligkeit <span class="val" id="hv${k}"></span>
        <input type="range" min="0" max="255" id="h${k}"></label>
      <label>Farbe <span class="val" id="fv${k}"></span>
        <input type="range" min="0" max="255" id="f${k}"></label>
      <div id="pr${k}"></div>
      <label>Gobo <span class="val" id="gv${k}"></span>
        <input type="range" min="0" max="255" id="g${k}"></label>
      <div id="gp${k}"></div>
      <label>Strobe <span class="val" id="sv${k}"></span>
        <input type="range" min="0" max="255" id="s${k}"></label>
      <p class="hint">Achtung: Blitzlicht. Nur kurz und vorsichtig testen.</p>
      <button id="b${k}"></button></div>`;
  }
  $('heads').innerHTML = html;
  for (const k of [1, 2]) {
    $('p' + k).addEventListener('input', () =>
      throttled('p' + k, () => post('api/set', {heads: {[k]: {pan: +$('p' + k).value}}})));
    $('t' + k).addEventListener('input', () =>
      throttled('t' + k, () => post('api/set', {heads: {[k]: {tilt: +$('t' + k).value}}})));
    $('h' + k).addEventListener('input', () =>
      throttled('h' + k, () => post('api/set', {heads: {[k]: {hell: +$('h' + k).value}}})));
    $('s' + k).addEventListener('input', () =>
      throttled('s' + k, () => post('api/set', {heads: {[k]: {strobe: +$('s' + k).value}}})));
    $('g' + k).addEventListener('input', () =>
      throttled('g' + k, () => post('api/set', {heads: {[k]: {gobo: +$('g' + k).value}}})));
    $('f' + k).addEventListener('input', () =>
      throttled('f' + k, () => post('api/set', {heads: {[k]: {farbe: +$('f' + k).value}}})));
    $('b' + k).addEventListener('click', () =>
      post('api/set', {heads: {[k]: {on: !state[k].on}}}));
  }
}

function showState() {
  for (const k of [1, 2]) {
    const s = state[k];
    if (!s) continue;
    if (document.activeElement !== $('p' + k)) $('p' + k).value = s.pan;
    if (document.activeElement !== $('t' + k)) $('t' + k).value = s.tilt;
    $('pv' + k).textContent = s.pan;
    if (document.activeElement !== $('f' + k)) $('f' + k).value = s.farbe;
    $('fv' + k).textContent = s.farbe + ' · ' + farbName(s.farbe);
    if (document.activeElement !== $('g' + k)) $('g' + k).value = s.gobo;
    $('gv' + k).textContent = s.gobo + ' · ' + goboName(s.gobo);
    if (document.activeElement !== $('h' + k)) $('h' + k).value = s.hell;
    $('hv' + k).textContent = s.hell;
    if (document.activeElement !== $('s' + k)) $('s' + k).value = s.strobe;
    $('sv' + k).textContent = s.strobe + ' · ' + strobeName(s.strobe);
    $('tv' + k).textContent = s.tilt;
    $('b' + k).textContent = s.on ? `Kopf ${k} aus` : `Kopf ${k} an`;
    $('b' + k).className = s.on ? '' : 'primary';
  }
}

$('allon').addEventListener('click', () =>
  post('api/set', {heads: {1: {on: true}, 2: {on: true}}}));
$('alloff').addEventListener('click', () =>
  post('api/set', {heads: {1: {on: false}, 2: {on: false}}}));

$('start').addEventListener('click', () => {
  $('beatinfo').textContent = 'lade …';
  fetch('api/start', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({title: $('ttl').value, artist: $('art').value, bpm: $('bpm').value})})
    .then(r => r.json()).then(s => { $('beatinfo').textContent = s.info; });
});
$('stop').addEventListener('click', () =>
  fetch('api/stop', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
    .then(r => r.json()).then(s => { $('beatinfo').textContent = s.info; }));

// Schalter Strobe und Nebel
function showSettings() {
  $('tStrobe').textContent = 'Strobe ' + (settings.strobe ? 'an' : 'aus');
  $('tStrobe').className = settings.strobe ? 'primary' : '';
  $('tNebel').textContent = 'Nebel ' + (settings.nebel ? 'an' : 'aus');
  $('tNebel').className = settings.nebel ? 'primary' : '';
  $('tVor').textContent = 'Vorsteuerung ' + (settings.vorsteuerung ? settings.vorsteuerung + ' s' : 'aus');
  $('tVor').className = settings.vorsteuerung ? 'primary' : '';
  $('tKick').textContent = 'Anschub ' + (settings.anschub ? 'an' : 'aus');
  $('tKick').className = settings.anschub ? 'primary' : '';
  $('tempo1').className = settings.tempo === 1 ? 'primary' : '';
  $('tempo2').className = settings.tempo === 2 ? 'primary' : '';
}
$('tKick').addEventListener('click', () => setSetting({anschub: !settings.anschub}));
const VOR = [0, 0.2, 0.3, 0.45];
$('tVor').addEventListener('click', () => {
  const i = VOR.indexOf(settings.vorsteuerung);
  setSetting({vorsteuerung: VOR[(i + 1) % VOR.length]});
});
$('tempo1').addEventListener('click', () => setSetting({tempo: 1}));
$('tempo2').addEventListener('click', () => setSetting({tempo: 2}));
function setSetting(body) {
  fetch('api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)}).then(r => r.json()).then(s => { settings = s; showSettings(); });
}
$('tStrobe').addEventListener('click', () => setSetting({strobe: !settings.strobe}));
$('tNebel').addEventListener('click', () => setSetting({nebel: !settings.nebel}));

// Vorschau: Spots 5x pro Sekunde holen und ins Raumbild zeichnen
setInterval(() => {
  fetch('api/spots').then(r => r.json()).then(d => {
    spots = d.spots || {};
    $('szene').textContent = d.szene || '–';
    drawRoom();
  }).catch(() => {});
}, 200);

// Status alle 2 s holen, damit Anzeige und Köpfe zum Server passen
setInterval(() => {
  fetch('api/state').then(r => r.json()).then(s => {
    state = s; showState();
    if (s.settings) { settings = s.settings; showSettings(); }
    if (s.info) $('beatinfo').textContent = s.info + ' · erkannt: ' + s.erkannt + ' · Überwachung ' + (s.ueberwachung ? 'an' : 'aus');
  }).catch(() => {});
}, 2000);

buildHeads();
presets();
resize();
fetch('api/state').then(r => r.json()).then(s => { state = s; showState(); });
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, data):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
        elif self.path == "/api/state":
            data = snapshot()
            data["info"] = BEAT["info"]
            data["laeuft"] = BEAT["stop"] is not None
            live = LIVE.get("live") or {}
            data["erkannt"] = f"{live.get('title', '-')} ({time.time() - LIVE['at']:.0f} s her)" if LIVE.get("live") else "noch nichts"
            data["ueberwachung"] = WATCH["stop"] is not None
            data["szene"] = BEAT["szene"]
            data["settings"] = SETTINGS
            self._send(200, "application/json", json.dumps(data).encode("utf-8"))
        elif self.path == "/api/spots":
            self._send(200, "application/json",
                       json.dumps({"spots": SPOTS, "szene": BEAT["szene"]}).encode("utf-8"))
        else:
            self._send(404, "text/plain", b"nicht gefunden")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, "text/plain", b"ungueltiges JSON")
        if self.path == "/api/set":
            for k, values in body.get("heads", {}).items():
                apply(int(k), values.get("pan"), values.get("tilt"), values.get("on"), values.get("farbe"), values.get("gobo"), values.get("strobe"), values.get("hell"))
        elif self.path == "/api/target":
            x, y, z = float(body["x"]), float(body["y"]), float(body["z"])
            for k in HEADS:
                pan, tilt = pan_tilt(k, (x, y, z), current_pan=STATE[k]["pan"])
                apply(k, pan, tilt, None)
            # x kommt gespiegelt an (Modell), für die Datei zurück in Raumkoordinaten
            LAST_TARGET["value"] = {"x": 5 - x, "y": y, "z": z}
        elif self.path == "/api/save":
            return self._send(200, "application/json", json.dumps(save_point()).encode("utf-8"))
        elif self.path == "/api/start":
            title = str(body.get("title", "")).strip()
            artist = str(body.get("artist", "")).strip()
            bpm_text = str(body.get("bpm", "")).strip()
            live = now_playing()  # zuerst HA: was läuft gerade wirklich
            if live:
                title, artist = live["title"], live["artist"]
                LIVE.update(live=live, at=time.time())
            found = tempo(title, artist) if title and artist else None
            if bpm_text:
                info = dict(found or {}, bpm=float(bpm_text.replace(",", ".")))
            elif found and found.get("bpm"):
                info = found
            else:
                return self._send(200, "application/json", json.dumps(
                    {"info": "Tempo nicht gefunden, bitte BPM eingeben"}).encode("utf-8"))
            start_beat(title or "ohne Titel", artist, info,
                       live.get("id") if live else None, live.get("duration") if live else None)
            start_watch(title, artist)
            return self._send(200, "application/json", json.dumps({"info": BEAT["info"]}).encode("utf-8"))
        elif self.path == "/api/settings":
            for key in ("strobe", "nebel", "anschub"):
                if key in body:
                    SETTINGS[key] = bool(body[key])
            if "offset" in body:
                SETTINGS["offset"] = float(body["offset"])
            if "vorsteuerung" in body:
                SETTINGS["vorsteuerung"] = max(0.0, min(1.0, float(body["vorsteuerung"])))
            if "tempo" in body:
                SETTINGS["tempo"] = max(0.25, min(4.0, float(body["tempo"])))
            # Nebel ändert die Szenenauswahl: Show für den laufenden Titel neu aufbauen
            if "nebel" in body and BEAT["stop"] is not None and BEAT["start"]:
                start_beat(*BEAT["start"])
            save_settings()
            return self._send(200, "application/json", json.dumps(SETTINGS).encode("utf-8"))
        elif self.path == "/api/stop":
            stop_all()
            return self._send(200, "application/json", json.dumps({"info": BEAT["info"]}).encode("utf-8"))
        else:
            return self._send(404, "text/plain", b"nicht gefunden")
        self._send(200, "application/json", json.dumps(snapshot()).encode("utf-8"))

    def log_message(self, *args):
        pass


def main():
    for k in HEADS:
        apply(k, 32768, 32768, True)
    stop = threading.Event()
    threading.Thread(target=sender, args=(stop,), daemon=True).start()
    for k in HEADS:
        print(f"Kopf {k}: Node {NODES[k]}, Universe {config.UNIVERSE[k]}, Kanäle {config.LAYOUT[k]} "
              f"({config.HEADS_SOURCE[k]})", flush=True)
    print(f"Spotify-Player: {config.PLAYER or 'nicht eingestellt'}, "
          f"Tempo-Schlüssel: {'gesetzt' if config.freqblog_key() else 'fehlt'}", flush=True)
    print(f"Lichtregie läuft auf Port {PORT}", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_all()
        for k in HEADS:
            apply(k, on=False)
        time.sleep(0.5)
        stop.set()
        server.server_close()
        print("Beendet, Köpfe dunkel.", flush=True)


if __name__ == "__main__":
    main()
