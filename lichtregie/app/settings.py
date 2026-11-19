"""Einstellungen aus der Oberfläche. Sie überdauern einen Neustart (DATA/settings.json)."""

import config
import jsonfile

SETTINGS = {
    # Party-Modus: automatisch an, wenn Musik ankommt; aus nach so vielen Minuten ohne Musik
    "automatik": True, "party_aus_min": 15,
    # Show
    "strobe": True, "strobe_menge": 100, "nebel": False, "tempo": 2.0,        # tempo = Bewegungstempo ×1/×2
    "offset": 0.0,                                       # Phasen-Versatz in Schlägen (ohne Audio)
    # Mechanik der Köpfe (gemessen, siehe SHOW.md)
    "vorlauf": 0.4,                                      # Bewegung so viele Sekunden vorziehen
    "anschub": True, "vorsteuerung": 0.45,
    # Live-Audio
    # Ton-Vorlauf: Der Empfänger (shairport-sync, stdout) liefert den Ton ca. 1,0 s bevor der Lautsprecher ihn
    # spielt (Puffer 1 s; gemessen 15.11.2026 mit Aufnahmen und Beat This!). Die Show hängt so weit zurück.
    "audio": True, "ton_vorlauf": 1.0, "takttest": False,
    "beatthis": True,                                    # „1“ im Takt mit Beat This (downbeat.py)
    # Lampen über HA
    "lampen": True, "lampen_decke": 40, "lampen_vitrine": 100, "lampen_vorlauf": 0.8,
    # Ambilights: Farbwechsel alle so viele Schläge (0 = nach dem Lied: 8 oder 16 Takte; mindestens ein Takt),
    # hart (ohne Übergang); Lampen-Test zum Einstellen des Vorlaufs
    "lampen_wechsel": 8.0, "lampen_hart": True, "lampentest": False,
    # LED-Streifen (Govee, Bluetooth, sehr hell): Helligkeit der Farbe; Blinder (0 aus, 1 Drop/Höhepunkt,
    # 2 zusätzlich jeder Phrasenwechsel); Flash auf der „1“ (0 aus, 1 nur Höhepunkt/Drop, 2 immer); Vorlauf
    # (ein Befehl über HA und Bluetooth dauert ca. 0,36 s)
    "tv_hell": 5, "tv_blinder": 2, "tv_flash": 0, "tv_vorlauf": 0.35,
    "tv_blinder_lang": 1.0, "tv_flash_lang": 0.5,           # Länge in Schlägen
    "tv_blinder_hell": 100, "tv_flash_hell": 100,           # Prozent
    # Spiegelkugel: Kopf (0 = keine), gespeicherte Pan/Tilt und Raumpunkt (Vorschau), wann in der Show (0 nie,
    # 1 ruhige Teile, 2 zusätzlich Höhepunkt und Drop), Gobo (show.KUGEL_GOBOS) und Zittern (0 langsam, 1 mittel,
    # 2 schnell), in der Ruhe-Animation, farbig, Test
    "kugel_kopf": 0, "kugel_pan": 32768, "kugel_tilt": 32768, "kugel_xyz": None, "kugel_show": 1,
    "kugel_gobo": 3, "kugel_zittern": 0, "kugel_idle": True, "kugel_farbig": False, "kugeltest": False,
    # Laser: Senden an/aus, Schutzgrenzen, Ruhepunkt über dem TV (auf dem TV sieht man ihn schlecht)
    "laser": True, "laser_ud_min": 42, "laser_ud_max": 86, "laser_lr_min": 39, "laser_lr_max": 90,
    "laser_ud_mitte": 76,
}
FILE = config.DATA / "settings.json"
_saved = jsonfile.load(FILE)
SETTINGS.update(_saved)
SETTINGS["takttest"] = False   # Takt-Test und Lampen-Test starten nie von selbst
SETTINGS["lampentest"] = False
SETTINGS["kugeltest"] = False
if "tv_blitz" in SETTINGS:      # 0.9.17 → 0.9.18: Blinder und Flash getrennt; Vorlauf passend zur gemessenen Dauer
    SETTINGS["tv_vorlauf"] = max(SETTINGS.get("tv_vorlauf", 0.35), 0.35)
for _old in ("lampen_dunkel", "audio_versatz", "tv_blitz", "kugel_wackeln"):   # entfernte Einstellungen
    SETTINGS.pop(_old, None)

# Erlaubte Werte je Einstellung: bool oder (Typ, min, max)
RULES = {
    "beatthis": bool, "strobe": bool, "nebel": bool, "anschub": bool, "lampen": bool, "audio": bool, "takttest": bool,
    "laser": bool, "automatik": bool, "party_aus_min": (int, 1, 240),
    "lampen_hart": bool, "lampentest": bool, "lampen_wechsel": (float, 0.0, 64.0),
    "tv_hell": (int, 0, 100), "tv_blinder": (int, 0, 2), "tv_flash": (int, 0, 2), "tv_vorlauf": (float, 0.0, 1.0),
    "tv_blinder_lang": (float, 0.5, 8.0), "tv_flash_lang": (float, 0.25, 2.0),
    "tv_blinder_hell": (int, 5, 100), "tv_flash_hell": (int, 5, 100),
    "kugel_kopf": (int, 0, 2), "kugel_show": (int, 0, 2), "kugel_gobo": (int, 0, 6), "kugel_zittern": (int, 0, 2), "kugel_idle": bool,
    "kugel_farbig": bool, "kugeltest": bool,
    "strobe_menge": (int, 0, 200),
    "offset": (float, -64.0, 64.0), "tempo": (float, 0.25, 4.0), "vorsteuerung": (float, 0.0, 1.0),
    "ton_vorlauf": (float, 0.0, 3.0), "lampen_vorlauf": (float, 0.0, 2.0),
    "lampen_decke": (int, 0, 150), "lampen_vitrine": (int, 0, 150),
    "laser_ud_min": (int, 0, 255), "laser_ud_max": (int, 0, 255), "laser_lr_min": (int, 0, 255),
    "laser_lr_max": (int, 0, 255), "laser_ud_mitte": (int, 0, 255),
}


def save():
    jsonfile.save(FILE, SETTINGS)


def update(body):
    """Übernimmt bekannte Einstellungen aus einer Anfrage (geprüft und begrenzt) und speichert.
    Gibt die Namen der geänderten Einstellungen zurück."""
    changed = []
    for key, rule in RULES.items():
        if key not in body:
            continue
        if rule is bool:
            value = bool(body[key])
        else:
            kind, lo, hi = rule
            value = max(lo, min(hi, kind(float(body[key]))))
            if kind is float:
                value = round(value, 3)
        SETTINGS[key] = value
        changed.append(key)
    save()
    return changed
