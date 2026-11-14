"""Live-Audioanalyse: Schlagphase, Pegel, Breaks und Drops aus der Musik, die gerade läuft.

Quelle ist der AirPlay-Empfänger im Add-on (shairport-sync, Ausgabe in eine Pipe als S16LE-Stereo, 44,1 kHz).
Music Assistant spielt synchron an den Phantom und an diesen Empfänger, die Analyse hört also dieselbe
Musik zur selben Zeit.

Vorgehen:
- FFT über 2048 Samples alle 512 Samples (11,6 ms). Bassenergie (40–150 Hz) und breitbandiger
  Spektralfluss ergeben eine Onset-Kurve; Spitzen darin sind Kicks und Anschläge.
- Das Tempo kommt als Vorgabe aus der Datenbank (bpm_hint), sonst aus der Autokorrelation der Onset-Kurve.
- Ein Phasenregler rastet das Schlagraster auf die erkannten Onsets ein.
- Break: der Bass ist über 2 s deutlich leiser als sonst. Drop: nach einem Break kommt der Bass zurück.
"""
import math
import threading
import time
from collections import deque

import numpy as np

RATE = 44100
HOP = 512
N = 2048
HOP_SEC = HOP / RATE
ONSET_LAG = 0.012   # gemessen: Onsets werden durch das FFT-Fenster ca. 12 ms zu spät erkannt


