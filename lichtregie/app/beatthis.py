"""Beat This! in numpy: Schläge und „1“-Schläge (Downbeats) aus einem Tonausschnitt.

Modell und Gewichte: „Beat This! Accurate Beat Tracking Without DBN Postprocessing“ (Foscarin, Schlüter, Widmer,
ISMIR 2024), https://github.com/CPJKU/beat_this, MIT-Lizenz; Gewichte „final0“. Im Add-on gibt es weder PyTorch
noch ONNX Runtime (Alpine), deshalb ist die Rechnung hier mit numpy nachgebaut: Gewichte als float16 in
modelle/beat_this.npz (umgewandelt mit musik-analyse/werkzeug/export_npz.py), gerechnet wird in float32.
Geprüft gegen das Original mit dev/test_beatthis.py (Abweichung der Logits siehe dort).

Ablauf wie im Original: 22,05 kHz, Mel-Spektrogramm (128 Bänder, 50 Bilder/s, log1p(1000·x)), Vorbau aus
Faltungen und Teil-Transformern über Frequenz und Zeit, 6 Transformer-Schichten mit Rotary-Positionen, Ausgang
für Schlag und „1“; lange Stücke in Abschnitten zu 1500 Bildern (30 s). Nachbearbeitung „minimal“ (Spitzen über
50 % innerhalb ±70 ms, die „1“ auf den nächsten Schlag gelegt).
"""
import time
from pathlib import Path

import numpy as np

FILE = Path(__file__).resolve().parent / "modelle" / "beat_this.npz"
HOP = 441
NFFT = 1024
FPS = 50
CHUNK = 1500
BORDER = 6
HEAD_DIM = 32
EPS_BN = 1e-5


def _erf(x):
    """Fehlerfunktion (Abramowitz/Stegun 7.1.26, Fehler unter 1,5e-7); numpy hat keine eigene."""
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t \
        * np.exp(-a * a)
    return s * y


def gelu(x):
    return 0.5 * x * (1.0 + _erf(x * np.float32(0.7071067811865476)))


