"""Lampen über HA. Sie folgen dem Song-Thema: Die Ambilights wechseln hart auf dem Schlag die Farbe (Rhythmus,
Dunkelzeit und Vorlauf in der Oberfläche), die Schränke spielen pro Takt im Wechsel. Gesendet wird nur, was sich
ändert; die Yeelights hängen lokal."""
import threading
import time
from collections import deque

import config
import ha
import jsonfile
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
QUOTA_GROUP = {"tv": 600}  # LED-Streifen (Govee über Bluetooth) haben keine Befehlsgrenze
GAP = {"tv": 0.4}          # … aber zu schnell hintereinander verschluckt der Streifen Befehle: mindestens so viele s
LAST_SENT = {}             # Gruppe → Zeit des letzten Befehls
SPENT = {}                 # Gruppe → deque[(Zeit, Befehle)]


def stats(now=None):
    """Messwerte der letzten 60 s für die Oberfläche: Befehle pro Minute, Dauer eines Befehls, Fehler."""
    now = time.time() if now is None else now
    recent = [c for c in list(CALLS) if now - c[0] < 60.0]
    if not recent:
        return None
    ms = sorted(c[1] * 1000 for c in recent)
    amb = [c for c in recent if c[3] == "grund"]
    tv = sorted(c[1] * 1000 for c in recent if c[3] == "tv")
    return {"befehle_min": len(recent), "ambilight_min": len(amb),
            "dauer_ms": round(ms[len(ms) // 2]), "max_ms": round(ms[-1]),
            "fehler": sum(1 for c in recent if not c[2]),
            "tv_min": len(tv), "tv_ms": round(tv[len(tv) // 2]) if tv else None}
ROOM = {"dark": False}     # vom Party-Modus gesetzt: Raum abgedunkelt, Lampen gehören der Show
SCENE_ID = "lichtregie_vorher"
ENTITIES = config.LAMPEN_GRUND + config.LAMPEN_AKZENT + config.LAMPEN_TV + config.LAMPEN_AUS
# Merker auf der Platte: Es gibt eine gesicherte Szene. Nach einem Neustart des Add-ons mitten in der Party
# darf der schon abgedunkelte Raum nicht als „vorher“ gesichert werden.
MARKER = config.DATA / "lampen_gesichert"
LAMP["snapshot"] = MARKER.exists()
# Zum Prüfen nach der Party: der Zustand beim Sichern und die zuletzt gesendete Show-Farbe je Lampe. Leuchtet
# eine Lampe beim nächsten Party-Start noch in der Show-Farbe, hat das Zurücksetzen nicht geklappt; dann bleibt die
# alte Szene, statt die Party-Farbe als „vorher“ zu sichern (gesehen: Schrank 1 blieb dauerhaft lila)
BEFORE_FILE = config.DATA / "lampen_vorher.json"
SHOW_FILE = config.DATA / "lampen_show.json"
SHOWN = {}                 # Lampe → zuletzt erfolgreich gesendete Farbe (None = aus)
CHECKS = (5.0, 20.0, 65.0, 120.0)   # nach der Party prüfen, ob alles zurück ist; die letzte Prüfung meldet nur
BUSY = set()               # Gruppen, deren Befehl gerade unterwegs ist
RETRY = {}                 # Gruppe → frühester neuer Versuch nach einem Fehler
PARALLEL = True            # jede Gruppe sendet in einem eigenen Thread (ein langsamer Befehl hält keine andere auf)


def _close(a, b, tol=20):
    return bool(a) and bool(b) and len(a) == len(b) == 3 and all(abs(x - y) <= tol for x, y in zip(a, b))


def stuck(cur, show):
    """Lampen, die noch in der zuletzt gesendeten Show-Farbe leuchten."""
    return sorted(e for e, s in cur.items() if s.get("state") == "on" and _close(s.get("rgb"), show.get(e)))


def restored(cur, before):
    """Ist der Zustand von vor der Party wieder da? Lampen, die HA gerade nicht meldet, zählen nicht dagegen."""
    for e, b in before.items():
        c = cur.get(e)
        if c is None or b.get("state") not in ("on", "off"):
            continue
        if c.get("state") != b["state"]:
            return False
        if b["state"] == "on":
            if b.get("rgb") and not _close(c.get("rgb"), b["rgb"]):
                return False
            if b.get("bri") is not None and c.get("bri") is not None and abs(c["bri"] - b["bri"]) > 8:
                return False
    return True


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
    gibt es kein Wechselspiel. Die LED-Streifen („tv“) senden zuerst: Sie tragen den Schlag."""
    acc = config.LAMPEN_AKZENT
    if len(acc) >= 2:
        return [("tv", config.LAMPEN_TV), ("grund", config.LAMPEN_GRUND), ("links", acc[:1]), ("rechts", acc[1:2]),
                ("akzent", acc[2:])]
    return [("tv", config.LAMPEN_TV), ("grund", config.LAMPEN_GRUND), ("akzent", acc)]


def follow(prof, b, live):
    """Von der Show-Schleife in jedem Bild aufgerufen."""
    LAMP.update(prof=prof, b=b, at=time.time(), live=live)


def set_room(dark):
    """Party an: Zustand sichern, Hauptlicht aus, Lampen folgen der Show. Party aus: alter Zustand zurück."""
    ROOM["dark"] = bool(dark)


def restore(transition=None):
    """Zustand von vor der Show zurückholen (wenn einer gesichert ist). Die Show-Farben kommen auf die Platte, damit
    der nächste Party-Start erkennt, ob das Zurücksetzen geklappt hat."""
    if not LAMP["snapshot"]:
        return False
    if SHOWN:
        jsonfile.save(SHOW_FILE, {e: rgb for e, rgb in SHOWN.items() if rgb})
    data = {"entity_id": f"scene.{SCENE_ID}"}
    if transition:
        data["transition"] = transition
    ha.call("scene", "turn_on", data)
    _mark(False)
    return True


def snapshot():
    """Party-Start: Zustand der Lampen als HA-Szene sichern. Leuchten Lampen noch in den Farben der letzten Show,
    bleibt die alte Szene. True, wenn eine Szene da ist."""
    cur = ha.lights(ENTITIES)
    left = stuck(cur, jsonfile.load(SHOW_FILE))
    if left and ha.states([f"scene.{SCENE_ID}"]):
        print(f"Lampen noch in den Farben der letzten Show ({', '.join(left)}): Szene „vorher“ bleibt", flush=True)
        return True
    if not ha.call("scene", "create", {"scene_id": SCENE_ID, "snapshot_entities": ENTITIES}):
        return False
    jsonfile.save(BEFORE_FILE, cur)
    SHOW_FILE.unlink(missing_ok=True)
    return True


def check_restored(last):
    """Nach der Party: Ist alles zurück? Sonst die Szene noch einmal (außer bei der letzten Prüfung)."""
    before = jsonfile.load(BEFORE_FILE)
    if not before or restored(ha.lights(ENTITIES), before):
        if before:
            print("Lampen wieder wie vor der Party", flush=True)
        SHOW_FILE.unlink(missing_ok=True)
        return True
    if last:
        print("Lampen nach der Party nicht ganz zurück; die Szene „vorher“ bleibt für die nächste Party", flush=True)
    else:
        ha.call("scene", "turn_on", {"entity_id": f"scene.{SCENE_ID}"})
    return False


def lamp_loop():
    """Alle 20 ms. Solange der Raum abgedunkelt ist (Party-Modus): Zustand der Lampen einmal als HA-Szene
    sichern, „Während der Party aus“ ausschalten und die Lampen nach dem Song-Thema setzen, nur bei Änderung.
    Zwischen zwei Liedern bleiben sie, wie sie sind. Danach kommt der alte Zustand zurück; nach 5, 20 und 65 s
    wird geprüft, ob er wirklich da ist (Yeelights verschlucken gelegentlich einen Befehl), sonst noch einmal."""
    while True:
        time.sleep(TICK)
        if not ENTITIES:
            continue
        if not (ROOM["dark"] and SETTINGS["lampen"]):
            if restore(transition=2):
                now = time.time()
                LAMP["again"] = [now + d for d in CHECKS]
            elif LAMP["again"] and time.time() > LAMP["again"][0]:
                LAMP["again"] = LAMP["again"][1:] or None
                if check_restored(last=not LAMP["again"]):
                    LAMP["again"] = None
            continue
        LAMP["again"] = None
        if not LAMP["snapshot"]:
            if not snapshot():
                time.sleep(2.0)                # HA nicht erreichbar: nicht im 20-ms-Takt nachfragen
                continue
            _mark(True)
            if config.LAMPEN_AUS:
                ha.call("homeassistant", "turn_off", {"entity_id": config.LAMPEN_AUS})
            LAMP["last"] = {}
            SHOWN.clear()
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
    # LED-Streifen: eigener Vorlauf (Bluetooth reagiert schneller als die Yeelights), Wechsel bis auf den Schlag
    b_tv = LAMP["b"] + (time.time() - LAMP["at"] + SETTINGS["tv_vorlauf"]) * bps
    rgb, pct, flash = show.tv(LAMP["prof"], b_tv, live, SETTINGS["tv_blinder"], SETTINGS["tv_flash"],
                              SETTINGS["tv_flash_lang"], SETTINGS["tv_blinder_lang"])
    if SETTINGS["lampentest"]:
        rgb, pct, flash = show.WHITE, 100, b_tv % 1.0 < show.TV_FLASH   # Blitz auf jedem Schlag, sonst gedimmt weiß
    # Farbe in der eingestellten (geringen) Helligkeit, weiße Blitze immer voll
    want["tv"] = (rgb, pct if flash else (0 if pct == 0 or SETTINGS["tv_hell"] == 0 else
                                          max(1, round(pct * SETTINGS["tv_hell"] / 100))))
    # Helligkeit je Gruppe aus der Oberfläche (Decke = Grundfarbe, Vitrinen = Akzent), in Prozent
    for group, setting in (("grund", "lampen_decke"), ("akzent", "lampen_vitrine"),
                           ("links", "lampen_vitrine"), ("rechts", "lampen_vitrine")):
        rgb, pct = want[group]
        want[group] = (rgb, 0 if pct == 0 else max(1, min(100, round(pct * SETTINGS[setting] / 100))))
    return want


def send(want):
    """Nur die Gruppen senden, die sich geändert haben, und davon nur die geänderten Werte: Ein Farbwechsel ist ein
    Befehl, das Wechselspiel der Schränke auch. Jede Gruppe sendet für sich (ein langsamer Befehl hält die anderen
    nicht vom Schlag ab). Schlägt ein Befehl fehl, versucht es die Gruppe nach 1 s noch einmal."""
    trans = 0 if SETTINGS["lampen_hart"] else 0.4
    now = time.time()
    for group, ents in groups():
        if not ents or group in BUSY or now < RETRY.get(group, 0.0) or LAMP["last"].get(group) == want[group]:
            continue
        if now - LAST_SENT.get(group, 0.0) < GAP.get(group, 0.0):
            continue                            # noch zu kurz nach dem letzten Befehl: im nächsten Durchlauf
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
        if sum(c for _, c in spent) + cost > QUOTA_GROUP.get(group, QUOTA):
            continue                            # Budget der Lampe aufgebraucht: diesen Wechsel auslassen
        spent.append((now, cost))
        LAST_SENT[group] = now
        BUSY.add(group)
        args = (group, ents, service, data, want[group])
        if PARALLEL:
            threading.Thread(target=_call, args=args, daemon=True).start()
        else:
            _call(*args)


def _call(group, ents, service, data, value):
    t0 = time.time()
    ok = False
    try:
        ok = ha.call("light", service, data)
    finally:
        CALLS.append((t0, time.time() - t0, bool(ok), group))
        if ok:
            LAMP["last"][group] = value
            for e in ents:
                SHOWN[e] = list(value[0]) if value[1] else None
        else:
            RETRY[group] = time.time() + 1.0   # nicht im 20-ms-Takt nachschießen; das Budget zählt ohnehin mit
        BUSY.discard(group)                    # erst jetzt: sonst schickt der nächste Durchlauf denselben Wechsel
