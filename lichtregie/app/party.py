"""Party-Modus: der Hauptschalter der Lichtregie.

An: Geräte einschalten (Steckdosen der Köpfe, Laser, weitere), Raum abdunkeln, Titel überwachen, Show.
Aus: Show stoppen, Köpfe dunkel, Geräte aus, Lampen zurück auf den Zustand von vorher.

Automatik: geht an, sobald Musik ankommt (Ton am AirPlay-Empfänger, ohne Empfänger: Spotify spielt), und
aus, wenn so lange keine Musik lief, wie in „party_aus_min“ steht. Ein Stopp von Hand gilt, bis die Musik
einmal eine Minute aus war; sonst würde die Automatik sofort wieder einschalten.
"""
import json
import threading
import time

import config
import engine
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


def _save():
    try:
        FILE.write_text(json.dumps({"on": PARTY["on"], "last_music": PARTY["last_music"]}), encoding="utf-8")
    except OSError:
        pass


def resume():
    """Nach einem Neustart des Add-ons: Lief die Party, läuft sie weiter (Geräte bleiben an, Raum dunkel).
    Ohne Musik schaltet die Automatik sie nach der üblichen Zeit ab."""
    try:
        saved = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
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
        engine.start_watch("", "")     # nimmt den laufenden Titel und startet die Show
        DEVICES["at"] = 0.0


def stop(why="von Hand", manual=True):
    with LOCK:
        if not PARTY["on"]:
            return
        PARTY.update(on=False, why=why, since=time.time(), manual_stop=manual)
        _save()
        print(f"Party aus ({why})", flush=True)
        engine.stop_all()
        for k in heads.HEADS:
            heads.apply(k, on=False, strobe=0)
        lamps.set_room(False)
        if config.GERAETE:
            ha.call("homeassistant", "turn_off", {"entity_id": config.GERAETE})
        DEVICES["at"] = 0.0


def _music(now, tick):
    """Kommt gerade Musik an?"""
    if engine.AUDIO is not None and SETTINGS["audio"]:
        return engine.AUDIO.signal(now)
    if not PARTY["on"] and tick % 5 == 0:      # ohne Empfänger: Spotify in HA fragen (läuft die Party,
        live = ha.now_playing()                # macht das schon die Titel-Überwachung)
        if live:
            engine.update_live(live)
    live = engine.LIVE.get("live")
    return bool(live and live.get("playing") and now - engine.LIVE["at"] < 15)


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
