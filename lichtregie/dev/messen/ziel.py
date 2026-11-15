#!/usr/bin/env python3
"""Zielpunkt im Raum: beide Köpfe auf einen Punkt richten (nur Standardbibliothek).

Rechnet mit dem Fit aus kalibrierung_fit.py (Stand: dritter Fit) Pan und Tilt für beide Köpfe
aus und gibt die Werte aus. Mit --send fahren die Köpfe dorthin und halten die Position,
bis Strg+C. Danach wird der Kopf dunkel geschaltet.

Raumkoordinaten wie in kalibrierung_fit.py: x = 0 linke Wand, x = 5 rechte Wand,
y = 0 TV-Wand, y = 6 Kopf-Wand, z = 0 Boden.

Beispiele:
  python3 ziel.py --x 2.5 --y 0 --z 1.0            # nur ausrechnen (TV-Mitte)
  python3 ziel.py --x 2.2 --y 3.5 --z 0.75 --send  # Tisch anfahren und halten
"""
import argparse
import socket
import threading
import time

from halte import ART_PORT, FPS, NODES, Head, artdmx
from kalibrierung_fit import angles

# Ergebnis des dritten Fits (kalibrierung_fit.py), gerundet
MODEL = {
    1: {"pos": (4.90, 5.90, 2.50), "ap": 23475, "bp": -112.4, "at": 2223, "bt": -450.9},
    2: {"pos": (0.10, 5.90, 2.50), "ap": 44122, "bp": -121.7, "at": 63019, "bt": 429.8},
}


def clamp16(v):
    return max(0, min(65535, int(round(v))))


def pan_tilt(kopf, target, current_pan=None):
    """Pan und Tilt für einen Raumpunkt. Pan wird so gewählt, dass der Kopf den kurzen Weg
    von `current_pan` nimmt. Ohne Angabe liegt die Wahl in der Mitte des Schwenkbereichs."""
    m = MODEL[kopf]
    phi, theta = angles(m["pos"], target)
    raw = m["ap"] + m["bp"] * phi
    turn = 360.0 * abs(m["bp"])  # DMX-Werte für eine volle Drehung
    ref = 32768 if current_pan is None else current_pan
    candidates = [raw + n * turn for n in range(-2, 3)]
    valid = [c for c in candidates if 0 <= c <= 65535] or [max(0.0, min(65535.0, raw))]
    pan = min(valid, key=lambda c: abs(c - ref))
    return clamp16(pan), clamp16(m["at"] + m["bt"] * theta)


def main():
    parser = argparse.ArgumentParser(description="Beide Köpfe auf einen Raumpunkt richten")
    parser.add_argument("--x", type=float, required=True)
    parser.add_argument("--y", type=float, required=True)
    parser.add_argument("--z", type=float, required=True)
    parser.add_argument("--send", action="store_true", help="Köpfe dorthin fahren und halten")
    parser.add_argument("--speed", type=int, default=0, help="motor speed 0 (schnell) bis 255")
    args = parser.parse_args()

    target = (args.x, args.y, args.z)
    values = {k: pan_tilt(k, target) for k in MODEL}
    print(f"Ziel: x={args.x} y={args.y} z={args.z}")
    for k, (pan, tilt) in values.items():
        print(f"  Kopf {k}: pan {pan}, tilt {tilt}   (HA-Slider: {pan >> 8} / {tilt >> 8} grob)")
    if not args.send:
        print("Mit --send fahren die Köpfe dorthin.")
        return

    heads = {k: Head(k, args.speed) for k in MODEL}
    for k, (pan, tilt) in values.items():
        heads[k].position(pan, tilt)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stop = threading.Event()

    def send_loop():
        seq = 1
        while not stop.is_set():
            for k, head in heads.items():
                with head.lock:
                    data = bytes(head.buf)
                sock.sendto(artdmx(1, data, seq), (NODES[k], ART_PORT))
            seq = (seq + 1) % 256 or 1
            time.sleep(1.0 / FPS)

    thread = threading.Thread(target=send_loop, daemon=True)
    thread.start()
    print("Halten. Strg+C beendet und schaltet beide Köpfe dunkel.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for head in heads.values():
            head.blackout()
        time.sleep(0.5)
        stop.set()
        thread.join(timeout=1)
        sock.close()
        print("Beendet, beide Köpfe dunkel.")


if __name__ == "__main__":
    main()