class Analyzer:
    def __init__(self):
        self.lock = threading.Lock()
        self.buf = np.zeros(N, dtype=np.float32)
        self.win = np.hanning(N).astype(np.float32)
        freqs = np.fft.rfftfreq(N, 1.0 / RATE)
        self.bass_bins = (freqs >= 40) & (freqs < 150)
        self.broad_bins = (freqs >= 150) & (freqs < 8000)
        self.pending = np.zeros(0, dtype=np.float32)
        self.prev_log_bass = 0.0
        self.prev_log_spec = None
        self.onset_hist = deque(maxlen=int(2.0 / HOP_SEC))     # Schwelle über 2 s
        self.env = deque(maxlen=int(8.0 / HOP_SEC))            # Onset-Kurve für die Tempo-Schätzung
        self.last3 = deque(maxlen=3)
        self.last_onset = 0.0
        self.onset_times = deque(maxlen=64)
        self.last_audio = 0.0
        self.bpm_hint = None
        self.period = None
        self.t_beat = None
        self.hits = deque(maxlen=48)                           # (Zeit, getroffen?) für die Sicherheit
        self.last_hit = 0.0
        self.hit_count = 0
        self.misses = 0
        self.level = 0.0
        self.level_peak = 1e-4
        self.bass = 0.0
        self.bass_peak = 1e-6
        self.bass_short = 0.0
        self.break_on = False
        self.quiet_since = None
        self.drop_at = 0.0
        self._last_tempo = 0.0

    # --- Eingang -------------------------------------------------------------------------------------
    def feed_pcm(self, data, t_end):
        """Rohdaten (S16LE stereo) einspeisen; t_end = Zeitpunkt des letzten Samples."""
        if len(data) < 4:
            return
        data = data[: len(data) - len(data) % 4]
        x = np.frombuffer(data, dtype="<i2").astype(np.float32).reshape(-1, 2).mean(axis=1) / 32768.0
        self.feed(x, t_end)

    def feed(self, mono, t_end):
        with self.lock:
            self.pending = np.concatenate([self.pending, mono.astype(np.float32)])
            while len(self.pending) >= HOP:
                hop = self.pending[:HOP]
                self.pending = self.pending[HOP:]
                t_hop = t_end - len(self.pending) / RATE
                self._process(hop, t_hop)

    def set_bpm_hint(self, bpm):
        with self.lock:
            self.bpm_hint = float(bpm) if bpm else None
            if self.bpm_hint:
                self.period = 60.0 / self.bpm_hint

    # --- Verarbeitung je 11,6 ms -----------------------------------------------------------------------
    def _process(self, hop, t):
        self.buf = np.concatenate([self.buf[HOP:], hop])
        rms = float(np.sqrt(np.mean(hop * hop)))
        if rms < 1e-3:            # Stille: nichts lernen
            self.prev_log_spec = None
            return
        self.last_audio = t
        mag = np.abs(np.fft.rfft(self.buf * self.win))
        e_bass = float(np.mean(mag[self.bass_bins] ** 2))
        log_bass = math.log1p(e_bass)
        log_spec = np.log1p(mag[self.broad_bins])
        bass_flux = max(0.0, log_bass - self.prev_log_bass)
        broad_flux = 0.0
        if self.prev_log_spec is not None:
            broad_flux = float(np.mean(np.maximum(0.0, log_spec - self.prev_log_spec)))
        self.prev_log_bass, self.prev_log_spec = log_bass, log_spec
        onset = bass_flux + 2.0 * broad_flux
        self.onset_hist.append(onset)
        self.env.append(onset)
        self._levels(rms, e_bass, t)
        self._peak_pick(onset, t)
        if t - self._last_tempo > 1.0:
            self._last_tempo = t
            self._tempo()

    def _levels(self, rms, e_bass, t):
        a = 0.3 if rms > self.level else 0.03
        self.level += a * (rms - self.level)
        self.level_peak = max(self.level, self.level_peak * 0.99995)
        b = math.sqrt(e_bass)
        a = 0.3 if b > self.bass else 0.05
        self.bass += a * (b - self.bass)
        self.bass_peak = max(self.bass, self.bass_peak * 0.99995)
        self.bass_short += 0.05 * (self.bass / self.bass_peak - self.bass_short)   # ca. 0,25 s
        if self.bass_short < 0.3:
            self.quiet_since = self.quiet_since or t
            if t - self.quiet_since > 2.0:
                self.break_on = True
        else:
            self.quiet_since = None
        # Drop: nach einem Break der erste kräftige Bass-Schlag (ungeglättet, damit er sofort zählt)
        if self.break_on and self.bass / self.bass_peak > 0.6:
            self.break_on = False
            self.quiet_since = None
            self.drop_at = t

    def _peak_pick(self, onset, t):
        self.last3.append((onset, t))
        if len(self.last3) < 3 or len(self.onset_hist) < 20:
            return
        (a, _), (b, tb), (c, _) = self.last3
        hist = np.fromiter(self.onset_hist, dtype=np.float32)
        thresh = float(hist.mean() + 1.5 * hist.std())
        if b > a and b >= c and b > thresh and tb - self.last_onset > 0.18:
            self.last_onset = tb
            self.onset_times.append(tb - ONSET_LAG)
            self._pll(tb - ONSET_LAG)

    def _tempo(self):
        """Ohne Vorgabe: Tempo aus der Autokorrelation der Onset-Kurve (70–180 BPM, Vorliebe um 120)."""
        if self.bpm_hint or len(self.env) < int(4.0 / HOP_SEC):
            return
        e = np.fromiter(self.env, dtype=np.float32)
        e = e - e.mean()
        ac = np.correlate(e, e, mode="full")[len(e) - 1:]
        lo, hi = int(60.0 / 180 / HOP_SEC), int(60.0 / 70 / HOP_SEC)
        lags = np.arange(lo, hi + 1)
        bpms = 60.0 / (lags * HOP_SEC)
        weight = np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.6) ** 2)
        best = int(lags[np.argmax(ac[lo:hi + 1] * weight)])
        if ac[best] <= 0:
            return
        # Spitze zwischen den Rasterpunkten interpolieren (sonst nur 11,6-ms-Schritte, ca. 1 % Tempofehler)
        y0, y1, y2 = ac[best - 1], ac[best], ac[best + 1]
        denom = y0 - 2 * y1 + y2
        shift = 0.5 * (y0 - y2) / denom if denom < 0 else 0.0
        new = (best + max(-0.5, min(0.5, shift))) * HOP_SEC
        self.period = new if self.period is None else 0.8 * self.period + 0.2 * new

    def _pll(self, t_on):
        """Schlagraster auf das Onset ziehen."""
        if not self.period:
            return
        if self.t_beat is None:
            self.t_beat = t_on
            return
        n = round((t_on - self.t_beat) / self.period)
        expected = self.t_beat + n * self.period
        err = t_on - expected
        hit = abs(err) < 0.2 * self.period
        self.hits.append((t_on, hit))
        if not hit:
            # Vier Fehlschläge in Folge: das Raster ist weggedriftet oder falsch eingerastet → neu ansetzen
            self.misses += 1
            if self.misses >= 4:
                self.t_beat = t_on
                self.misses = 0
            return
        self.misses = 0
        if hit:
            self.last_hit = t_on
            self.hit_count += 1
            self.t_beat = expected + 0.25 * err
            if not self.bpm_hint:   # ohne Vorgabe auch das Tempo leicht nachführen
                self.period *= 1.0 + max(-0.002, min(0.002, 0.01 * err / self.period))

    # --- Ausgang -------------------------------------------------------------------------------------------
    def confidence(self, now):
        recent = [h for (tt, h) in self.hits if now - tt < 8.0]
        return sum(recent) / len(recent) if len(recent) >= 4 else 0.0

    def signal(self, now=None):
        """Kommt gerade Musik an? Dann gelten Pegel, Break und Drop."""
        now = time.time() if now is None else now
        with self.lock:
            return now - self.last_audio < 1.5

    def phase_ok(self, now=None):
        """Ist das Schlagraster eingerastet? Es läuft auch ohne neue Kicks (Break) bis zu 30 s weiter."""
        now = time.time() if now is None else now
        with self.lock:
            return (now - self.last_audio < 1.5 and self.period is not None and self.t_beat is not None
                    and self.hit_count >= 4 and now - self.last_hit < 30.0)

    active = phase_ok

    def phase(self, t):
        """Anteil des aktuellen Schlags (0 = Schlag, 0,5 = genau dazwischen)."""
        with self.lock:
            return ((t - self.t_beat) / self.period) % 1.0

    def live(self, now, bpm):
        """Live-Zustand für die Show."""
        with self.lock:
            beat = 60.0 / bpm
            return {
                "level": min(1.0, self.level / self.level_peak),
                "bass": min(1.0, self.bass / self.bass_peak),
                "break": self.break_on,
                "drop": now - self.drop_at < 16 * beat,
                "drop_beats": (now - self.drop_at) / beat,
            }

    def status(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            on = now - self.last_audio < 1.5
            return {
                "an": on,
                "takt": on and self.period is not None and self.hit_count >= 4 and now - self.last_hit < 30.0,
                "bpm": round(60.0 / self.period, 1) if self.period else None,
                "sicher": round(self.confidence(now), 2),
                "pegel": round(min(1.0, self.level / self.level_peak), 2) if on else 0.0,
                "bass": round(min(1.0, self.bass / self.bass_peak), 2) if on else 0.0,
                "break": self.break_on, "drop": now - self.drop_at < 8.0,
            }


def reader(analyzer, path, stop=None):
    """Liest die Pipe von shairport-sync. Ohne Wiedergabe ist die Pipe geschlossen; dann wird gewartet."""
    while stop is None or not stop.is_set():
        try:
            with open(path, "rb", buffering=0) as pipe:
                while True:
                    data = pipe.read(HOP * 4)
                    if not data:
                        break          # Schreiber hat die Pipe geschlossen (Wiedergabe beendet)
                    analyzer.feed_pcm(data, time.time())
        except OSError:
            time.sleep(2.0)
