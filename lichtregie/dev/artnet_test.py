#!/usr/bin/env python3
"""Art-Net-Test für Moving Head 1 (Node 192.168.178.144, Universe 1).

Sendet ArtDMX-Pakete direkt an den Node und fährt Pan von 0 nach Maximum und zurück.
Dabei werden Startzeiten ausgegeben, damit sie sich mit einem Video abgleichen lassen.

Kanalbelegung laut configuration.yaml (Moving Head 1):
  1-2 pan (16 Bit), 3-4 tilt (16 Bit), 5 color, 6 grobo, 7 strobe,
  8 dimmer, 9 motor speed, 10 auto mode, 11 config mode

Nur Standardbibliothek. Aufruf (vom Mac, im selben WLAN):
  python3 artnet_test.py --speed 0
  python3 artnet_test.py --speed 128 --hold 6

Während des Tests darf HA diesen Kopf nicht gleichzeitig steuern.
Abbruch mit Strg+C: der Kopf wird danach dunkel geschaltet.
"""
import argparse
import socket
import struct
import time

ART_PORT = 6454
FPS = 40
FRAME = 1.0 / FPS


def artdmx(universe, data, seq=0):
    """ArtDMX-Paket: Header nach Art-Net-Spezifikation, dann 512 Kanäle."""
    header = b"Art-Net\x00"
    header += struct.pack("<H", 0x5000)          # OpCode ArtDMX, Little-Endian
    header += struct.pack(">H", 14)              # Protokollversion
    header += bytes([seq, 0])                    # Sequenz, Physical
    header += bytes([universe & 0xFF, (universe >> 8) & 0x7F])  # SubUni, Net
    header += struct.pack(">H", len(data))       # Länge, Big-Endian
    return header + data


class Head:
    """Kanalpuffer für einen Kopf, Kanäle wie in der configuration.yaml."""

    def __init__(self, speed, tilt):
        self.buf = bytearray(512)
        self.set8(9, speed)      # motor speed
        self.set8(10, 0)         # auto mode aus
        self.set8(11, 0)         # config mode aus
        self.set8(8, 255)        # dimmer voll
        self.set8(5, 0)          # color
        self.set8(6, 0)          # grobo
        self.set8(7, 0)          # strobe aus
        self.set16(3, tilt)     # tilt fest

    def set8(self, ch, value):
        self.buf[ch - 1] = max(0, min(255, int(value)))

    def set16(self, ch, value):
        value = max(0, min(65535, int(value)))
        self.buf[ch - 1] = value >> 8
        self.buf[ch] = value & 0xFF

    def set_pan(self, value):
        self.set16(1, value)


def send_for(sock, ip, universe, head, seconds, seq):
    """Hält den aktuellen Zustand für `seconds` Sekunden mit FPS Bildern pro Sekunde."""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        sock.sendto(artdmx(universe, bytes(head.buf), seq), (ip, ART_PORT))
        seq = (seq + 1) % 256 or 1
        time.sleep(FRAME)
    return seq


def stamp(text):
    print(f"{time.strftime('%H:%M:%S')}  {text}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Art-Net-Test Moving Head 1")
    parser.add_argument("--ip", default="192.168.178.144", help="IP des Art-Net-Nodes")
    parser.add_argument("--universe", type=int, default=1)
    parser.add_argument("--speed", type=int, default=0, help="motor speed, Kanal 9 (0-255)")
    parser.add_argument("--tilt", type=int, default=32768, help="tilt 16 Bit (0-65535), Mitte = 32768")
    parser.add_argument("--hold", type=float, default=6.0, help="Sekunden, die der Kopf auf dem Ziel bleibt")
    parser.add_argument("--settle", type=float, default=4.0, help="Sekunden zum Einrichten bei Pan 0")
    args = parser.parse_args()

    head = Head(speed=args.speed, tilt=args.tilt)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = 1

    print(f"Node {args.ip}, Universe {args.universe}, motor speed {args.speed}, tilt {args.tilt}")
    print("Stoppe die Zeit, sobald 'START' steht, und notiere, wann der Kopf am Ziel ist.\n")

    try:
        head.set_pan(0)
        stamp("Einrichten: Pan 0")
        seq = send_for(sock, args.ip, args.universe, head, args.settle, seq)

        head.set_pan(65535)
        t0 = time.perf_counter()
        stamp("START: Pan 0 -> Maximum")
        seq = send_for(sock, args.ip, args.universe, head, args.hold, seq)
        stamp(f"Ende Hold ({args.hold:.1f} s nach START)")

        head.set_pan(0)
        stamp("START: Pan Maximum -> 0")
        seq = send_for(sock, args.ip, args.universe, head, args.hold, seq)
        stamp("Ende Test")
    except KeyboardInterrupt:
        stamp("Abbruch")
    finally:
        head.set8(8, 0)  # dimmer aus
        for _ in range(FPS // 2):
            sock.sendto(artdmx(args.universe, bytes(head.buf), seq), (args.ip, ART_PORT))
            seq = (seq + 1) % 256 or 1
            time.sleep(FRAME)
        sock.close()


if __name__ == "__main__":
    main()
