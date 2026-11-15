"""Die beiden Moving Heads: aktueller Zustand, DMX-Puffer und die Bewegungshilfen Anschub und Vorsteuerung."""
import json
import threading
import time
from datetime import datetime

import config
from artnet import Head
from geometry import pan_tilt
from settings import SETTINGS

HEADS = {k: Head(config.LAYOUT[k], 0) for k in (1, 2)}
STATE = {k: {"pan": 32768, "tilt": 32768, "on": True, "farbe": 0, "gobo": 0, "strobe": 0, "hell": 255}
         for k in HEADS}
LOCK = threading.Lock()
LIMITS = {"pan": 65535, "tilt": 65535, "farbe": 255, "gobo": 255, "strobe": 255, "hell": 255}


def apply(k, pan=None, tilt=None, on=None, farbe=None, gobo=None, strobe=None, hell=None):
    """Setzt Werte eines Kopfes (None = unverändert) und schreibt sie in den DMX-Puffer."""
    values = {"pan": pan, "tilt": tilt, "farbe": farbe, "gobo": gobo, "strobe": strobe, "hell": hell}
    with LOCK:
        st = STATE[k]
        for key, value in values.items():
            if value is not None:
                st[key] = max(0, min(LIMITS[key], int(value)))
        if on is not None:
            st["on"] = bool(on)
        head = HEADS[k]
        head.position(st["pan"], st["tilt"])
        with head.lock:
            head.set8(head.ch["dimmer"], st["hell"] if st["on"] else 0)
            head.set8(head.ch["color"], st["farbe"])
            head.set8(head.ch["gobo"], st["gobo"])
            head.set8(head.ch["strobe"], st["strobe"])


def snapshot():
    with LOCK:
        return {str(k): dict(v) for k, v in STATE.items()}


# --- Zielen ------------------------------------------------------------------------------------------
# Das Kalibriermodell (geometry.py) hat die x-Achse gespiegelt gegenüber dem Raum. Die Show rechnet in
# Raumkoordinaten (x = 0 links … 5 rechts, Blick zum TV); beim Zielen wird deshalb 5 − x übergeben.
_LAST_GOAL = {}   # k → (pan, tilt, Zeit) des letzten Show-Ziels
_KICK = {}
_VEL = {}
# Anschub (gemessen: Überschießen macht Sprünge schneller, mit leichtem Nachwackeln):
# bei einem Sprung kurz ein weiter entferntes Ziel vorgeben, dann das echte.
KICK_FAKTOR = 1.5      # Zusatzweg als Vielfaches des Sprungs (1,5 = Ziel liegt beim 2,5-fachen)
KICK_ZEIT = 0.12       # Sekunden
KICK_AB_PAN = 450      # ab ca. 4° Pan in einem Bild gilt es als Sprung
KICK_AB_TILT = 1760    # ab ca. 4° Tilt
VOR_MAX_PAN = 1700     # Vorsteuerung höchstens ca. 15° Pan
VOR_MAX_TILT = 6600    # bzw. ca. 15° Tilt


def _clamp16(v):
    return max(0, min(65535, int(v)))


def _with_kick(k, pan, tilt):
    """Die tatsächlich zu sendenden Pan/Tilt-Werte.
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


def aim_show(k, point):
    """Pan/Tilt für einen Show-Zielpunkt in Raumkoordinaten, mit Anschub und Vorsteuerung."""
    x, y, z = point
    current = _LAST_GOAL.get(k, (STATE[k]["pan"],))[0]
    pan, tilt = pan_tilt(k, (5.0 - x, y, z), current_pan=current)
    return _with_kick(k, pan, tilt)


# --- Einrichten: Punkt im Raumbild antippen und merken ----------------------------------------------
LAST_TARGET = {"value": None}
CALIB_FILE = config.DATA / "kalibrierpunkte.jsonl"


def aim_manual(x_model, y, z):
    """Richtet beide Köpfe auf einen Punkt. x kommt schon gespiegelt aus der Oberfläche (Modell)."""
    for k in HEADS:
        pan, tilt = pan_tilt(k, (x_model, y, z), current_pan=STATE[k]["pan"])
        apply(k, pan, tilt)
    LAST_TARGET["value"] = {"x": 5 - x_model, "y": y, "z": z}   # für die Datei in Raumkoordinaten


def save_point():
    """Hängt den aktuellen Kalibrierpunkt an die Datei an: Zielpunkt aus dem Bild plus die
    endgültigen 16-Bit-Werte beider Köpfe nach dem Feinjustieren."""
    with LOCK:
        heads = {str(k): {"pan": v["pan"], "tilt": v["tilt"]} for k, v in STATE.items()}
    entry = {"zeit": datetime.now().isoformat(timespec="seconds"), "ziel": LAST_TARGET["value"], "kopf": heads}
    with CALIB_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    with CALIB_FILE.open(encoding="utf-8") as f:
        count = sum(1 for _ in f)
    return {"count": count, "ziel": entry["ziel"]}
