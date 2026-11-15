"""Lampen über HA: die langsame Ebene der Show. Sie folgt dem Song-Thema und wechselt nur selten
(alle 8 oder 16 Takte und an Höhepunkten), damit das Befehlslimit der Yeelights nicht erreicht wird."""
import time

import config
import ha
import show
from settings import SETTINGS

# Die Show-Schleife schreibt hier Thema, Taktposition und Live-Audio hinein; lamp_loop liest mit
LAMP = {"prof": None, "b": 0.0, "at": 0.0, "live": None, "last": None, "snapshot": False, "again": None}
ROOM = {"dark": False}     # vom Party-Modus gesetzt: Raum abgedunkelt, Lampen gehören der Show
SCENE_ID = "lichtregie_vorher"
ENTITIES = config.LAMPEN_GRUND + config.LAMPEN_AKZENT + config.LAMPEN_AUS
# Merker auf der Platte: Es gibt eine gesicherte Szene. Nach einem Neustart des Add-ons mitten in der Party
# darf der schon abgedunkelte Raum nicht als „vorher“ gesichert werden.
MARKER = config.DATA / "lampen_gesichert"
LAMP["snapshot"] = MARKER.exists()


def _mark(saved):
    LAMP["snapshot"] = saved
    try:
        if saved:
            MARKER.write_text("1", encoding="utf-8")
        else:
            MARKER.unlink(missing_ok=True)
    except OSError:
        pass


def groups():
    """Lampengruppen. Die erste Akzent-Lampe steht links vom TV, die zweite rechts (Schrank 1 und 2); sie
    spielen unabhängig voneinander. Weitere Akzent-Lampen folgen der Akzentfarbe. Mit nur einer Akzent-Lampe
    gibt es kein Wechselspiel."""
    acc = config.LAMPEN_AKZENT
    if len(acc) >= 2:
        return [("grund", config.LAMPEN_GRUND), ("links", acc[:1]), ("rechts", acc[1:2]), ("akzent", acc[2:])]
    return [("grund", config.LAMPEN_GRUND), ("akzent", acc)]


def follow(prof, b, live):
    """Von der Show-Schleife in jedem Bild aufgerufen."""
    LAMP.update(prof=prof, b=b, at=time.time(), live=live)


def set_room(dark):
    """Party an: Zustand sichern, Hauptlicht aus, Lampen folgen der Show. Party aus: alter Zustand zurück."""
    ROOM["dark"] = bool(dark)


def restore():
    """Zustand von vor der Show zurückholen (wenn einer gesichert ist)."""
    if LAMP["snapshot"]:
        ha.call("scene", "turn_on", {"entity_id": f"scene.{SCENE_ID}"})
        _mark(False)


def lamp_loop():
    """Alle 0,25 s. Solange der Raum abgedunkelt ist (Party-Modus): Zustand der Lampen einmal als HA-Szene
    sichern, „Während der Party aus“ ausschalten und die Lampen nach dem Song-Thema setzen, nur bei Änderung.
    Zwischen zwei Liedern bleiben sie, wie sie sind. Danach kommt der alte Zustand zurück (zweimal, weil
    Yeelights gelegentlich einen Befehl verschlucken)."""
    while True:
        time.sleep(0.25)
        if not ENTITIES:
            continue
        if not (ROOM["dark"] and SETTINGS["lampen"]):
            if LAMP["snapshot"]:
                ha.call("scene", "turn_on", {"entity_id": f"scene.{SCENE_ID}", "transition": 2})
                _mark(False)
                LAMP["again"] = time.time() + 5.0
            elif LAMP["again"] and time.time() > LAMP["again"]:
                ha.call("scene", "turn_on", {"entity_id": f"scene.{SCENE_ID}"})
                LAMP["again"] = None
            continue
        LAMP["again"] = None
        if not LAMP["snapshot"]:
            if not ha.call("scene", "create", {"scene_id": SCENE_ID, "snapshot_entities": ENTITIES}):
                continue
            _mark(True)
            if config.LAMPEN_AUS:
                ha.call("homeassistant", "turn_off", {"entity_id": config.LAMPEN_AUS})
            LAMP["last"] = None
        if LAMP["prof"] is None or time.time() - LAMP["at"] > 3.0:   # gerade keine Show: nichts ändern
            continue
        # Vorlauf: Yeelights reagieren mit Verzögerung, deshalb die Lage etwas vorausrechnen
        bps = LAMP["prof"]["bpm"] / 60.0
        b_lamp = LAMP["b"] + (time.time() - LAMP["at"] + SETTINGS["lampen_vorlauf"]) * bps
        want = show.lamps(LAMP["prof"], b_lamp, LAMP["live"])
        # Helligkeit je Gruppe aus der Oberfläche (Decke = Grundfarbe, Vitrinen = Akzent), in Prozent
        for group, setting in (("grund", "lampen_decke"), ("akzent", "lampen_vitrine"),
                               ("links", "lampen_vitrine"), ("rechts", "lampen_vitrine")):
            rgb, pct = want[group]
            want[group] = (rgb, max(1, min(100, round(pct * SETTINGS[setting] / 100))))
        key = tuple(want[g] for g in ("grund", "akzent", "links", "rechts"))
        if key == LAMP["last"]:
            continue
        LAMP["last"] = key
        for group, ents in groups():
            if ents:
                rgb, pct = want[group]
                ha.call("light", "turn_on", {"entity_id": ents, "rgb_color": list(rgb),
                                             "brightness_pct": pct, "transition": 0.4})
