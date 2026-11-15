"""Schlagzählung für die Show: welcher Schlag im Takt und in der Phrase gerade dran ist.

Ohne Audio kommt die Zählung aus der Spotify-Position (HA, auf 1–3 s genau). Mit eingerastetem Audio-Takt
zählt die Lichtregie die Schläge selbst weiter (Phase aus der Analyse), damit Sprünge der HA-Position nicht
durchschlagen. Grob korrigiert wird nur, wenn HA dauerhaft mehrere Schläge abweicht.

Anker für Takt und Phrase:
- Drop: beginnt fast immer auf der „1“ einer Phrase → die Zählung wird so verschoben, dass er dort liegt.
- Phrasenwechsel aus der Klanganalyse: liegt er nahe an einer erwarteten Phrasengrenze (±3 Schläge),
  wird die Zählung nachgezogen.
Verschiebungen gelten auch für die HA-Grundlage (offset), sonst würde die Drift-Korrektur sie zurückdrehen.
"""
PHRASE = 32          # Schläge pro Phrase (8 Takte)
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
        self.seen_drop = 0.0
        self.seen_change = 0.0
        self.events = []        # (Zeit, Text) für die Anzeige

    def shift(self, s, now, why="von Hand"):
        """Zählung um s Schläge verschieben (z. B. nach dem Break, wenn der Einsatz nicht stimmt)."""
        self._shift(int(s), now, why)

    def _shift(self, s, now, why):
        if self.count is not None:
            self.count += s
        self.offset += s
        self.events.append((now, f"{why}: {s:+d} Schläge"))
        del self.events[:-5]

    def update(self, now, b_ha, frac=None, drop_at=0.0, change_at=0.0, bpm=120.0):
        """Taktposition b. b_ha = Schätzung aus HA/Zeit; frac = Phase des aktuellen Schlags aus dem Audio
        (None, wenn kein Takt eingerastet ist); drop_at/change_at = Zeitpunkte der letzten Ereignisse."""
        beat = 60.0 / bpm
        b_ref = b_ha + self.offset
        if frac is None:
            self.count = None
            self.prev = None
            b = b_ref
        else:
            if self.count is None:
                recent = self.last_b is not None and self.last_t is not None and now - self.last_t < 2.0
                ref = self.last_b + (now - self.last_t) / beat if recent else b_ref
                self.count = round(ref - frac)
            elif self.prev is not None:
                if self.prev > 0.7 and frac < 0.3:
                    self.count += 1
                elif self.prev < 0.3 and frac > 0.7:
                    self.count -= 1
            self.prev = frac
            b = self.count + frac
            # Grobe Drift gegen HA: nur wenn sie groß ist und anhält
            self.diff += 0.02 * ((b_ref - b) - self.diff)
            if abs(self.diff) > DRIFT_LIMIT:
                self.far_since = self.far_since or now
                if now - self.far_since > DRIFT_TIME:
                    s = round(self.diff)
                    self.count += s
                    b += s
                    self.diff -= s
                    self.far_since = None
                    self.events.append((now, f"HA-Abgleich: {s:+d} Schläge"))
            else:
                self.far_since = None
        # Drop als Anker: auf die nächste Phrasengrenze legen
        if drop_at and drop_at != self.seen_drop:
            self.seen_drop = drop_at
            b_drop = round(b - (now - drop_at) / beat)
            s = round(b_drop / PHRASE) * PHRASE - b_drop
            if s and abs(s) <= DROP_MAX_SHIFT:
                self._shift(s, now, "Drop-Anker")
                b += s
        # Phrasenwechsel aus der Klanganalyse: kleine Korrektur zur nächsten Phrasengrenze
        if change_at and change_at != self.seen_change:
            self.seen_change = change_at
            b_c = b - (now - change_at) / beat
            err = round(b_c / PHRASE) * PHRASE - b_c
            s = round(err)
            if s and abs(err) <= CHANGE_WINDOW:
                self._shift(s, now, "Phrasenwechsel")
                b += s
        self.last_b, self.last_t = b, now
        return b
