"""Party-Modus: der Hauptschalter der Lichtregie.

An: Geräte einschalten (Steckdosen der Köpfe, Laser, weitere), Raum abdunkeln, Titel überwachen, Show.
Aus: Show stoppen, Köpfe dunkel, Geräte aus, Lampen zurück auf den Zustand von vorher.

Automatik: geht an, sobald Musik ankommt (Ton am AirPlay-Empfänger; ist die Audioanalyse aus: AirPlay meldet
ein laufendes Lied), und
aus, wenn so lange keine Musik lief, wie in „party_aus_min“ steht. Ein Stopp von Hand gilt, bis die Musik
einmal eine Minute aus war; sonst würde die Automatik sofort wieder einschalten.
"""
import threading
import time

import config
import jsonfile
import engine
import airplay
import ha
import heads
import lamps
from settings import SETTINGS

PARTY = {"on": False, "why": "", "since": 0.0, "last_music": 0.0, "manual_stop": False,
         "music_since": None, "quiet_since": None}
DEVICES = {"states": {}, "at": 0.0, "asked": 0.0}    # Zustand der Geräte für die Anzeige
LOCK = threading.Lock()
FILE = config.DATA / "party.json"   # Stand überdauert einen Neustart des Add-ons (z. B. ein Update)
START_AFTER = 3.0        # so lange muss Musik ankommen, bevor die Automatik einschaltet
REARM_AFTER = 60.0       # so lange Ruhe hebt einen Stopp von Hand wieder auf
PARK = (0, 0)            # Parkposition (Pan, Tilt) vor dem Abschalten: beide Köpfe hängen gleich (wie im alten
PARK_SEC = 3.5           # Skript „Moving Head off“), erst danach gehen die Steckdosen aus


def _save():
    jsonfile.save(FILE, {"on": PARTY["on"], "last_music": PARTY["last_music"]})


def resume():
    """Nach einem Neustart des Add-ons: Lief die Party, läuft sie weiter (Geräte bleiben an, Raum dunkel).
    Ohne Musik schaltet die Automatik sie nach der üblichen Zeit ab."""
    saved = jsonfile.load(FILE)
    if saved.get("on"):
        start("nach Neustart fortgesetzt", last_music=float(saved.get("last_music") or time.time()))


def start(why="von Hand", last_music=None):
    with LOCK:
        if PARTY["on"]:
            return
        now = time.time()
        PARTY.update(on=True, why=why, since=now, last_music=last_music or now, manual_stop=False)
        _save()
        print(f"Party an ({why})", flush=True)
        if config.GERAETE:
            ha.call("homeassistant", "turn_on", {"entity_id": config.GERAETE})
        lamps.set_room(True)
        for k in heads.HEADS:
            heads.apply(k, on=True, hell=0, strobe=0)
        engine.IDLE["on"] = True          # bis Musik kommt: Ruhe-Animation
        engine.start_watch("", "")     # nimmt den laufenden Titel und startet die Show
        DEVICES["at"] = 0.0


def _power_off():
    """Geräte ausschalten, wenn die Köpfe geparkt sind (außer die Party hat inzwischen wieder begonnen)."""
    if not PARTY["on"] and config.GERAETE:
        ha.call("homeassistant", "turn_off", {"entity_id": config.GERAETE})


def stop(why="von Hand", manual=True):
    with LOCK:
        if not PARTY["on"]:
            return
        PARTY.update(on=False, why=why, since=time.time(), manual_stop=manual)
        _save()
        print(f"Party aus ({why})", flush=True)
        engine.IDLE["on"] = False
        time.sleep(0.1)                   # Ruhe-Animation ein letztes Bild fertig rechnen lassen
        engine.stop_all()
        for k in heads.HEADS:      # dunkel und in die Parkposition fahren
            heads.apply(k, pan=PARK[0], tilt=PARK[1], on=False, strobe=0)
        lamps.set_room(False)
        threading.Timer(PARK_SEC, _power_off).start()
        DEVICES["at"] = 0.0


def _audio(now):
    return engine.audio_mode() and engine.AUDIO.signal(now)


def _playing(now):
    """AirPlay meldet ein laufendes Lied (Metadaten von Music Assistant)."""
    live = airplay.now_playing(now)
    if live and not PARTY["on"]:               # läuft die Party, liest die Titel-Überwachung schon mit
        engine.update_live(live)
    return bool(live and live.get("playing"))


def _music(now, tick):
    """Starten darf nur Ton am Empfänger (ist die Audioanalyse aus: AirPlay meldet ein Lied). Läuft die Party schon,
    hält sie auch ein laufendes Lied laut AirPlay am Leben (z. B. ein leiser Teil)."""
    if not engine.audio_mode():
        return _playing(now)
    if _audio(now):
        _playing(now)                          # Titel für die Anzeige trotzdem lesen
        return True
    return _playing(now) and PARTY["on"]


def loop():
    tick = 0
    resume()
    while True:
        time.sleep(1.0)
        tick += 1
        if PARTY["on"] and tick % 30 == 0:
            _save()
        now = time.time()
        if _music(now, tick):
            PARTY["music_since"] = PARTY["music_since"] or now
            PARTY["quiet_since"] = None
            PARTY["last_music"] = now
        else:
            PARTY["music_since"] = None
            PARTY["quiet_since"] = PARTY["quiet_since"] or now
        quiet = now - PARTY["quiet_since"] if PARTY["quiet_since"] else 0.0
        if PARTY["manual_stop"] and quiet > REARM_AFTER:
            PARTY["manual_stop"] = False
        if (not PARTY["on"] and SETTINGS["automatik"] and not PARTY["manual_stop"]
                and PARTY["music_since"] and now - PARTY["music_since"] >= START_AFTER):
            start("Musik erkannt")
        elif PARTY["on"] and now - PARTY["last_music"] > SETTINGS["party_aus_min"] * 60:
            stop(f"{SETTINGS['party_aus_min']} min keine Musik", manual=False)
        # Gerätezustand für die Anzeige, nur solange jemand die Oberfläche offen hat
        if config.GERAETE and now - DEVICES["asked"] < 30 and now - DEVICES["at"] > 8:
            DEVICES.update(states=ha.states(config.GERAETE), at=now)


def status():
    now = time.time()
    DEVICES["asked"] = now
    rest = None
    if PARTY["on"] and not PARTY["music_since"]:
        rest = max(0, int(SETTINGS["party_aus_min"] * 60 - (now - PARTY["last_music"])))
    return {"an": PARTY["on"], "grund": PARTY["why"], "automatik": SETTINGS["automatik"],
            "gesperrt": PARTY["manual_stop"], "musik": bool(PARTY["music_since"]), "aus_in": rest,
            "geraete": [{"id": e, "name": e.split(".", 1)[1].replace("_", " "), "zustand": DEVICES["states"].get(e)}
                        for e in config.GERAETE]}
