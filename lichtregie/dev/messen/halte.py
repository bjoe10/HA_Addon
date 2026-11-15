#!/usr/bin/env python3
"""Kopf in 16-Bit-Position halten und live verstellen (nur Standardbibliothek).

Der Kopf bleibt auf der eingegebenen Position, bis du eine neue eingibst.
Eingabe im Terminal:  <pan> <tilt>      z. B.  41216 7168
                      q                  beenden (Kopf wird dunkel)

Kanäle wie in der configuration.yaml:
  Kopf 1 (192.168.178.144): pan 1-2, tilt 3-4, dimmer 8, speed 9, auto 10, config 11
  Kopf 2 (192.168.178.146): pan2 12-13, tilt2 14-15, dimmer2 19, speed2 20, auto2 21, config2 22

Aufruf:  python3 halte.py --kopf 1
"""
import argparse
import socket
import struct
import threading
import time

ART_PORT = 6454
FPS = 40
NODES = {1: "192.168.178.144", 2: "192.168.178.146"}
LAYOUT = {
    1: {"pan": 1, "tilt": 3, "dimmer": 8, "speed": 9, "auto": 10, "config": 11},
    2: {"pan": 12, "tilt": 14, "dimmer": 19, "speed": 20, "auto": 21, "config": 22},
}


def artdmx(universe, data, seq):
    header = b"Art-Net\x00" + struct.pack("<H", 0x5000) + struct.pack(">H", 14)
    header += bytes([seq, 0, universe & 0xFF, (universe >> 8) & 0x7F])
    return header + struct.pack(">H", len(data)) + data


class Head:
    def __init__(self, kopf, speed):
        self.kopf = kopf
        self.ch = LAYOUT[kopf]
        self.lock = threading.Lock()
        self.buf = bytearray(512)
        self.set8(self.ch["speed"], speed)
        self.set8(self.ch["auto"], 0)
        self.set8(self.ch["config"], 0)
        self.set8(self.ch["dimmer"], 255)

    def set8(self, ch, value):
        self.buf[ch - 1] = max(0, min(255, int(value)))

    def set16(self, ch, value):
        value = max(0, min(65535, int(value)))
        self.buf[ch - 1] = value >> 8
        self.buf[ch] = value & 0xFF

    def position(self, pan, tilt):
        with self.lock:
            self.set16(self.ch["pan"], pan)
            self.set16(self.ch["tilt"], tilt)

    def blackout(self):
        with self.lock:
            self.set8(self.ch["dimmer"], 0)


def sender(head, stop, sock, ip):
    seq = 1
    while not stop.is_set():
        with head.lock:
            data = bytes(head.buf)
        sock.sendto(artdmx(1, data, seq), (ip, ART_PORT))
        seq = (seq + 1) % 256 or 1
        time.sleep(1.0 / FPS)


def main():
    parser = argparse.ArgumentParser(description="Moving Head in 16-Bit-Position halten")
    parser.add_argument("--kopf", type=int, choices=(1, 2), required=True)
    parser.add_argument("--ip", help="Node-IP überschreiben")
    parser.add_argument("--pan", type=int, default=32768)
    parser.add_argument("--tilt", type=int, default=32768)
    parser.add_argument("--speed", type=int, default=0, help="motor speed 0 (schnell) bis 255 (langsam)")
    args = parser.parse_args()

    ip = args.ip or NODES[args.kopf]
    head = Head(args.kopf, args.speed)
    head.position(args.pan, args.tilt)
    stop = threading.Event()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    thread = threading.Thread(target=sender, args=(head, stop, sock, ip), daemon=True)
    thread.start()

    print(f"Kopf {args.kopf} an {ip}, Pan {args.pan}, Tilt {args.tilt}, Speed {args.speed}")
    print("Eingabe: '<pan> <tilt>' (0-65535), 'q' beendet.")
    try:
        while True:
            line = input("> ").strip()
            if line.lower() in ("q", "quit", "exit"):
                break
            parts = line.split()
            if len(parts) != 2:
                print("Bitte zwei Zahlen eingeben, z. B. 41216 7168")
                continue
            try:
                pan, tilt = int(parts[0]), int(parts[1])
            except ValueError:
                print("Nur ganze Zahlen 0-65535")
                continue
            head.position(pan, tilt)
            print(f"  -> Pan {pan}, Tilt {tilt}")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        head.blackout()
        time.sleep(0.5)
        stop.set()
        thread.join(timeout=1)
        sock.close()
        print("Beendet, Kopf dunkel.")


if __name__ == "__main__":
    main()
