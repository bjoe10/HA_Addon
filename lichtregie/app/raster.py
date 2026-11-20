"""Gespeichertes Taktraster je Lied: Beim nächsten Abspielen sitzen „1“ und Phrase ab Sekunde 0.

Beat This braucht 16 s Ton und rechnet am Pi gut 7 s; die „1“ steht deshalb frühestens nach einer halben Minute
fest, und Drops und Phrasenwechsel ziehen die Phrase erst im Lauf des Liedes zurecht. Was dabei herauskommt, ist
eine feste Beziehung zwischen der Liedposition (AirPlay, auf Millisekunden genau) und der Schlagzählung:
    Schlag = Position · Tempo / 60 + Verschiebung
Tempo und Verschiebung werden gemerkt, sobald die „1“ bestätigt ist (Beat This oder von Hand) und der Takt aus dem
Ton eingerastet ist; spätere Stände überschreiben frühere (später im Lied ist mehr bekannt). Beim nächsten Mal
startet die Zählung damit. Beat This, Drops und Korrekturen von Hand wirken weiter wie bisher.
"""
import config
import jsonfile

FILE = config.DATA / "raster.json"
SAME_TEMPO = 0.002        # gespeichertes Raster gilt nur beim (fast) selben Tempo


def get(key, bpm):
    """Gespeichertes Raster für dieses Lied und Tempo: {"bpm", "shift", "hand"} oder None."""
    r = jsonfile.load(FILE).get(key)
    if not r or not bpm or abs(r["bpm"] / bpm - 1.0) > SAME_TEMPO:
        return None
    return r


def save(key, bpm, shift, hand=False):
    data = jsonfile.load(FILE)
    old = data.get(key)
    new = {"bpm": round(float(bpm), 3), "shift": round(float(shift), 3), "hand": bool(hand)}
    if old != new:
        data[key] = new
        jsonfile.save(FILE, data)
