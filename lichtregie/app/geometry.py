"""Raumgeometrie: Raumpunkt → Pan/Tilt je Kopf (Kalibrier-Fit, siehe KONZEPT.md und dev/kalibrierung_fit.py).

Achtung: Das Modell ist in x gespiegelt gegenüber den Raumkoordinaten der Show (x_modell = 5 - x).
Die Umrechnung macht der Aufrufer (server.py), hier wird nur im Modell gerechnet.
"""
import math

# Ergebnis des dritten Fits (Höhe 2,50 m und Wandabstand fest), gerundet
MODEL = {
    1: {"pos": (4.90, 5.90, 2.50), "ap": 23475, "bp": -112.4, "at": 2223, "bt": -450.9},
    2: {"pos": (0.10, 5.90, 2.50), "ap": 44122, "bp": -121.7, "at": 63019, "bt": 429.8},
}


def angles(p, t):
    dx, dy, dz = t[0] - p[0], t[1] - p[1], t[2] - p[2]
    return math.degrees(math.atan2(dx, dy)), math.degrees(math.atan2(dz, math.hypot(dx, dy)))


def clamp16(v):
    return max(0, min(65535, int(round(v))))


def pan_tilt(kopf, target, current_pan=None):
    """Pan und Tilt für einen Punkt im Modell. Pan wird so gewählt, dass der Kopf den kurzen Weg
    von `current_pan` nimmt (gleicher Winkel, eine volle Drehung weiter oder zurück)."""
    m = MODEL[kopf]
    phi, theta = angles(m["pos"], target)
    raw = m["ap"] + m["bp"] * phi
    turn = 360.0 * abs(m["bp"])
    ref = 32768 if current_pan is None else current_pan
    candidates = [raw + n * turn for n in range(-2, 3)]
    valid = [c for c in candidates if 0 <= c <= 65535] or [max(0.0, min(65535.0, raw))]
    pan = min(valid, key=lambda c: abs(c - ref))
    return clamp16(pan), clamp16(m["at"] + m["bt"] * theta)
