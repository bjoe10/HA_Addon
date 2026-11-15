"""Laser: DMX-Werte, Schutzgrenzen für die Lage des Musters und die Abbildung der Show-Position."""
import threading

import config
from settings import SETTINGS

KEYS = ["mode", "shape", "rotate", "mirror_h", "mirror_v", "up_down", "left_right", "size", "color", "dots"]
STATE = {k: 0 for k in KEYS}
PRESET = {"mode": 15, "shape": 125, "rotate": 178, "mirror_h": 0, "mirror_v": 0, "up_down": 8,
          "left_right": 64, "size": 3, "color": 191, "dots": 0}   # HA-Szene „Laser Party standard“
BUF = bytearray(512)
LOCK = threading.Lock()


def _limits(values):
    """Schutzgrenzen: hoch/runter und links/rechts nie außerhalb des freigegebenen Bereichs."""
    out = dict(values)
    for key, lo, hi in (("up_down", "laser_ud_min", "laser_ud_max"),
                        ("left_right", "laser_lr_min", "laser_lr_max")):
        out[key] = max(SETTINGS[lo], min(SETTINGS[hi], int(out[key])))
    return out


def apply(values):
    """Setzt Laserwerte (nur bekannte Kanäle) und schreibt sie begrenzt in den DMX-Puffer."""
    with LOCK:
        STATE.update({k: max(0, min(255, int(v))) for k, v in values.items() if k in STATE})
        safe = _limits(STATE)
        for key, ch in config.LASER[2].items():
            BUF[ch - 1] = safe[key]


def off():
    apply({"mode": 0})


def apply_show(frame):
    """Übernimmt ein Bild aus show.laser_frame. Die Position (x, y von −1 bis 1) wird in die Grenzen
    gelegt: links/rechts über die ganze Breite, hoch/runter um den Ruhepunkt, nur so weit, wie er von
    beiden Grenzen entfernt ist. So bleiben die Bahnen ganz über (oder unter) dem TV in der Wandmitte."""
    values = {k: v for k, v in frame.items() if k in STATE}
    x, y = frame["pos"]
    lo, hi = SETTINGS["laser_ud_min"], SETTINGS["laser_ud_max"]
    mid = max(lo, min(hi, SETTINGS["laser_ud_mitte"]))
    values["up_down"] = mid + y * max(4, min(mid - lo, hi - mid))
    values["left_right"] = (SETTINGS["laser_lr_min"]
                            + (x + 1) / 2 * (SETTINGS["laser_lr_max"] - SETTINGS["laser_lr_min"]))
    apply(values)


def snapshot():
    with LOCK:
        return {"werte": dict(STATE), "gesendet": _limits(STATE), "steckdose": bool(config.LASER_SWITCH)}
