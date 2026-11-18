#!/usr/bin/env python3
"""Show-Motor für die Moving Heads (nur Standardbibliothek, reine Funktionen).

Eingabe: Taktposition b (Schläge seit Liedanfang, als Kommazahl) und ein Song-Profil.
Ausgabe je Kopf: Zielpunkt im Raum (x, y, z in Metern, Raumkoordinaten wie in der Web-App),
Helligkeit, Farbe, Gobo und Strobe als DMX-Werte.

Konzept (siehe SHOW.md):
- Szenen werden aus Bausteinen zusammengesetzt: Form × Fläche × Lage/Größe × Kopf-Verhältnis × Dimmer-Muster
  × Farbverhalten × Gobo. Daraus entsteht viel Abwechslung, ohne dass jede Szene von Hand gebaut ist.
- Jedes Lied bekommt aus seiner Track-ID ein festes Thema: Grund-/Akzentfarbe (Tonart), zwei Gobos,
  Motiv-Punkt, 5 Szenen in fester Folge, eine Refrain-Szene. Gleiches Lied = gleiche Show.
- Ablauf: Intro, Phrasen zu 8 Takten (Motiv am Anfang, Variation in der zweiten Hälfte), alle 4 Phrasen
  Aufbau → Höhepunkt → Atempause, Outro. Radwechsel im Dunkeln vor einer neuen Phrase.
- Mechanik (gemessen): ein Sprung dauert 0,5–0,7 s; Bahnen werden bei schnellen Liedern verlangsamt.

Aufruf zum Testen ohne Köpfe:  python3 show.py
"""
import hashlib
import math
import random

# --- Gerätewerte (gemessen, siehe SHOW.md) ---------------------------------------------------------
WHEEL = [0, 17, 22, 36, 44, 54, 64, 73]  # Farbrad in Radreihenfolge
WHEEL_NAMES = ["weiß", "rot", "grün", "blau", "gelb", "orange", "eisblau", "lila"]
SPLIT = {frozenset((64, 73)): 85, frozenset((64, 54)): 93, frozenset((54, 44)): 101,
         frozenset((44, 36)): 113, frozenset((22, 36)): 121, frozenset((22, 17)): 132}  # Halbfarben
MAJOR = [1, 5, 4, 2]   # Dur: rot, orange, gelb, grün (warm)
MINOR = [3, 6, 7, 2]   # Moll: blau, eisblau, lila, grün (kühl)
GOBO_ZITTERN = {13: (73, 74, 76), 21: (80, 82, 85), 27: (89, 90, 93), 34: (97, 99, 100),
                43: (105, 108, 111), 50: (113, 115, 117), 57: (121, 123, 126)}
GOBO_NAMES = {0: "offen", 13: "Atom", 21: "Punkte-Ring", 27: "Punkte-Blume", 34: "grobe Löcher",
              43: "Blasen", 50: "Swirl", 57: "Striche"}
STROBE = 200   # fester Wert, entschieden
MIN_DIM = 10   # darunter ist der Kopf aus

BAR = 4        # Schläge pro Takt
PHRASE = 32    # 8 Takte
PITCH = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
         "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}

# --- Flächen: lokale Koordinaten (u, v) → Raumpunkt ------------------------------------------------
SURF = {
    "wand": {"u": (0.2, 4.8), "v": (0.3, 2.4)},    # TV-Wand: u = x, v = Höhe
    "boden": {"u": (0.3, 4.7), "v": (0.3, 3.0)},   # vorderer Boden: u = x, v = Abstand zur TV-Wand
    "decke": {"u": (0.5, 4.5), "v": (1.0, 4.5)},   # Decke: u = x, v = Abstand zur TV-Wand
}


def to_surface(surface, u, v):
    lo, hi = SURF[surface]["u"]
    u = min(hi, max(lo, u))
    lo, hi = SURF[surface]["v"]
    v = min(hi, max(lo, v))
    if surface == "wand":
        return (u, 0.0, v)
    if surface == "boden":
        return (u, v, 0.0)
    return (u, v, 2.5)


# --- Formen in lokalen Koordinaten -----------------------------------------------------------------
def _t(b, per, q):
    return 2 * math.pi * b / per + q.get("ph", 0.0)


def _tri(x):   # Dreieckwelle -1..1
    return 4.0 * abs((x % 1.0) - 0.5) - 1.0


def f_kreis(b, per, q):
    t = _t(b, per, q)
    return q["cu"] + q["su"] * math.cos(t), q["cv"] + q["sv"] * math.sin(t)


def f_acht(b, per, q):
    t = _t(b, per, q)
    return q["cu"] + q["su"] * math.sin(t), q["cv"] + q["sv"] * math.sin(2 * t)


def f_pendel_h(b, per, q):
    return q["cu"] + q["su"] * math.sin(_t(b, per, q)), q["cv"]


def f_pendel_v(b, per, q):
    return q["cu"], q["cv"] + q["sv"] * math.sin(_t(b, per, q))


def f_diagonale(b, per, q):
    s = math.sin(_t(b, per, q))
    return q["cu"] + q["su"] * s, q["cv"] + q["dir"] * q["sv"] * s


def f_spirale(b, per, q):
    t = _t(b, per, q)
    r = 0.25 + 0.75 * abs(math.sin(math.pi * b / (4 * per)))
    return q["cu"] + q["su"] * r * math.cos(t), q["cv"] + q["sv"] * r * math.sin(t)


def f_welle(b, per, q):
    return q["cu"] + q["su"] * _tri(b / per), q["cv"] + q["sv"] * math.sin(4 * math.pi * b / per)


def f_zickzack(b, per, q):
    return q["cu"] + q["su"] * _tri(b / per), q["cv"] + q["sv"] * _tri(3 * b / per)


def f_zufall(b, per, q):   # gleichmäßiger „Zufallsflug“ aus überlagerten Schwingungen
    t = _t(b, per, q)
    p = q["phs"]
    u = 0.6 * math.sin(t + p[0]) + 0.4 * math.sin(2.3 * t + p[1])
    v = 0.6 * math.sin(1.3 * t + p[2]) + 0.4 * math.sin(2.9 * t + p[3])
    return q["cu"] + q["su"] * u, q["cv"] + q["sv"] * v


