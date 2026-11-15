"""Schlagzählung für die Show: welcher Schlag im Takt und in der Phrase gerade dran ist.

Ohne Audio kommt die Zählung aus der Spotify-Position (HA, auf 1–3 s genau). Mit eingerastetem Audio-Takt
zählt die Lichtregie die Schläge selbst weiter (Phase aus der Analyse), damit Sprünge der HA-Position nicht
durchschlagen. Grob korrigiert wird nur, wenn HA dauerhaft mehrere Schläge abweicht.

Anker für Takt und Phrase:
- Drop: beginnt fast immer auf der „1“ einer Phrase → die Zählung wird so verschoben, dass er dort liegt.
- Phrasenwechsel aus der Klanganalyse: liegt er nahe an einer erwarteten Phrasengrenze (±3 Schläge),
  wird die Zählung nachgezogen.
Verschiebungen gelten auch für die HA-Grundlage (offset), sonst würde die Drift-Korrektur sie zurückdrehen.

Die „1“ im Takt (seit 0.8.13): HA ist nur auf 1–3 s genau, die Lage im Takt war damit Zufall. Die Analyse
liefert je Schlag, wie stark sich der Klang gegenüber dem vorigen Schlag ändert (Akkord, Bass-Ton, Instrumente
wechseln meist auf der „1“). Über mehrere Takte auf die vier Positionen im Takt summiert, wird die Position mit
dem klar größten Wechsel zur „1“. Danach verschieben Drop und Phrasenwechsel nur noch um ganze Takte. Eine
Korrektur von Hand hat Vorrang: Dann bleibt die „1“ für das Lied, wo sie gesetzt wurde.
"""
import numpy as np

PHRASE = 32          # Schläge pro Phrase (8 Takte)
BAR = 4
BAR_MIN_BEATS = 24   # so viele Schläge sammeln, bevor die „1“ zum ersten Mal festgelegt wird
BAR_MARGIN = 1.25    # die stärkste Position muss so viel stärker sein als die zweitstärkste
BAR_DECAY = 0.99     # ältere Schläge zählen langsam weniger (ca. 100 Schläge Gedächtnis)
DRIFT_LIMIT = 6.0    # so viele Schläge Abweichung von HA, bevor korrigiert wird …
DRIFT_TIME = 8.0     # … und so lange (s) muss sie bestehen
DROP_MAX_SHIFT = 12  # weiter verschiebt ein Drop die Zählung nicht
CHANGE_WINDOW = 3.0  # Phrasenwechsel zählt nur so nahe an einer erwarteten Grenze