def _fftconv(x, h):
    n = len(x) + len(h) - 1
    size = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(h, size), size)[:n]
    return y[len(h) // 2: len(h) // 2 + len(x)]


_LP = None


def resample_44k(x):
    """44,1 kHz → 22,05 kHz: Tiefpass (Kaiser-gefenstertes sinc, 10,5 kHz) und jeden zweiten Wert nehmen."""
    global _LP
    if _LP is None:
        n = np.arange(-127, 128)
        fc = 10500.0 / 44100.0
        _LP = (2 * fc * np.sinc(2 * fc * n) * np.kaiser(len(n), 8.6)).astype(np.float64)
        _LP /= _LP.sum()
    return _fftconv(np.asarray(x, dtype=np.float64), _LP)[::2].astype(np.float32)


class BeatThis:
    def __init__(self, path=FILE):
        z = np.load(path)
        self.w = {k: z[k].astype(np.float32) for k in z.files}
        self.fb = self.w.pop("_mel_fb")
        self.win = self.w.pop("_window")
        self._rot = {}

    # --- Bausteine ---------------------------------------------------------------------------------------
    def _lin(self, x, name, bias=True):
        y = x @ self.w[name + ".weight"].T
        if bias and name + ".bias" in self.w:
            y = y + self.w[name + ".bias"]
        return y

    @staticmethod
    def _rms(x, gamma):
        norm = np.sqrt(np.sum(x * x, axis=-1, keepdims=True))
        return x / np.maximum(norm, 1e-12) * np.float32(np.sqrt(x.shape[-1])) * gamma

    def _bn(self, x, name, axis_shape):
        rm, rv = self.w[name + ".running_mean"], self.w[name + ".running_var"]
        g, b = self.w[name + ".weight"], self.w[name + ".bias"]
        scale = (g / np.sqrt(rv + EPS_BN)).reshape(axis_shape)
        return (x - rm.reshape(axis_shape)) * scale + b.reshape(axis_shape)

    def _rotary(self, n):
        if n not in self._rot:
            inv = 1.0 / (10000.0 ** (np.arange(0, HEAD_DIM, 2, dtype=np.float32) / HEAD_DIM))
            ang = np.repeat(np.arange(n, dtype=np.float32)[:, None] * inv[None, :], 2, axis=1)   # (n, 32)
            self._rot[n] = (np.cos(ang).astype(np.float32), np.sin(ang).astype(np.float32))
        return self._rot[n]

    @staticmethod
    def _rot_half(x):
        x2 = x.reshape(x.shape[:-1] + (HEAD_DIM // 2, 2))
        return np.stack((-x2[..., 1], x2[..., 0]), axis=-1).reshape(x.shape)

    def _attn(self, x, name):
        """x: (N, n, d) → (N, n, d); Kopfgröße 32, Gating je Kopf, Rotary über die Folge n."""
        N, n, d = x.shape
        h = d // HEAD_DIM
        xn = self._rms(x, self.w[name + ".norm.gamma"])
        qkv = (xn @ self.w[name + ".to_qkv.weight"].T).reshape(N, n, 3, h, HEAD_DIM).transpose(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], np.ascontiguousarray(qkv[2])  # (N, h, n, 32)
        cos, sin = self._rotary(n)
        q = q * cos + self._rot_half(q) * sin
        k = np.ascontiguousarray((k * cos + self._rot_half(k) * sin).transpose(0, 1, 3, 2))   # (N, h, 32, n)
        out = np.empty_like(q)
        step = max(1, int(8e6 // (h * n * n)))                 # Speicher der Aufmerksamkeitsmatrix begrenzen
        scale = np.float32(HEAD_DIM ** -0.5)
        for i in range(0, N, step):
            s = (q[i:i + step] * scale) @ k[i:i + step]
            s -= s.max(axis=-1, keepdims=True)
            np.exp(s, out=s)
            s /= s.sum(axis=-1, keepdims=True)
            out[i:i + step] = s @ v[i:i + step]
        gates = 1.0 / (1.0 + np.exp(-self._lin(xn, name + ".to_gates")))   # (N, n, h)
        out = out * gates.transpose(0, 2, 1)[..., None]
        out = out.transpose(0, 2, 1, 3).reshape(N, n, h * HEAD_DIM)
        return out @ self.w[name + ".to_out.0.weight"].T

    def _ff(self, x, name):
        y = self._rms(x, self.w[name + ".net.0.gamma"])
        y = gelu(self._lin(y, name + ".net.1"))
        return self._lin(y, name + ".net.4")

    def _conv(self, x, name, kh, sh):
        """x: (C, F, T); Kern (kh, 3), Schritt (sh, 1), Rand (0, 1), ohne Bias → (O, F', T)."""
        W = self.w[name + ".weight"]                           # (O, C, kh, 3)
        C, F, T = x.shape
        xp = np.pad(x, ((0, 0), (0, 0), (1, 1)))
        Fo = (F - kh) // sh + 1
        cols = np.empty((C, kh, 3, Fo, T), dtype=np.float32)
        for i in range(kh):
            for j in range(3):
                cols[:, i, j] = xp[:, i:i + sh * (Fo - 1) + 1:sh, j:j + T]
        y = W.reshape(W.shape[0], -1) @ cols.reshape(C * kh * 3, Fo * T)
        return y.reshape(W.shape[0], Fo, T)

    # --- Netz --------------------------------------------------------------------------------------------
    def logits(self, spect):
        """spect: (T, 128) → (Schlag, „1“) als Logits je Bild, Länge T."""
        T = spect.shape[0]
        t0 = time.perf_counter()
        x = self._bn(spect.T, "frontend.stem.bn1d", (-1, 1))                  # (128, T)
        x = self._conv(x[None], "frontend.stem.conv2d", 4, 4)                   # (32, 32, T)
        x = gelu(self._bn(x, "frontend.stem.bn2d", (-1, 1, 1)))
        for i in range(3):
            p = f"frontend.blocks.{i}"
            xf = np.ascontiguousarray(x.transpose(2, 1, 0))                     # (T, F, C)
            xf = xf + self._attn(xf, p + ".partial.attnF")
            xf = xf + self._ff(xf, p + ".partial.ffF")
            xt = np.ascontiguousarray(xf.transpose(1, 0, 2))                    # (F, T, C)
            xt = xt + self._attn(xt, p + ".partial.attnT")
            xt = xt + self._ff(xt, p + ".partial.ffT")
            x = np.ascontiguousarray(xt.transpose(2, 0, 1))                     # (C, F, T)
            x = gelu(self._bn(self._conv(x, p + ".conv2d", 2, 2), p + ".norm", (-1, 1, 1)))
        C, F, _ = x.shape
        x = self._lin(x.transpose(2, 0, 1).reshape(T, C * F), "frontend.linear")   # (T, 512)
        t1 = time.perf_counter()
        for i in range(6):
            p = f"transformer_blocks.layers.{i}"
            x = x + self._attn(x[None], p + ".0")[0]
            x = x + self._ff(x, p + ".1")
        x = self._rms(x, self.w["transformer_blocks.norm.gamma"])
        out = self._lin(x, "task_heads.beat_downbeat_lin")
        self.times["vorbau"] += t1 - t0
        self.times["transformer"] += time.perf_counter() - t1
        return out[:, 0] + out[:, 1], out[:, 1]

    def spect(self, audio_22k):
        x = np.pad(np.asarray(audio_22k, dtype=np.float32), NFFT // 2, mode="reflect")
        frames = np.lib.stride_tricks.sliding_window_view(x, NFFT)[::HOP]
        mag = np.abs(np.fft.rfft(frames * self.win, axis=1)).astype(np.float32) / np.float32(np.sqrt(NFFT))
        return np.log1p(1000.0 * (mag @ self.fb))

    def frames(self, spect):
        """Wie split_predict_aggregate im Original: Abschnitte zu 1500 Bildern, 6 Bilder Rand, das frühere gewinnt."""
        T = len(spect)
        starts = np.arange(-BORDER, T - BORDER, CHUNK - 2 * BORDER)
        if T > CHUNK - 2 * BORDER:
            starts[-1] = T - (CHUNK - BORDER)
        beat = np.full(T, -1000.0, dtype=np.float32)
        down = np.full(T, -1000.0, dtype=np.float32)
        for start in reversed(starts):
            lo, hi = max(start, 0), min(start + CHUNK, T)
            chunk = np.pad(spect[lo:hi], ((max(0, -start), max(0, min(BORDER, start + CHUNK - T))), (0, 0)))
            b, d = self.logits(chunk)
            a, e = start + BORDER, start + CHUNK - BORDER
            n = min(e, T) - max(a, 0)
            beat[max(a, 0):max(a, 0) + n] = b[BORDER + max(0, -a):][:n]
            down[max(a, 0):max(a, 0) + n] = d[BORDER + max(0, -a):][:n]
        return beat, down

    @staticmethod
    def _peaks(logit):
        pad = np.pad(logit, 3, constant_values=-np.inf)
        mx = np.lib.stride_tricks.sliding_window_view(pad, 7).max(axis=1)
        idx = np.nonzero((logit == mx) & (logit > 0))[0]
        out, p, c = [], None, 0
        for q in idx:                                          # benachbarte Spitzen zusammenfassen (Mittelwert)
            if p is not None and q - p <= 1:
                c += 1
                p += (q - p) / c
            else:
                if p is not None:
                    out.append(p)
                p, c = float(q), 1
        if p is not None:
            out.append(p)
        return np.array(out) / FPS

    def __call__(self, audio, sr=44100):
        """Ton (mono, float) → (Schläge, „1“-Schläge) in Sekunden ab Beginn des Ausschnitts."""
        self.times = {"spektrogramm": 0.0, "vorbau": 0.0, "transformer": 0.0}
        t0 = time.perf_counter()
        x = resample_44k(audio) if sr == 44100 else np.asarray(audio, dtype=np.float32)
        sp = self.spect(x)
        self.times["spektrogramm"] = time.perf_counter() - t0
        beat, down = self.frames(sp)
        beats, downs = self._peaks(beat), self._peaks(down)
        if len(beats):
            downs = np.unique(beats[np.argmin(np.abs(beats[None, :] - downs[:, None]), axis=1)]) if len(downs) \
                else downs
        return beats, downs


def _serve():
    """Worker für downbeat.py: liest [Länge (uint32), float32-Ton] von stdin, schreibt JSON je Ergebnis."""
    import json
    import struct
    import sys
    model = BeatThis()
    try:                                       # Diagnose: welche Rechenbibliothek nutzt numpy hier?
        cfg = np.show_config(mode="dicts")
        blas = cfg.get("Build Dependencies", {}).get("blas", {})
        print(f"Beat This bereit: numpy {np.__version__}, BLAS {blas.get('name')} {blas.get('version', '')}",
              file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 – nur Diagnose
        print(f"Beat This bereit: numpy {np.__version__}", file=sys.stderr, flush=True)
    inp, out = sys.stdin.buffer, sys.stdout
    with np.errstate(all="ignore"):
        while True:
            head = inp.read(4)
            if len(head) < 4:
                return
            n = struct.unpack("<I", head)[0]
            x = np.frombuffer(inp.read(n), dtype=np.float32)
            t0 = time.perf_counter()
            beats, downs = model(x, 44100)
            tm = " · ".join(f"{k} {v:.1f} s" for k, v in model.times.items())
            print(f"Beat This: {len(x) / 44100:.0f} s Ton in {time.perf_counter() - t0:.1f} s ({tm})", file=sys.stderr,
                  flush=True)
            out.write(json.dumps({"beats": [round(float(t), 4) for t in beats],
                                  "downs": [round(float(t), 4) for t in downs]}) + "\n")
            out.flush()


if __name__ == "__main__":
    import sys
    if "--worker" in sys.argv:
        _serve()