# Sprung-Formen: per = Schläge pro Sprung
def f_stern(b, per, q):
    k = int(b // per)
    th = k * 4 * math.pi / 5 + q.get("ph", 0.0)
    return q["cu"] + q["su"] * math.sin(th), q["cv"] + q["sv"] * math.cos(th)


def f_quadrat(b, per, q):
    cx, cy = [(-1, -1), (1, -1), (1, 1), (-1, 1)][int(b // per) % 4]
    return q["cu"] + q["su"] * cx, q["cv"] + q["sv"] * cy


def f_springen(b, per, q):
    return q["pts"][int(b // per) % len(q["pts"])]


SHAPES = {"kreis": f_kreis, "acht": f_acht, "pendel_h": f_pendel_h, "pendel_v": f_pendel_v,
          "diagonale": f_diagonale, "spirale": f_spirale, "welle": f_welle, "zickzack": f_zickzack,
          "zufall": f_zufall, "stern": f_stern, "quadrat": f_quadrat, "springen": f_springen}
JUMPS = {"stern": 5, "quadrat": 4, "springen": None}  # Sprungformen und Anzahl Punkte


# Flächenübergreifende Bahnen (ohne Lage-Parameter)
ANCHORS = [(2.5, 0.0, 1.9), (1.0, 0.0, 1.6), (4.0, 0.0, 1.6), (2.5, 3.0, 2.5), (2.2, 3.5, 0.75),
           (2.5, 1.2, 0.0)]


def x_wand_boden(b, per):    # von der TV-Wand herunter und über den Boden nach vorne, hin und zurück
    ph = (b / per) % 2.0
    s = (ph if ph <= 1.0 else 2.0 - ph) * (1.9 + 2.5)
    x = 2.5 + 1.2 * math.sin(2 * math.pi * b / (2 * per))
    return (x, 0.0, 1.9 - s) if s < 1.9 else (x, s - 1.9, 0.0)


def x_wandlauf(b, per):      # entlang Seitenwand, TV-Wand, Seitenwand – hin und zurück
    ph = (b / per) % 2.0
    s = (ph if ph <= 1.0 else 2.0 - ph) * 13.0
    if s < 4.0:
        return (0.0, 4.0 - s, 1.6)
    s -= 4.0
    return (s, 0.0, 1.6) if s < 5.0 else (5.0, s - 5.0, 1.6)


def x_fokus(b, per):         # Sprung zwischen festen Punkten im ganzen Raum
    return ANCHORS[int(b // per) % len(ANCHORS)]


CROSS = {"wand_boden": x_wand_boden, "wandlauf": x_wandlauf, "fokus": x_fokus}
CROSS_JUMPS = {"fokus": len(ANCHORS)}

# Mindestdauer in Sekunden (mit Anschub/Vorsteuerung im Webserver): Durchlauf bzw. ein Sprung
MIN_SEC = {"kreis": 1.2, "acht": 1.6, "pendel_h": 1.0, "pendel_v": 1.0, "diagonale": 1.0,
           "spirale": 1.2, "welle": 2.0, "zickzack": 1.6, "zufall": 2.0,
           "stern": 0.7, "quadrat": 0.7, "springen": 0.7,
           "wand_boden": 1.6, "wandlauf": 2.4, "fokus": 0.7}


def playable(kind, per, bpm):
    """Schläge pro Durchlauf (bzw. Sprung) so weit verdoppeln, dass die Mechanik mitkommt (5 % Toleranz)."""
    while per * 60.0 / bpm < 0.95 * MIN_SEC.get(kind, 0.0):
        per *= 2
    return per


def point_fn(scene):
    """Funktion (b, per) → Raumpunkt für eine Szene."""
    kind = scene["shape"]
    if kind in CROSS:
        return CROSS[kind]
    f, surface = SHAPES[kind], scene["surface"]
    return lambda b, per: to_surface(surface, *f(b, per, scene))


def cycle_of(scene, per):
    """Schläge für einen vollen Durchlauf (bei Sprungformen: alle Punkte einmal)."""
    kind = scene["shape"]
    if kind in JUMPS:
        n = JUMPS[kind] or len(scene["pts"])
        return per * n
    if kind in CROSS_JUMPS:
        return per * CROSS_JUMPS[kind]
    return per


# --- Verhältnis der beiden Köpfe ------------------------------------------------------------------
def relate(rel, fn, b, per, cycle):
    p1 = fn(b, per)
    if rel == "spiegel":
        p2 = (5.0 - p1[0], p1[1], p1[2])
    elif rel == "gegenlaeufig":
        p2 = fn(b + cycle / 2, per)
    elif rel == "versetzt":
        p2 = fn(b - 0.5, per)
    elif rel == "folgen":
        p2 = fn(b - 1.0, per)
    elif rel == "kanon":
        p2 = fn(b - cycle / 4, per)
    elif rel == "frage_antwort":   # einer bewegt sich, der andere hält, taktweise im Wechsel
        hold = math.floor(b / BAR) * BAR
        even = int(b // BAR) % 2 == 0
        p1 = fn(b if even else hold, per)
        p2 = fn((hold if even else b) + cycle / 2, per)
    elif rel == "kreuz":           # für Nebel: jeder Kopf leuchtet auf die gegenüberliegende Seite
        x_a, x_b = p1[0], 5.0 - p1[0]
        p1, p2 = (max(x_a, x_b), p1[1], p1[2]), (min(x_a, x_b), p1[1], p1[2])
    else:                          # gleich
        p2 = p1
    return {1: p1, 2: p2}


# --- Dimmer-Muster: Pegel 0..1 --------------------------------------------------------------------
def _decay(frac, floor):
    return max(floor, 1.0 - frac * 1.6)


def _dip(frac, floor, width):
    """Kurz vor dem Schlag abdunkeln, auf dem Schlag schlagartig voll: Der Kick wirkt durch den Kontrast.
    width = Anteil des Schlags, der dunkel ist (Abfall in den ersten 30 % davon)."""
    start = 1.0 - width
    if frac < start:
        return 1.0
    x = (frac - start) / width
    return 1.0 - (1.0 - floor) * min(1.0, x / 0.3)


def dimmer(pattern, b, k, deep=False):
    """Die Köpfe sind lichtschwach: Grundpegel hoch, Pulse fallen nur kurz ab.
    Abdunkeln ist ein eigener Effekt (tief, blink), nicht der Normalfall.
    deep = Takt aus dem Audio eingerastet: Pulse sitzen genau, deshalb kräftiger (tiefer abfallen)."""
    f = 0.25 if deep else 0.5
    low = 0.0 if deep else 0.4      # Abdunkeln vor dem Schlag: mit genauer Phase ganz dunkel
    if pattern == "vorher":       # vor jedem Schlag dunkel, auf dem Kick voll
        return _dip(b % 1.0, low, 0.3)
    if pattern == "vorher_halb":  # nur vor jedem zweiten Schlag (ruhigere Lieder)
        return _dip((b / 2) % 1.0, low, 0.15)
    if pattern == "vorher_wechsel":   # Köpfe abwechselnd: einer dunkelt vor dem Schlag ab, der andere bleibt
        on = (int(b + 0.5) % 2 == 0) == (k == 1)
        return _dip(b % 1.0, low, 0.3) if on else 1.0
    if pattern == "atmen":
        return 0.8 + 0.2 * (0.5 - 0.5 * math.cos(2 * math.pi * b / 8))
    if pattern == "konstant":
        return 1.0
    if pattern == "halbzeit":
        return _decay((b / 2) % 1.0, f)
    if pattern == "puls":
        return _decay(b % 1.0, f)
    if pattern == "gegenpuls":
        return _decay((b + (0.5 if k == 2 else 0.0)) % 1.0, f)
    if pattern == "doppel":
        return _decay((2 * b) % 1.0, f + 0.05)
    if pattern == "offbeat":
        return _decay((b + 0.5) % 1.0, f)
    if pattern == "wechsel":      # Köpfe abwechselnd auf den Schlägen
        on = (int(b) % 2 == 0) == (k == 1)
        return _decay(b % 1.0, f) if on else f - 0.05
    if pattern == "tief":         # voll hell, am Ende jedes Takts kurz abdunkeln
        return 0.25 if (b % BAR) >= BAR - 0.5 else 1.0
    if pattern == "blink":        # 2 Schläge an, 2 Schläge aus (seltener Effekt)
        return 1.0 if int(b // 2) % 2 == 0 else 0.0
    return 1.0


# Mit eingerastetem Takt: diese Muster pulsen auf jedem Schlag durch Abdunkeln davor
DIP_LIVE = {"puls": "vorher", "halbzeit": "vorher", "wechsel": "vorher_wechsel"}


# --- Szenen-Generator -----------------------------------------------------------------------------
SHAPES_BY_SURFACE = {
    "wand": ["kreis", "acht", "pendel_h", "pendel_v", "diagonale", "spirale", "welle", "zickzack",
             "zufall", "stern", "quadrat", "springen"],
    "boden": ["kreis", "acht", "pendel_h", "pendel_v", "diagonale", "spirale", "welle", "zufall",
              "stern", "quadrat", "springen"],
    "decke": ["kreis", "acht", "spirale", "zufall", "stern"],
    "quer": ["wand_boden", "wandlauf", "fokus"],
}
RELS = {"ruhig": ["gleich", "spiegel", "gegenlaeufig", "folgen", "kanon"],
        "mittel": ["gleich", "spiegel", "gegenlaeufig", "folgen", "kanon", "versetzt"],
        "druckvoll": ["spiegel", "gegenlaeufig", "versetzt", "folgen", "kanon", "frage_antwort"]}
DIMS = {"ruhig": ["atmen", "konstant", "konstant", "tief"],
        "mittel": ["halbzeit", "offbeat", "wechsel", "konstant", "tief", "halbzeit", "puls"],
        "druckvoll": ["puls", "gegenpuls", "doppel", "wechsel", "konstant", "tief", "puls", "offbeat",
                      "puls", "blink"]}
COLORS = {"ruhig": ["base", "accent", "getrennt"],
          "mittel": ["base", "accent", "getrennt", "wechsel_takt"],
          "druckvoll": ["base", "accent", "getrennt", "wechsel_takt", "wechsel_takt"]}
PERS = {"ruhig": [16, 32], "mittel": [8, 16], "druckvoll": [4, 8]}          # Schläge pro Durchlauf
JUMP_PERS = {"ruhig": [4, 8], "mittel": [2, 4], "druckvoll": [1, 2]}       # Schläge pro Sprung


def make_scene(rng, stage, surface, nebel=False):
    shape = rng.choice(SHAPES_BY_SURFACE[surface])
    scene = {"shape": shape, "surface": surface}
    if surface != "quer":
        (ulo, uhi), (vlo, vhi) = SURF[surface]["u"], SURF[surface]["v"]
        su = rng.uniform(0.2, 0.48) * (uhi - ulo)
        sv = rng.uniform(0.2, 0.48) * (vhi - vlo)
        scene.update(su=su, sv=sv, cu=rng.uniform(ulo + su, uhi - su), cv=rng.uniform(vlo + sv, vhi - sv),
                     ph=rng.uniform(0, 2 * math.pi), dir=rng.choice([-1, 1]),
                     phs=[rng.uniform(0, 2 * math.pi) for _ in range(4)],
                     pts=[(rng.uniform(ulo, uhi), rng.uniform(vlo, vhi)) for _ in range(rng.randint(3, 5))])
    jumpy = shape in JUMPS or shape in CROSS_JUMPS
    rels = RELS[stage] + (["kreuz", "kreuz"] if nebel else [])
    scene.update(
        per=rng.choice(JUMP_PERS[stage] if jumpy else PERS[stage]),
        rel=rng.choice(rels), rel2=rng.choice(rels),
        dim=rng.choice(DIMS[stage]), dim2=rng.choice(DIMS[stage]),
        farbe=rng.choice(COLORS[stage]),
        gobo=(rng.choice(["offen", "offen", "signatur"]) if surface in ("wand", "quer")
              else rng.choice(["signatur", "signatur", "zweit"])),
        # Richtungswechsel alle 2 oder 4 Schläge (nur fließende Formen)
        umkehr=0 if jumpy else rng.choice([0, 0, 0, 2, 4]),
    )
    return scene


def umkehr(b, length):
    """Richtungswechsel alle `length` Schläge: vorwärts über `length`, dann halb so weit zurück.
    Ohne Sprünge, und die Bahn kommt trotzdem voran (netto ein Viertel pro Hin und Her)."""
    j = math.floor(b / (2 * length))
    m = b - j * 2 * length
    start = j * length / 2
    return start + (m if m < length else length - (m - length) / 2)


def scene_name(scene):
    where = {"wand": "Wand", "boden": "Boden", "decke": "Decke", "quer": "Raum"}[scene["surface"]]
    return f"{scene['shape']}@{where}"


# --- Song-Profil ----------------------------------------------------------------------------------
def stage_of(energy):
    if energy is None:
        return "mittel"
    if energy >= 0.6:
        return "druckvoll"
    return "mittel" if energy >= 0.4 else "ruhig"


def base_color(key, rng):
    """Grundfarbe aus der Tonart: gleiche Tonart, gleiche Farbe. Dur warm, Moll kühl."""
    if key and "-" in key:
        name, mode = key.split("-", 1)
        pc = PITCH.get(name)
        if pc is not None:
            fifths = (pc * 7) % 12  # Position im Quintenzirkel
            return (MINOR if mode.lower().startswith("min") else MAJOR)[fifths % 4]
    return rng.choice(MAJOR + MINOR)


def profile(track_id, info, duration=None, nebel=False):
    """Festes Thema je Lied, abgeleitet aus der Track-ID (gleiches Lied = gleiche Show)."""
    seed = int(hashlib.sha1((track_id or "ohne-id").encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed)
    bpm = float(info["bpm"])
    stage = stage_of(info.get("energy"))
    base = base_color(info.get("key"), rng)
    valence = info.get("valence")
    accent = (base + (1 if (valence if valence is not None else 0.5) >= 0.5 else -1)) % len(WHEEL)
    if accent == base:
        accent = (base + 1) % len(WHEEL)
    gobo, gobo2 = rng.sample(sorted(GOBO_ZITTERN), 2)
    # 5 Szenen über die Flächen verteilt: mindestens 2× Boden, 1× Wand, dazu Decke oder Raum
    surfaces = ["boden", "boden", "wand", rng.choice(["decke", "quer", "wand"]), rng.choice(["boden", "wand", "quer"])]
    rng.shuffle(surfaces)
    scenes = [make_scene(rng, stage, s, nebel) for s in surfaces]
    perm = list(range(5))
    rng.shuffle(perm)
    order = [perm[i] for i in [0, 1, 0, 2, 3, 1, 4, 2]]
    refrain = make_scene(rng, "druckvoll" if stage != "ruhig" else "ruhig",
                         rng.choice(["boden", "wand", "quer"]), nebel)
    prof = {
        "seed": seed, "bpm": bpm, "stage": stage,
        "beats_total": duration * bpm / 60.0 if duration else None,
        "base": base, "accent": accent, "gobo": gobo, "gobo2": gobo2,
        "motif": rng.choice(ANCHORS),
        "scenes": scenes, "order": order, "refrain": refrain,
    }
    prof["laser"] = laser_theme(rng, stage)   # nach allen anderen Zufallswerten: Kopf-Themen bleiben gleich
    # Lampen wechseln alle 8 oder 16 Takte (ruhige Lieder eher seltener); eigener Zufall, Themen bleiben gleich
    lrng = random.Random(seed ^ 0x1A3)
    prof["lamp_beats"] = 64 if lrng.random() < (0.7 if stage == "ruhig" else 0.35) else 32
    # Laser-Rolle je Lied: passt nicht zu jedem Lied und soll nicht dauernd laufen
    prof["laser_role"] = lrng.choices(list(L_ROLES), weights=[w[stage] for w in L_ROLES.values()])[0]
    return prof


def describe(prof):
    return (f"{prof['stage']}, Farben {WHEEL_NAMES[prof['base']]}/{WHEEL_NAMES[prof['accent']]}, "
            f"Gobos {GOBO_NAMES[prof['gobo']]}/{GOBO_NAMES[prof['gobo2']]}, "
            f"Lampen alle {prof.get('lamp_beats', 32) // 4} Takte, "
            f"Laser {L_ROLE_NAMES[prof.get('laser_role', 'voll')]}")


INTRO = {"shape": "kreis", "surface": "decke", "cu": 2.5, "cv": 3.0, "su": 0.5, "sv": 0.5, "ph": 0.0,
         "per": 32, "rel": "gegenlaeufig", "dim": "atmen", "farbe": "base", "gobo": "signatur"}


# --- Was zu einem Zeitpunkt läuft ------------------------------------------------------------------
OUTRO_BEATS = 8          # letzte 2 Takte: Spots laufen zusammen
OUTRO_LIVE_BEATS = 48    # bis 12 Takte vor Schluss, wenn die Musik hörbar ausläuft


def look(prof, b, live=None):
    """Abschnitt, Szene und Abwandlungen zum Zeitpunkt b (Schläge seit Liedanfang).
    live = Live-Audio (Break/Drop aus der Analyse); hat Vorrang vor der geschätzten Phrasenstruktur."""
    total = prof["beats_total"]
    ph = int(b // PHRASE)
    in_ph = b % PHRASE
    st = {"teil": "Szene", "scene": None, "motiv": False, "scale": 1.0, "tempo": 1.0,
          "dim": None, "rel": None, "farbe": None, "gobo": None, "strobe": False, "var": "",
          "umkehr": None}
    # Ruhiges Intro nur, wenn das Lied auch ruhig beginnt; setzt die Musik gleich voll ein (Live-Audio), geht
    # die Show sofort los
    full_start = live is not None and not live.get("break") and live.get("level", 0.0) > 0.5
    if b < PHRASE and not full_start:
        st.update(teil="Intro", scene=INTRO, scale=0.85 + 0.15 * (b / PHRASE))
        return st
    # Outro: Die Show läuft bis kurz vor Schluss voll weiter. Nur die letzten 2 Takte laufen die Spots zusammen;
    # früher (bis 12 Takte vorher) nur, wenn das Audio zeigt, dass die Musik ausläuft (Break ohne Kick)
    left = total - b if total else None
    if left is not None and (left < OUTRO_BEATS or (left < OUTRO_LIVE_BEATS and live and live.get("break"))):
        if left < OUTRO_BEATS:
            scale = 0.6 + 0.4 * max(0.0, left) / OUTRO_BEATS
        else:
            scale = 0.4 + 0.6 * live.get("level", 1.0)
        st.update(teil="Outro", scene=dict(INTRO, shape="fokus", surface="quer", per=64, rel="gleich",
                                            gobo="offen"),
                  motiv=True, scale=scale)
        return st
    if live and live.get("drop"):                  # echter Drop aus dem Audio: sofort Höhepunkt, Blitz
        st.update(teil="Drop", scene=prof["refrain"], farbe="split",
                  gobo="zittern3" if prof["stage"] != "ruhig" else "zittern1",
                  strobe=live.get("drop_beats", 99.0) < 1.0)
        return st
    if live and live.get("break"):                 # echter Break: ruhig, langsamer, atmen
        st.update(teil="Break", scene=prof["scenes"][prof["order"][(ph - 1) % len(prof["order"])]],
                  dim="atmen", tempo=0.5, scale=0.85)
        return st
    peaks = prof["stage"] != "ruhig"
    loud = prof["stage"] == "druckvoll"
    luck = random.Random(prof["seed"] * 7919 + ph).random()   # fester Zufall je Phrase
    if peaks and ph % 4 == 3:                      # Höhepunkt: Refrain-Szene, Zittern, Strobe am Anfang
        st.update(teil="Höhepunkt", scene=prof["refrain"], farbe="split",
                  gobo="zittern3" if loud else "zittern1",
                  strobe=in_ph < (BAR if loud else 1))
        if in_ph >= PHRASE / 2:
            st.update(tempo=2.0, var="schneller")
        return st
    scene = prof["scenes"][prof["order"][(ph - 1) % len(prof["order"])]]
    st["scene"] = scene
    if peaks and ph % 4 == 0 and ph >= 4 and in_ph < 2 * BAR:   # Atempause nach dem Höhepunkt
        st.update(teil="Atempause", dim="atmen", tempo=0.5, scale=0.9)
        return st
    if in_ph < BAR:                                # Motiv am Anfang jeder Phrase, manchmal mit Blitz
        st.update(teil="Motiv", motiv=True, farbe="accent", strobe=loud and luck < 0.35 and in_ph < 1)
        return st
    if peaks and ph % 4 == 2 and in_ph >= PHRASE - 2 * BAR:     # Aufbau vor dem Höhepunkt
        rise = (in_ph - (PHRASE - 2 * BAR)) / (2 * BAR)
        st.update(teil="Aufbau", scale=0.8 + 0.2 * rise, dim="puls" if rise < 0.5 else "doppel",
                  gobo="zittern1" if scene["gobo"] != "offen" else None,
                  strobe=PHRASE - 2 <= in_ph < PHRASE - 1)   # Blitz kurz vor dem Höhepunkt
        return st
    # kurzer Blitz in der Phrasenmitte, je nach Phrase
    if PHRASE / 2 <= in_ph < PHRASE / 2 + 1 and luck < (0.5 if loud else 0.25 if peaks else 0.0):
        st["strobe"] = True
    if in_ph >= PHRASE / 2:                        # Variation in der zweiten Phrasenhälfte
        var = random.Random(prof["seed"] * 1009 + ph).choice(
            ["keine", "schneller", "verhaeltnis", "dimmer", "farbe", "umkehr"])
        if var == "umkehr":
            st["umkehr"] = 2
        elif var == "schneller":
            st["tempo"] = 2.0
        elif var == "verhaeltnis":
            st["rel"] = scene["rel2"]
        elif var == "dimmer":
            st["dim"] = scene["dim2"]
        elif var == "farbe":
            st["farbe"] = "getrennt"
        st["var"] = "" if var == "keine" else var
    return st


def _color(prof, mode, b, k):
    base, acc = WHEEL[prof["base"]], WHEEL[prof["accent"]]
    if mode == "accent":
        return acc
    if mode == "getrennt":
        return base if k == 1 else acc
    if mode == "wechsel_takt":
        return base if int(b // BAR) % 2 == 0 else acc
    if mode == "split":
        return SPLIT.get(frozenset((base, acc)), acc)
    return base


def _gobo(prof, mode):
    if mode == "signatur":
        return prof["gobo"]
    if mode == "zweit":
        return prof["gobo2"]
    if mode and mode.startswith("zittern"):
        return GOBO_ZITTERN[prof["gobo"]][int(mode[-1]) - 1]
    return 0


def _wheels(prof, st, b, k):
    farbe = _color(prof, st["farbe"] or st["scene"]["farbe"], b, k)
    gobo = _gobo(prof, st["gobo"] or st["scene"]["gobo"])
    return farbe, gobo


# --- Ein Bild ---------------------------------------------------------------------------------------
def _strobe_amount(prof, st, b, strobe, amount):
    """Strobe-Menge in Prozent: 100 = wie geplant, darunter fallen einzelne Blitze weg (0 = keine), darüber
    kommen kurze Blitze auf der „1“ dazu: mehr in Aufbau, Höhepunkt und Drop, bei 200 auch in normalen Szenen.
    Die Blitze sind kurz (höchstens ein halber Schlag), nie länger als bisher."""
    bar = int(b // BAR)
    luck = random.Random(prof["seed"] * 31 + bar).random()
    if amount <= 0:
        return False
    if amount < 100:
        return strobe and luck < amount / 100.0
    extra = (amount - 100) / 100.0
    in_bar = b % BAR
    big = st["teil"] in ("Aufbau", "Höhepunkt", "Drop")
    if big and in_bar < 0.5 * extra:
        return True
    if st["teil"] in ("Szene", "Motiv") and luck < 0.5 * extra and in_bar < 0.25:
        return True
    return strobe


def frame(prof, b, b_move=None, strobe_on=True, tempo=1.0, live=None, locked=False, strobe_amount=100):
    """Ein Bild für beide Köpfe. b = Taktposition jetzt, b_move = Taktposition für die Bewegung
    (vorgezogen um die Laufzeit des Kopfes). tempo = Faktor für die Bahnen (2 = doppelt so schnell).
    Rückgabe: {kopf: {ziel, hell, farbe, gobo, strobe}}, Info-Text."""
    b_move = b if b_move is None else b_move
    st = look(prof, b, live)
    scene = st["scene"]
    # Radwechsel im Dunkeln: letzter Schlag vor einer neuen Phrase (nicht während Drop/Break aus dem Audio)
    dark = False
    wheels = {k: _wheels(prof, st, b, k) for k in (1, 2)}
    if b % PHRASE >= PHRASE - 1 and st["teil"] not in ("Drop", "Break"):
        nb = (int(b // PHRASE) + 1) * PHRASE
        nst = look(prof, nb)
        nxt = {k: _wheels(prof, nst, nb, k) for k in (1, 2)}
        if nxt != wheels:
            dark, wheels = True, nxt
    # Bewegung
    per = playable(scene["shape"], scene["per"] / (tempo * st["tempo"]), prof["bpm"])
    fn = point_fn(scene)
    flip = st["umkehr"] or scene.get("umkehr", 0)
    if flip and scene["shape"] not in JUMPS and scene["shape"] not in CROSS_JUMPS:
        while flip * 60.0 / prof["bpm"] < 0.9:   # ein Richtungswechsel braucht Zeit (gemessen ~0,5 s)
            flip *= 2
        b_move = umkehr(b_move, flip)
    if st["motiv"]:
        targets = {1: prof["motif"], 2: prof["motif"]}
    else:
        targets = relate(st["rel"] or scene["rel"], fn, b_move, per, cycle_of(scene, per))
    pattern = st["dim"] or scene["dim"]
    strobe = st["strobe"]
    if locked:
        # Takt aus dem Audio eingerastet: die Effekte, die genau sitzen müssen, aufdrehen. Statt auf dem Kick
        # hochzudimmen, wird kurz vorher abgedunkelt (kräftiger Kontrast genau auf dem Schlag)
        if pattern == "konstant":
            pattern = "vorher_halb" if prof["stage"] == "ruhig" else "vorher"
        pattern = DIP_LIVE.get(pattern, pattern)
        in_ph = b % PHRASE
        if st["teil"] in ("Höhepunkt", "Drop") and prof["stage"] == "druckvoll" and in_ph < 4 * BAR:
            strobe = strobe or (b % BAR) < 0.5                # halber Schlag Strobe auf jeder „1“
        if st["teil"] == "Aufbau" and in_ph >= PHRASE - BAR:
            strobe = strobe or (b % 1.0) < 0.25               # Wirbel im letzten Takt vor dem Höhepunkt
    strobe = _strobe_amount(prof, st, b, strobe, strobe_amount)
    out = {}
    for k in (1, 2):
        farbe, gobo = wheels[k]
        level = 0.0 if dark else dimmer(pattern, b, k, deep=locked) * st["scale"]
        if farbe != 0 and level > 0:   # Farbfilter schlucken Licht: Absenkungen bei Farbe abschwächen
            level = 1.0 - (1.0 - level) * (0.9 if locked else 0.7)
        hell = 0 if level <= 0 else int(MIN_DIM + (255 - MIN_DIM) * min(1.0, level))
        out[k] = {"ziel": targets[k], "hell": hell, "farbe": farbe, "gobo": gobo,
                  "strobe": STROBE if (strobe and strobe_on and not dark) else 0}
    info = (f"{st['teil']}: {scene_name(scene)} · {st['rel'] or scene['rel']} · {pattern}"
            + (f" · {st['var']}" if st["var"] else ""))
    return out, info


if __name__ == "__main__":
    demo = {"bpm": 125.0, "energy": 0.81, "key": "A-Minor", "valence": 0.6}
    prof = profile("spotify:track:demo", demo, duration=240)
    print(describe(prof))
    for i, s in enumerate(prof["scenes"]):
        print(f"  Szene {i}: {scene_name(s)}, {s['rel']}, {s['dim']}, Farbe {s['farbe']}, Gobo {s['gobo']}")
    print(f"  Refrain: {scene_name(prof['refrain'])}, Folge {prof['order']}")
    for b in (0, 32, 36, 52, 80, 88, 96, 100, 116, 128, 132, 140, 470):
        out, info = frame(prof, b)
        p = out[1]["ziel"]
        print(f"b={b:5.0f}  {info:60s} K1 ({p[0]:.1f},{p[1]:.1f},{p[2]:.1f}) hell {out[1]['hell']:3d} "
              f"farbe {out[1]['farbe']:3d} gobo {out[1]['gobo']:3d} strobe {out[1]['strobe']}")


# --- Lampen (über HA, langsame Ebene) --------------------------------------------------------------
RGB = {0: (255, 255, 255), 17: (255, 0, 0), 22: (0, 255, 0), 36: (0, 0, 255), 44: (255, 190, 0),
       54: (255, 90, 0), 64: (110, 210, 255), 73: (170, 0, 255)}
LAMP_PCT = {"Intro": 20, "Motiv": 20, "Szene": 20, "Aufbau": 35, "Höhepunkt": 60, "Atempause": 10,
            "Drop": 70, "Break": 10}


def _wheel_color(idx):
    return WHEEL[(idx % (len(WHEEL) - 1)) + 1]          # ohne Weiß: Lampen sollen Farbe zeigen


def _lamp_colors(prof, b, teil, per):
    """Lampen in den beiden Farben der Köpfe (Grund- und Akzentfarbe des Liedes), im Wechsel: zeigen die Ambilights
    die eine, zeigen die Schränke die andere. Höhepunkt und Drop: alles in der Akzentfarbe. (Bis 0.9.5 kam eine
    dritte Farbe dazu, die die Köpfe nie zeigen: Raum und Show passten nicht zusammen.)"""
    pal = [_wheel_color(prof["base"] - 1), _wheel_color(prof["accent"] - 1)]
    if teil in ("Höhepunkt", "Drop"):
        return pal[1], pal[1]
    step = int(b // per)
    return pal[step % 2], pal[(step + 1) % 2]


LAMP_MIN_BEATS = 2 * BAR   # schneller nicht: Yeelights nehmen nur ca. 60 Befehle/min je Lampe an, HA schickt je
                           # Farbwechsel zwei (Einschalten und Farbe); bei 130 BPM sind 2 Takte 32 pro Minute


def lamp_period(prof, wechsel):
    """Schläge pro Farbwechsel der Ambilights: eingestellt (mindestens ein Takt) oder nach dem Lied."""
    return max(LAMP_MIN_BEATS, wechsel) if wechsel > 0 else prof.get("lamp_beats", PHRASE)


def lamps(prof, b, live=None, wechsel=0):
    """Farben und Helligkeit der Lampen. Die Ambilights wechseln hart auf dem Schlag durch die Farben des Liedes
    (Grund, Akzent, Gegenfarbe), alle `wechsel` Schläge (0 = nach dem Lied: 8 oder 16 Takte, mindestens ein Takt);
    die Schränke laufen einen Schritt versetzt. Schrank 1 (links vom TV) und Schrank 2 (rechts) spielen im
    Wechsel: alle 2 Takte ist einer hell, der andere gedimmt. Auf Höhepunkt und Drop leuchtet alles in der
    Akzentfarbe. Grenze: Yeelights nehmen nur ca. 60 Befehle pro Minute je Lampe an (gemessen: „client quota
    exceeded“ bei Wechseln schneller als ein Takt oder mit Dunkel davor)."""
    st = look(prof, b, live)
    teil = st["teil"]
    grund, akzent = _lamp_colors(prof, b, teil, lamp_period(prof, wechsel))
    if teil == "Outro":
        pct = max(5, int(20 * st["scale"] / 5) * 5)
    else:
        pct = LAMP_PCT.get(teil, 20)
    if prof["stage"] == "ruhig":
        pct = max(5, int(pct * 0.8))
    links = rechts = pct
    if teil not in ("Höhepunkt", "Drop", "Break", "Atempause", "Outro"):
        dim = max(3, int(pct * 0.2))                   # Wechselspiel: ein Schrank hell, der andere gedimmt
        links, rechts = (pct, dim) if int(b // (2 * BAR)) % 2 == 0 else (dim, pct)   # alle 2 Takte (Befehlsgrenze)
    return {"grund": (RGB[grund], pct), "akzent": (RGB[akzent], pct),
            "links": (RGB[akzent], links), "rechts": (RGB[akzent], rechts), "teil": teil}


WHITE = (255, 255, 255)
TV_FLASH = 0.5             # Länge eines Flashes auf der „1“ in Schlägen (ein Befehl an den Streifen dauert ca. 0,36 s)
TV_BLINDER = 1.0           # Länge eines Blinders in Schlägen


def tv(prof, b, live=None, blinder=2, flash=0, flash_len=TV_FLASH, blinder_len=TV_BLINDER):
    """LED-Streifen hinter dem TV (Govee, sehr hell). Grundzustand: die Farbe des Liedes, gedimmt (Helligkeit
    „tv_hell“), bei Höhepunkt und Drop die Akzentfarbe, im Break aus. Dazu weiß in voller Helligkeit:
    - Blinder (blinder_len Schläge): 1 = wenn Drop oder Höhepunkt einsetzen, 2 = zusätzlich auf der „1“ jeder Phrase.
    - Flash (flash_len Schläge ab der „1“ des Takts): 1 = nur in Höhepunkt und Drop, 2 = immer.
    Rückgabe: (rgb, prozent, weiß?) – Prozent bezieht sich auf die eingestellte Helligkeit, Weiß nicht."""
    st = look(prof, b, live)
    teil = st["teil"]
    if teil in ("Break", "Atempause"):
        return WHITE, 0, False
    peak = teil in ("Höhepunkt", "Drop")
    color = RGB[_wheel_color((prof["accent"] if peak else prof["base"]) - 1)]
    if blinder >= 1:
        if live and live.get("drop") and live.get("drop_beats", 99.0) < blinder_len:   # Drop live erkannt
            return WHITE, 100, True
        # Höhepunkt hat vor höchstens blinder_len Schlägen begonnen (Teile beginnen auf ganzen Schlägen)
        if teil == "Höhepunkt" and look(prof, math.floor(b) - math.ceil(blinder_len) + 0.5)["teil"] != "Höhepunkt" \
                and look(prof, b - blinder_len)["teil"] != "Höhepunkt":
            return WHITE, 100, True
    if blinder >= 2 and b % PHRASE < blinder_len:                                  # Phrasenwechsel
        return WHITE, 100, True
    if (flash >= 2 or (flash == 1 and peak)) and b % BAR < min(flash_len, BAR - 0.25):
        return WHITE, 100, True
    return color, 100, False


# --- Laser (gemessen, siehe SHOW.md) ----------------------------------------------------------------
L_MODE = 65            # Handbetrieb (0 = aus)
L_UP = 93              # Rotation, bei der die Symbole aufrecht stehen
L_TURN = 126           # Rotation 0–125 = eine volle Drehung (ebenso die Spiegel-Zyklen)
L_SIZE_MAX = 62        # Größe: 0 groß … 62 klein
L_SHAPES = {
    "linie": [13, 17, 21, 48, 52, 59, 64, 176, 181],
    "flaeche": [0, 8, 27, 34, 37, 136, 142, 148, 162, 167, 187, 222],
    "welle": [67, 73, 108],
    "stern": [102, 156, 172, 191, 212],
    "symbol": [43, 79, 87, 122, 132, 152, 201, 207, 231, 238],
}
L_COUNTDOWN = [92, 113, 116]                    # 3, 2, 1
L_COLOR = {0: 0, 17: 112, 22: 93, 36: 75, 44: 93, 54: 112, 64: 64, 73: 121}   # Kopffarbe → Laserfarbe
L_MIX = [0, 21, 30, 35, 47, 57]                 # Mischungen für Höhepunkt und Drop
L_ROTS = {"ruhig": ["aufrecht", "langsam", "langsam"], "mittel": ["aufrecht", "langsam", "takt", "wackeln"],
          "druckvoll": ["takt", "wackeln", "schlag", "langsam"]}
L_FLIPS = {"ruhig": ["aus"], "mittel": ["aus", "aus", "h", "v"], "druckvoll": ["aus", "h", "v", "h"]}
L_POS = {"ruhig": ["mitte", "acht"], "mittel": ["mitte", "acht", "sprung"],
         "druckvoll": ["acht", "sprung", "sprung", "mitte"]}
L_SIZE = {"ruhig": (30, 45), "mittel": (18, 35), "druckvoll": (8, 28)}
# Rolle des Lasers je Lied mit Gewicht nach Stimmung: aus / nur Höhepunkte / jede zweite Phrase / durchgehend
L_ROLES = {"aus": {"ruhig": 6, "mittel": 25, "druckvoll": 10},
           "akzent": {"ruhig": 3, "mittel": 35, "druckvoll": 35},
           "phrasen": {"ruhig": 1, "mittel": 30, "druckvoll": 30},
           "voll": {"ruhig": 0, "mittel": 10, "druckvoll": 25}}
L_ROLE_NAMES = {"aus": "aus", "akzent": "nur Höhepunkte", "phrasen": "jede zweite Phrase", "voll": "durchgehend"}


def laser_on(prof, teil, b):
    """Ob der Laser in diesem Moment mitspielt (nach der Laser-Rolle des Liedes)."""
    role = prof.get("laser_role", "voll")
    in_ph = b % PHRASE
    big = teil in ("Höhepunkt", "Drop") or (teil == "Aufbau" and in_ph >= PHRASE / 2)
    if role == "aus":
        return False
    if role == "akzent":
        return big
    if role == "phrasen":
        return big or (teil in ("Motiv", "Szene") and int(b // PHRASE) % 2 == 0)
    return True


def laser_theme(rng, stage):
    """Laser-Thema je Lied: Hauptform, Nebenform, Gag-Symbol und drei Laser-Szenen."""
    scenes = [{"shape": rng.choice(["haupt", "haupt", "neben"]), "rot": rng.choice(L_ROTS[stage]),
               "flip": rng.choice(L_FLIPS[stage]), "pos": rng.choice(L_POS[stage]),
               "size": rng.randint(*L_SIZE[stage]), "dots": rng.choice(["normal", "normal", "gestrichelt"])}
              for _ in range(3)]
    return {"haupt": rng.choice(L_SHAPES["flaeche"] + L_SHAPES["stern"]),
            "neben": rng.choice(L_SHAPES["linie"] + L_SHAPES["welle"]),
            "gag": rng.choice(L_SHAPES["symbol"]), "mix": rng.choice(L_MIX), "scenes": scenes}


def laser_frame(prof, b, live=None, locked=False):
    """Laser-Werte für einen Zeitpunkt. Position als (x, y) von -1 bis 1; der Server bildet sie auf die
    Schutzgrenzen ab. Alle anderen Werte sind DMX-Werte in den gemessenen Bereichen."""
    st = look(prof, b, live)
    teil = st["teil"]
    if not laser_on(prof, teil, b):
        return {"mode": 0, "pos": (0.0, 0.0), "teil": teil}
    lt = prof["laser"]
    ph = int(b // PHRASE)
    in_ph = b % PHRASE
    ls = lt["scenes"][prof["order"][(ph - 1) % len(prof["order"])] % len(lt["scenes"])]
    if teil == "Intro":
        ls = {"shape": "haupt", "rot": "langsam", "flip": "aus", "pos": "mitte", "size": 40, "dots": "normal"}
    elif teil == "Outro":
        ls = {"shape": "haupt", "rot": "langsam", "flip": "aus", "pos": "mitte", "size": 50, "dots": "gestrichelt"}
    elif teil == "Break":
        ls = dict(ls, rot="langsam", flip="aus", pos="mitte", size=42, dots="gestrichelt")
    elif teil in ("Drop", "Höhepunkt"):
        ls = dict(ls, shape="haupt", rot="schlag" if prof["stage"] == "druckvoll" else "takt",
                  flip="h", pos="sprung", size=10, dots="normal")
    shape = lt[ls["shape"]]
    if teil == "Motiv" and ph % 2 == 1:
        shape = lt["gag"]                          # jede zweite Phrase beginnt mit dem Gag-Symbol
    rot_mode = ls["rot"]
    pos_mode = ls["pos"]
    if teil == "Aufbau" and in_ph >= PHRASE - 3:   # Countdown 3, 2, 1 vor dem Höhepunkt
        shape = L_COUNTDOWN[min(2, int(in_ph - (PHRASE - 3)))]
        rot_mode, pos_mode = "aufrecht", "mitte"
    # Farbe aus dem Liedthema, Mischfarbe auf Höhepunkt und Drop
    if teil in ("Höhepunkt", "Drop"):
        color = lt["mix"]
    else:
        color = L_COLOR.get(_color(prof, st["farbe"] or st["scene"]["farbe"], b, 1), 0)
    # Drehung (eigener Winkel, 0–125 = eine Runde)
    turns = {"aufrecht": 0.0, "langsam": b / 8, "takt": b / 4, "schlag": b if locked else b / 2}
    if rot_mode == "wackeln":
        rot = L_UP + 12 * math.sin(2 * math.pi * b / 2)
    else:
        rot = L_UP + turns[rot_mode] * L_TURN
    rotate = int(round(rot)) % L_TURN
    # Münz-Kippen über die Spiegel, ein Zyklus pro Takt
    cycle = int(((b / BAR) % 1.0) * L_TURN)
    mirror_h = cycle if ls["flip"] == "h" else 0
    mirror_v = cycle if ls["flip"] == "v" else 0
    # Größe: Puls auf dem Schlag (groß), mit eingerastetem Takt kräftiger; sonst langsames Atmen
    base = ls["size"]
    if prof["stage"] != "ruhig" and teil not in ("Break", "Intro", "Outro"):
        frac = b % 1.0
        depth = 1.0 if locked else 0.5
        size = base * (1.0 - depth * max(0.0, 1.0 - frac * 2.5))
    else:
        size = base + 6 * math.sin(2 * math.pi * b / 8)
    size = int(max(0, min(L_SIZE_MAX, round(size))))
    # Position
    if pos_mode == "acht":
        x, y = 0.8 * math.sin(2 * math.pi * b / 16), 0.6 * math.sin(4 * math.pi * b / 16)
    elif pos_mode == "sprung":
        x, y = [(-0.7, -0.5), (0.7, -0.5), (0.7, 0.5), (-0.7, 0.5)][int(b // BAR) % 4]
    else:
        x, y = 0.0, 0.0
    dots = 0 if ls["dots"] == "normal" else (150 if teil != "Break" else 210)
    return {"mode": L_MODE, "shape": shape, "rotate": rotate, "mirror_h": mirror_h, "mirror_v": mirror_v,
            "size": size, "color": color, "dots": dots, "pos": (x, y), "teil": teil}


# --- Ruhe-Animationen (keine Musik) ----------------------------------------------------------------
IDLE_COLORS = [64, 73, 36, 22, 54, 17]     # Farbfolge beim Warten (eisblau, lila, blau, grün, orange, rot)
IDLE_COLOR_SEC = 24.0                      # so lange bleibt eine Farbe; der Radwechsel passiert im Dunkeln


def _level(x):
    return 0 if x <= 0 else int(MIN_DIM + (255 - MIN_DIM) * min(1.0, x))


def idle_frame(t, mode="warten", colors=None):
    """Bild für die Köpfe, wenn keine Musik läuft. t = Zeit in Sekunden.
    - "warten": Party an, noch keine Musik (oder zwischen zwei Liedern ohne Tempo): Sternhimmel an der Decke.
      Beide Köpfe ziehen langsam gegenläufig Kreise (40 s pro Runde), Gobo Punkte-Ring, sanftes Atmen,
      Farbe wechselt alle 24 s im Dunkeln.
    - "pause": Spotify pausiert: beide Spots treffen sich über dem TV, pendeln leicht und atmen in der
      Grundfarbe des Liedes.
    Rückgabe wie frame(): {kopf: {ziel, hell, farbe, gobo, strobe}}."""
    out = {}
    if mode == "pause":
        color = (colors or [64])[0]
        for k in (1, 2):
            sway = 0.25 * math.sin(2 * math.pi * t / 12.0 + (0 if k == 1 else math.pi))
            breath = 0.35 + 0.25 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 6.0))
            out[k] = {"ziel": (2.5 + sway, 0.0, 1.9), "hell": _level(breath), "farbe": color, "gobo": 0,
                      "strobe": 0}
        return out
    step = int(t // IDLE_COLOR_SEC)
    palette = colors or IDLE_COLORS
    color = palette[step % len(palette)]
    in_step = t % IDLE_COLOR_SEC
    for k in (1, 2):
        a = 2 * math.pi * t / 40.0 + (0 if k == 1 else math.pi)
        target = (2.5 + 1.3 * math.cos(a), 3.0 + 1.6 * math.sin(a), 2.5)
        breath = 0.3 + 0.3 * (0.5 - 0.5 * math.cos(2 * math.pi * (t / 10.0 + (0 if k == 1 else 0.5))))
        if in_step > IDLE_COLOR_SEC - 0.8 or in_step < 0.2:     # Radwechsel im Dunkeln
            breath = 0.0
        out[k] = {"ziel": target, "hell": _level(breath), "farbe": color, "gobo": 21, "strobe": 0}
    return out
