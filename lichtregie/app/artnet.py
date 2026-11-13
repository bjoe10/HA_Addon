"""Art-Net: ArtDMX-Pakete und Kanalpuffer je Kopf (nur Standardbibliothek)."""
import struct
import threading

ART_PORT = 6454
FPS = 40


def artdmx(universe, data, seq):
    """ArtDMX-Paket nach Art-Net-Spezifikation, danach 512 Kanäle."""
    header = b"Art-Net\x00" + struct.pack("<H", 0x5000) + struct.pack(">H", 14)
    header += bytes([seq, 0, universe & 0xFF, (universe >> 8) & 0x7F])
    return header + struct.pack(">H", len(data)) + data


class Head:
    """Kanalpuffer eines Kopfes. ch = {funktion: DMX-Kanal} (pan/tilt 16 Bit ab dem genannten Kanal)."""

    def __init__(self, ch, speed=0):
        self.ch = dict(ch)
        self.lock = threading.Lock()
        self.buf = bytearray(512)
        self.set8(self.ch["speed"], speed)   # 0 = schnellste Bewegung
        self.set8(self.ch["auto"], 0)        # eingebaute Programme aus
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
