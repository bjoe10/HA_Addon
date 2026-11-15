"""Lampen über HA. Sie folgen dem Song-Thema: Die Ambilights wechseln hart auf dem Schlag die Farbe (Rhythmus,
Dunkelzeit und Vorlauf in der Oberfläche), die Schränke spielen pro Takt im Wechsel. Gesendet wird nur, was sich
ändert; die Yeelights hängen lokal."""
import time
from collections import deque

import config
import ha
import show
from settings import SETTINGS

# Die Show-Schleife schreibt hier Thema, Taktposition und Live-Audio hinein; lamp_loop liest mit
LAMP = {"prof": None, "b": 0.0, "at": 0.0, "live": None, "last": {}, "snapshot": False, "again": None}
TICK = 0.02                # so oft rechnet lamp_loop nach: Wechsel liegen auf ±20 ms am geplanten Zeitpunkt
LIVE_AT = {"fn": None}     # von der Show gesetzt: Zustand des Tons zu einer Zeit der Analyse (Drop, Break, Pegel)
TEST_COLORS = (17, 36)     # Lampen-Test: rot und blau im Wechsel, im eingestellten Rhythmus
CALLS = deque(maxlen=2000)  # (Zeit, Dauer s, ok, Gruppe) je Befehl an HA: wie schnell geht es wirklich?
# Yeelights nehmen nur ca. 60 Befehle pro Minute je Lampe an („client quota exceeded“). HA schickt Farbe und
# Helligkeit als getrennte Befehle; gezählt wird deshalb je geändertem Wert. Ist das Budget einer Gruppe
# aufgebraucht, wird der Wechsel ausgelassen statt von der Lampe abgelehnt.
QUOTA = 50
SPENT = {}                 # Gruppe → deque[(Zeit, Befehle)]


def stats(now=None):
    """Messwerte der letzten 60 s für die Oberfläche: Befehle pro Minute, Dauer eines Befehls, Fehler."""
    now = time.time() if now is None else now
    recent = [c for c in list(CALLS) if now - c[0] < 60.0]
    if not recent:
        return None
    ms = sorted(c[1] * 1000 for c in recent)
    amb = [c for c in recent if c[3] == "grund"]
    return {"befehle_min": len(recent), "ambilight_min": len(amb),
            "dauer_ms": round(ms[len(ms) // 2]), "max_ms": round(ms[-1]),
            "fehler": sum(1 for c in recent if not c[2])}
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
        time.sleep(TICK)
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
                time.sleep(2.0)                # HA nicht erreichbar: nicht im 20-ms-Takt nachfragen
                continue
            _mark(True)
            if config.LAMPEN_AUS:
                ha.call("homeassistant", "turn_off", {"entity_id": config.LAMPEN_AUS})
            LAMP["last"] = {}
        if LAMP["prof"] is None or time.time() - LAMP["at"] > 3.0:   # gerade keine Show: nichts ändern
            continue
        send(want_now())


def want_now():
    """Soll-Zustand je Gruppe jetzt: {gruppe: (rgb, prozent)}, 0 % = aus. Vorlauf: Die Yeelights reagieren mit
    Verzögerung, deshalb wird die Lage um den Vorlauf vorausgerechnet; so kommt der Wechsel auf dem Schlag an."""
    bps = LAMP["prof"]["bpm"] / 60.0
    b_lamp = LAMP["b"] + (time.time() - LAMP["at"] + SETTINGS["lampen_vorlauf"]) * bps
    live = LAMP["live"]
    if live is not None and LIVE_AT["fn"] is not None:
        # Die Analyse hat den Ton um den Ton-Vorlauf früher als der Lautsprecher: Drop und Break sind also schon
        # bekannt, bevor man sie hört. Die Lampen nehmen den Zustand um ihren Vorlauf voraus (höchstens bis jetzt)
        ahead = min(SETTINGS["lampen_vorlauf"], SETTINGS["ton_vorlauf"])
        live = LIVE_AT["fn"](time.time() - SETTINGS["ton_vorlauf"] + ahead, LAMP["prof"]["bpm"]) or live
    want = show.lamps(LAMP["prof"], b_lamp, live, SETTINGS["lampen_wechsel"])
    if SETTINGS["lampentest"]:
        per = show.lamp_period(LAMP["prof"], SETTINGS["lampen_wechsel"] or show.LAMP_MIN_BEATS)
        want["grund"] = (show.RGB[TEST_COLORS[int(b_lamp // per) % 2]], 100)
    # Helligkeit je Gruppe aus der Oberfläche (Decke = Grundfarbe, Vitrinen = Akzent), in Prozent
    for group, setting in (("grund", "lampen_decke"), ("akzent", "lampen_vitrine"),
                           ("links", "lampen_vitrine"), ("rechts", "lampen_vitrine")):
        rgb, pct = want[group]
        want[group] = (rgb, 0 if pct == 0 else max(1, min(100, round(pct * SETTINGS[setting] / 100))))
    return want


def send(want):
    """Nur die Gruppen senden, die sich geändert haben, Ambilights zuerst (sie tragen den Wechsel), und davon nur
    die geänderten Werte: Ein Farbwechsel ist ein Befehl, das Wechselspiel der Schränke auch."""
    trans = 0 if SETTINGS["lampen_hart"] else 0.4
    now = time.time()
    for group, ents in groups():
        if not ents or LAMP["last"].get(group) == want[group]:
            continue
        rgb, pct = want[group]
        prev = LAMP["last"].get(group)
        data = {"entity_id": ents, "transition": trans}
        if pct == 0:
            service, cost = "turn_off", 1
        else:
            service, cost = "turn_on", 1        # HA schickt vor Farbe/Helligkeit ein Einschalten (zählt bei Yeelight mit)
            if prev is None or prev[1] == 0 or prev[0] != rgb:
                data["rgb_color"] = list(rgb)
                cost += 1
            if prev is None or prev[1] == 0 or prev[1] != pct:
                data["brightness_pct"] = pct
                cost += 1
        spent = SPENT.setdefault(group, deque())
        while spent and now - spent[0][0] > 60.0:
            spent.popleft()
        if sum(c for _, c in spent) + cost > QUOTA:
            continue                            # Budget der Lampe aufgebraucht: diesen Wechsel auslassen
        spent.append((now, cost))
        LAMP["last"][group] = want[group]
        t0 = time.time()
        ok = ha.call("light", service, data)
        CALLS.append((t0, time.time() - t0, bool(ok), group))