class BeatCounter:
    def __init__(self):
        self.reset()

    def reset(self):
        self.count = None
        self.prev = None
        self.offset = 0.0
        self.diff = 0.0
        self.far_since = None
        self.last_b = None
        self.last_t = None
        self.first_t = None           # Zeit des ersten Bildes dieser Zählung (Liedbeginn)
        self.seen_drop = 0.0
        self.seen_change = 0.0
        self.events = []        # (Zeit, Text) für die Anzeige
        self.last_fix = None    # (Zeit, Richtung) des letzten HA-Abgleichs
        self.audio_off = False  # Audio-Zählung für dieses Lied abgeschaltet (läuft nicht mit der Musik)
        self.bar_bins = [0.0] * BAR   # Klangwechsel je Position im Takt (0 = „1“)
        self.bar_beats = 0            # so viele Schläge gesammelt
        self.bar_since = 0            # Schläge seit der letzten Verschiebung durch den Takt-Anker
        self.bar_locked = False       # „1“ aus dem Audio gefunden
        self.bar_manual = False       # „1“ von Hand gesetzt: kein automatischer Takt-Anker mehr
        self.bar_ratio = 0.0
        self.seen_bc = 0.0
        self.bar_model = False        # „1“ aus Beat This (hat Vorrang vor dem Klangwechsel)
        self.model_share = 0.0

    def shift(self, s, now, why="von Hand"):
        """Zählung um s Schläge verschieben (z. B. nach dem Break, wenn der Einsatz nicht stimmt)."""
        self.bar_manual = True
        self._shift(int(s), now, why)

    def bar_info(self):
        """Für die Anzeige: woher die „1“ kommt und wie deutlich sie ist."""
        source = ("von Hand" if self.bar_manual else "Beat This" if self.bar_model
                  else "Audio" if self.bar_locked else "geschätzt")
        return {"quelle": source, "deutlich": round(self.model_share if self.bar_model else self.bar_ratio, 2),
                "schlaege": self.bar_beats}

    def model_anchor(self, now, downs, bpm, beats=None):
        """„1“-Schläge aus Beat This (Uhrzeit der Analyse): Liegt die große Mehrheit auf derselben Position im
        Takt, wird sie zur „1“. Rückgabe: Verschiebung in Schlägen (meist 0).
        Mit `beats` (Schläge des Modells) wird vom letzten Modell-Schlag aus in Modell-Schlägen zurückgezählt:
        unabhängig davon, ob das Tempo aus der Datenbank genau stimmt (bei 1 % daneben sind 30 s schon fast ein
        Schlag). Nur „1“-Schläge aus diesem Lied (ab dem Start dieser Zählung) zählen."""
        if self.bar_manual or self.last_b is None or not downs:
            return 0
        beat = 60.0 / bpm
        downs = [t for t in downs if t >= (self.first_t or 0.0) + 1.0 and abs(now - t) < 45.0]
        if beats is not None and len(beats) >= 8:
            beats = np.asarray(sorted(beats))
            t_last = beats[-1]
            k_last = round(self.last_b - (self.last_t - t_last) / beat)
            res = []
            for t in downs:
                n = int(np.sum((beats > t + 0.5 * beat) & (beats <= t_last + 0.01)))
                res.append((k_last - n) % BAR)
        else:
            res = [round(self.last_b - (self.last_t - t) / beat) % BAR for t in downs]
        if len(res) < 3:
            return 0
        best = max(range(BAR), key=res.count)
        self.model_share = res.count(best) / len(res)
        if self.model_share < 0.7:
            return 0
        self.bar_locked = self.bar_model = True
        if best == 0:
            return 0
        s = (-best) % BAR
        s = s - BAR if s > BAR // 2 else s
        self._shift(s, now, "Takt-Anker (Beat This)")
        self.last_b += s
        return s

    def _shift(self, s, now, why):
        if self.count is not None:
            self.count += s
        self.offset += s
        self.bar_bins = [self.bar_bins[(i - s) % BAR] for i in range(BAR)]   # Statistik mitverschieben
        self.events.append((now, f"{why}: {s:+d} Schläge"))
        del self.events[:-5]

    def update(self, now, b_ha, frac=None, drop_at=0.0, change_at=0.0, bpm=120.0, changes=None):
        """Taktposition b. b_ha = Schätzung aus HA/Zeit; frac = Phase des aktuellen Schlags aus dem Audio
        (None, wenn kein Takt eingerastet ist); drop_at/change_at = Zeitpunkte der letzten Ereignisse;
        changes = neue Klangwechsel je Schlag [(Zeit, Stärke)] für die „1“ im Takt."""
        beat = 60.0 / bpm
        b_ref = b_ha + self.offset
        if self.audio_off:
            frac = None
        if frac is None:
            self.count = None
            self.prev = None
            b = b_ref
        else:
            # Vorhersage aus dem letzten Bild und der vergangenen Zeit, auf die gemessene Phase eingerastet.
            # Das zählt auch dann richtig, wenn Bilder ausfallen (früher: Zählen der Phasensprünge, das verlor
            # bei unter ~5 Bildern/s Schläge)
            recent = self.last_b is not None and self.last_t is not None and now - self.last_t < 2.0
            ref = self.last_b + (now - self.last_t) / beat if recent else b_ref
            self.count = round(ref - frac)
            self.prev = frac
            b = self.count + frac
            # Grobe Drift gegen HA: nur wenn sie groß ist und anhält
            self.diff += 0.02 * ((b_ref - b) - self.diff)
            if abs(self.diff) > DRIFT_LIMIT:
                self.far_since = self.far_since or now
                if now - self.far_since > DRIFT_TIME:
                    s = round(self.diff)
                    if self.last_fix and now - self.last_fix[0] < 60 and (s > 0) == self.last_fix[1]:
                        # zweimal kurz hintereinander in dieselbe Richtung: Die Audio-Zählung läuft nicht mit der
                        # Musik. Für dieses Lied nach der HA-Position zählen. (Bis 0.8.10 wurde stattdessen HA
                        # abgeschaltet; lief das Audio falsch, stand die Show dann fast still.)
                        self.audio_off = True
                        self.far_since = None
                        self.events.append((now, "Audio-Zählung aus (läuft nicht mit der Musik)"))
                        self.count = None
                        self.prev = None
                        b = b_ref
                    else:
                        if self.bar_locked or self.bar_manual:
                            s = BAR * round(self.diff / BAR) or s   # die „1“ nicht verschieben
                        self.count += s
                        b += s
                        self.diff -= s
                        self.bar_bins = [self.bar_bins[(i - s) % BAR] for i in range(BAR)]
                        self.far_since = None
                        self.last_fix = (now, s > 0)
                        self.events.append((now, f"HA-Abgleich: {s:+d} Schläge"))
            else:
                self.far_since = None
            if changes and not self.audio_off and not self.bar_model:
                b += self._bar_anchor(now, b, beat, changes)
        # Drop als Anker: auf die nächste Phrasengrenze legen (ist die „1“ bekannt, nur um ganze Takte)
        if drop_at and drop_at != self.seen_drop:
            self.seen_drop = drop_at
            b_drop = round(b - (now - drop_at) / beat)
            s = round(b_drop / PHRASE) * PHRASE - b_drop
            if self.bar_locked or self.bar_manual:
                s = BAR * round(s / BAR)
            if s and abs(s) <= DROP_MAX_SHIFT:
                self._shift(s, now, "Drop-Anker")
                b += s
        # Phrasenwechsel aus der Klanganalyse: kleine Korrektur zur nächsten Phrasengrenze
        if change_at and change_at != self.seen_change:
            self.seen_change = change_at
            b_c = b - (now - change_at) / beat
            err = round(b_c / PHRASE) * PHRASE - b_c
            if self.bar_locked or self.bar_manual:
                s = BAR * round(err / BAR)            # nur um ganze Takte, und nur wenn er gut auf einer „1“ liegt
                ok = abs(err - s) <= 1.0 and abs(err) <= BAR + 0.5
            else:
                s = round(err)
                ok = abs(err) <= CHANGE_WINDOW
            if s and ok:
                self._shift(s, now, "Phrasenwechsel")
                b += s
        self.last_b, self.last_t = b, now
        self.first_t = self.first_t or now
        return b

    def _bar_anchor(self, now, b, beat, changes):
        """Klangwechsel je Schlag auf die Positionen im Takt summieren; ist eine Position deutlich die stärkste,
        wird sie zur „1“. Rückgabe: Verschiebung in Schlägen (meist 0)."""
        for t_c, d in changes:
            if t_c <= self.seen_bc:
                continue
            self.seen_bc = t_c
            idx = round(b - (now - t_c) / beat)
            self.bar_bins = [x * BAR_DECAY for x in self.bar_bins]
            self.bar_bins[idx % BAR] += d
            self.bar_beats += 1
            self.bar_since += 1
        if self.bar_beats < BAR_MIN_BEATS or self.bar_since < 2 * BAR:
            return 0
        order = sorted(range(BAR), key=lambda i: -self.bar_bins[i])
        best, second = order[0], order[1]
        self.bar_ratio = self.bar_bins[best] / (self.bar_bins[second] + 1e-9)
        if self.bar_manual or self.bar_ratio < BAR_MARGIN:
            return 0
        self.bar_locked = True
        if best == 0:
            return 0
        s = (-best) % BAR
        s = s - BAR if s > BAR // 2 else s          # kürzester Weg: −1, +1 oder +2
        self._shift(s, now, "Takt-Anker")
        self.bar_since = 0
        return s
