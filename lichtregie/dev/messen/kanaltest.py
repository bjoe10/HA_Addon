#!/usr/bin/env python3
"""Kanal-Test für einen Moving Head: ein DMX-Kanal wird Schritt für Schritt durchgefahren (nur Standardbibliothek).

Pan und Tilt bleiben fest. So finden wir heraus, welcher Wert welche Farbe, welches Gobo,
welche Strobe-Stufe oder welches eingebaute Programm ist. Die Beobachtungen notierst du, der Test
schreibt nur die Werte mit Zeitstempel.

Kanäle (Uking-Layout aus configuration.yaml):
  Kopf 1: color 5, gobo 6, strobe 7, dimmer 8, speed 9, auto 10, config 11
  Kopf 2: color2 16, gobo2 17, strobe2 18, dimmer2 19, speed2 20, auto2 21, config2 22

Aufruf:  python3 kanaltest.py --kopf 1 --kanal color --schritt 16 --halte 2

Achtung: Der Test steuert den Kopf direkt. Die Web-App muss dafür gestoppt sein.
Bei Strobe nur kleine Schritte und kurze Zeiten, Blitzlicht kann für Menschen mit Epilepsie gefährlich sein.
"""
import argparse
import socket
import threading
import time

from halte import ART_PORT, FPS, NODES, Head, artdmx

CHANNELS = {
    1: {"color": 5, "gobo": 6, "strobe": 7, "dimmer": 8, "speed": 9, "auto": 10, "config": 11},
    2: {"color": 16, "gobo": 17, "strobe": 18, "dimmer": 19, "speed": 20, "auto": 21, "config": 22},
}


def sender(head, stop, sock, ip):
    seq = 1
    while not stop.is_set():
        with head.lock:
            data = bytes(head.buf)
        sock.sendto(artdmx(1, data, seq), (ip, ART_PORT))
        seq = (seq + 1) % 256 or 1
        time.sleep(1.0 / FPS)


def main():
    parser = argparse.ArgumentParser(description="Einen DMX-Kanal eines Moving Heads durchfahren")
    parser.add_argument("--kopf", type=int, choices=(1, 2), required=True)
    parser.add_argument("--kanal", choices=sorted(CHANNELS[1]), required=True)
    parser.add_argument("--von", type=int, default=0)
    parser.add_argument("--bis", type=int, default=255)
    parser.add_argument("--schritt", type=int, default=16)
    parser.add_argument("--halte", type=float, default=2.0, help="Sekunden pro Wert")
    parser.add_argument("--pan", type=int, default=32768)
    parser.add_argument("--tilt", type=int, default=32768)
    args = parser.parse_args()

    head = Head(args.kopf, speed=0)
    head.position(args.pan, args.tilt)
    ch = CHANNELS[args.kopf][args.kanal]
    with head.lock:
        for name in ("gobo", "strobe", "color"):
            head.set8(CHANNELS[args.kopf][name], 0)
        head.set8(CHANNELS[args.kopf]["dimmer"], 255)

    ip = NODES[args.kopf]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stop = threading.Event()
    thread = threading.Thread(target=sender, args=(head, stop, sock, ip), daemon=True)
    thread.start()

    print(f"Kopf {args.kopf}, Kanal {args.kanal} (DMX {ch}), {args.von} bis {args.bis} in Schritten von {args.schritt}")
    try:
        for value in range(args.von, args.bis + 1, args.schritt):
            with head.lock:
                head.set8(ch, value)
            print(f"{time.strftime('%H:%M:%S')}  Wert {value}", flush=True)
            time.sleep(args.halte)
    except KeyboardInterrupt:
        pass
    finally:
        head.blackout()
        time.sleep(0.5)
        stop.set()
        thread.join(timeout=1)
        sock.close()
        print("Ende, Kopf dunkel.")


if __name__ == "__main__":
    main()
