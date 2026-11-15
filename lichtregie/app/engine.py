"""Show-Motor: verbindet Titel (HA), Tempo (FreqBlog), Live-Audio und die Show-Regeln (show.py) und
gibt 40 Bilder pro Sekunde an Köpfe, Laser und Lampen."""
import json
import math
import threading
import time

import config
import ha
import heads
import lamps
import laser
import downbeat
import record
import show
try:            # numpy fehlt lokal ggf.; dann ohne Audioanalyse
    import audio
except ImportError:
    audio = None
from artnet import FPS
from beatcount import BeatCounter
from settings import SETTINGS
from tempo import tempo

AUDIO = audio.Analyzer() if (audio is not None and (config.AUDIO_PIPE or config.AUDIO_CMD)) else None
LIVE = {"live": None, "at": 0.0, "seeks": 0}   # letzter Stand des Spotify-Players aus HA; seeks zählt Spulen
SEEK_SEC = 5.0                       # Sprung der Liedposition ab dieser Größe gilt als Spulen
BEAT = {"stop": None, "info": "aus", "szene": "", "start": None, "lied": None, "b": None, "sync": None}   # laufende Show
WATCH = {"stop": None}               # Titel-Überwachung
SPOTS = {}                           # aktuelle Zielpunkte für die Vorschau im Raumbild
SYNC = {"pending": 0}                # Verschiebung der Schlagzählung von Hand (Schläge), wird im Bild übernommen
IDLE = {"on": False}                 # vom Party-Modus gesetzt: Party läuft (dann Ruhe-Animation, wenn keine Show)
BLACKOUT_SEC = 0.6                   # Liedwechsel: so lange dunkel, damit Farb- und Goborad unsichtbar laufen
# Die Show läuft nur mit Ton am Empfänger (wenn Audio an ist). HA meldet eine Pause erst nach bis zu 30 s.
QUIET_PAUSE = 2.0                    # so lange kein Ton: Pause-Animation (Spots über dem TV)
QUIET_STOP = 10.0                    # so lange kein Ton: Show aus, Warte-Animation; neu, sobald wieder Ton kommt


def audio_mode():
    """Steuert der Ton die Show? (Audioanalyse vorhanden und in der Oberfläche an)"""
    return AUDIO is not None and SETTINGS["audio"]


def sound(now=None):
    """Kommt gerade Ton am Empfänger an?"""
    return AUDIO is not None and AUDIO.signal(now)


def song_position():
    """Geschätzte Position im Lied in Sekunden, oder None, wenn nichts spielt."""
    live = LIVE.get("live")
    if not live or live.get("pos") is None or not live.get("playing"):
        return None
    return float(live["pos"]) + (time.time() - LIVE["at"])


def shift_beats(n):
    """Schlagzählung von Hand um n Schläge verschieben (4 = ein Takt)."""
    SYNC["pending"] += int(n)


def mark_one(grid):
    """„Jetzt ist die 1“: Der Schlag, der gerade läuft, wird zur 1 des Takts (grid 4) oder der Phrase (32)."""
    b = BEAT.get("b")
    if b is None:
        return False
    s = -(round(b) % grid)
    if s < -grid // 2:
        s += grid
    SYNC["pending"] += s
    return True


def update_live(live):
    """Neuen Stand des Players übernehmen. Springt die Position im selben Lied deutlich (Spulen), wird das
    gezählt; die Show setzt ihre Schlagzählung dann sofort neu auf."""
    old, expected = LIVE.get("live"), song_position()
    if (old and expected is not None and live.get("pos") is not None and live.get("playing")
            and (old["title"], old["artist"]) == (live["title"], live["artist"])
            and abs(live["pos"] - expected) > SEEK_SEC):
        LIVE["seeks"] += 1
    LIVE.update(live=live, at=time.time())


def show_loop(prof, t0, stop):
    """Eine Show für ein Lied. Die Taktposition hängt an der Liedposition aus HA (pausiert: an der Zeit
    seit dem Start); mit eingerastetem Audio zählt BeatCounter die Schläge selbst."""
    bpm = prof["bpm"]
    started = time.time()
    counter = BeatCounter()
    last_b = None
    frames, fps_t = 0, time.time()
    seeks = LIVE["seeks"]
    last_sound = started
    seen_model = downbeat.STATE["letzte"]
    if AUDIO is not None:        # Ereignisse aus dem vorigen Lied nicht als Anker nehmen
        counter.seen_drop, counter.seen_change = AUDIO.drop_at, AUDIO.change_at
    while not stop.is_set():
        now = time.time()
        if sound(now):
            last_sound = now
        quiet = now - last_sound if audio_mode() else 0.0
        if quiet > QUIET_STOP:                 # Musik aus: Show beenden, die Warte-Animation übernimmt
            if BEAT["stop"] is stop:
                print(f"Kein Ton seit {QUIET_STOP:.0f} s: Show aus, Warte-Animation", flush=True)
                halt_beat()
            return
        if LIVE["seeks"] != seeks:   # gespult: Zählung neu an die Liedposition hängen
            seeks = LIVE["seeks"]
            drop, change = counter.seen_drop, counter.seen_change
            counter.reset()
            counter.seen_drop, counter.seen_change = drop, change
            counter.events.append((now, "gespult: Zählung neu"))
        # Was jetzt aus dem Lautsprecher kommt, hat die Analyse um den Ton-Vorlauf früher bekommen: Alles aus dem
        # Ton (Schlag, Pegel, Break, Drop) und die Schlagzählung laufen deshalb auf dieser Zeit
        t_a = now - SETTINGS["ton_vorlauf"] if audio_mode() else now
        if SYNC["pending"]:                    # von Hand verschoben
            n, SYNC["pending"] = SYNC["pending"], 0
            counter.shift(n, t_a, "von Hand")
        blackout = now - started < BLACKOUT_SEC
        pos = song_position()
        b = (pos if pos is not None else now - t0) * bpm / 60.0 + SETTINGS["offset"]
        b_ha = b
        live = None
        locked = False
        if AUDIO is not None and SETTINGS["audio"] and AUDIO.signal(t_a):
            live = AUDIO.live(t_a, bpm)            # Pegel, Break, Drop
            frac = None
            if AUDIO.phase_ok(t_a):                # Schlagphase, sobald das Raster eingerastet ist
                frac = AUDIO.phase(t_a + SETTINGS["audio_versatz"] / 1000.0)
                locked = True
            changes = AUDIO.changes_since(counter.seen_bc) if locked else None
            b = counter.update(t_a, b, frac, AUDIO.drop_at, AUDIO.change_at, bpm, changes)
            st = downbeat.STATE
            if locked and st["letzte"] != seen_model and BEAT["start"] and st["lied"] == tuple(BEAT["start"][:2]):
                seen_model = st["letzte"]                      # neues Ergebnis von Beat This für dieses Lied
                if st["bpm"] and 0.003 < abs(st["bpm"] - bpm) / bpm < 0.04:
                    # Tempo aus der Datenbank etwas daneben: das genaue Tempo des Modells übernehmen
                    counter.events.append((t_a, f"Tempo {bpm:.1f} → {st['bpm']:.1f} BPM (Beat This)"))
                    bpm = prof["bpm"] = st["bpm"]
                    AUDIO.set_bpm_hint(bpm)
                    BEAT["lied"] = dict(BEAT["lied"] or {}, bpm=round(bpm, 1), tempo_quelle="Beat This")
                b += counter.model_anchor(t_a, st["eins"], bpm, st["beats"])
            if counter.audio_off:              # Audio-Takt läuft nicht mit der Musik: nicht als eingerastet werten
                locked = False
        else:
            b = counter.update(t_a, b)
        # Pause (Spotify pausiert): Spots bleiben stehen und leuchten leise, Laser aus
        player = LIVE.get("live")
        paused = ((bool(player) and not player.get("playing") and now - LIVE["at"] < 10 and live is None)
                  or quiet > QUIET_PAUSE)
        if paused and last_b is not None:
            b = last_b
        last_b = b
        b_move = b + SETTINGS["vorlauf"] * bpm / 60.0   # Bewegung vorziehen, damit sie auf dem Schlag ankommt
        out, info = show.frame(prof, b, b_move, strobe_on=SETTINGS["strobe"], tempo=SETTINGS["tempo"],
                               strobe_amount=SETTINGS["strobe_menge"],
                               live=live, locked=locked)
        if paused:                             # Ruhe-Animation: Spots treffen sich über dem TV und atmen
            out = show.idle_frame(now, "pause", [show.WHEEL[prof["base"]]])
            info = "Pause"
        if SETTINGS["takttest"]:
            # Takt-Test zum Einstellen von Audio-Versatz und Takt-Sync: weiß auf TV-Wand-Mitte, Blitz auf jedem
            # Schlag. Die „1“ des Takts blitzt auf beiden Köpfen, die Schläge 2–4 nur auf Kopf 1 und schwächer,
            # die „1“ der Phrase (alle 8 Takte) auf beiden Köpfen und doppelt so lang.
            beat_no = int(b)
            long_flash = beat_no % 32 == 0
            flash = (b % 1.0) < (0.5 if long_flash else 0.15)
            one = beat_no % 4 == 0
            out = {k: {"ziel": (2.5, 0.0, 1.6), "farbe": 0, "gobo": 0, "strobe": 0,
                       "hell": (255 if (one or k == 1) and flash else show.MIN_DIM) if one else
                               (120 if k == 1 and flash else show.MIN_DIM)} for k in (1, 2)}
            info, live = "Takt-Test", None
        for k, v in out.items():
            pan, tilt = heads.aim_show(k, v["ziel"])
            hell, strobe = v["hell"], v["strobe"]
            if live and hell > 0:   # Live-Pegel hebt und senkt die Helligkeit leicht
                hell = max(show.MIN_DIM, int(hell * (0.75 + 0.25 * live["level"])))
            if blackout:
                hell = strobe = 0
            heads.apply(k, pan, tilt, True, v["farbe"], v["gobo"], strobe, hell)
            x, y, z = v["ziel"]
            SPOTS[str(k)] = {"x": float(x), "y": float(y), "z": float(z), "hell": int(hell), "farbe": int(v["farbe"])}
        if paused:
            laser.off()
        elif SETTINGS["laser"] and not SETTINGS["takttest"]:
            laser.apply_show(show.laser_frame(prof, b, live, locked))
        frames += 1
        if now - fps_t >= 2.0:                 # Bildrate für die Anzeige (Soll: 40)
            BEAT["fps"] = round(frames / (now - fps_t), 1)
            frames, fps_t = 0, now
        BEAT["b"] = b
        if record.REC["on"]:
            record.trace(now, {"b": round(b, 3), "b_ha": round(b_ha, 3), "pos": pos, "bpm": bpm, "locked": locked,
                               "break": bool(live and live["break"]), "drop": bool(live and live["drop"]),
                               "info": info, "vorlauf": SETTINGS["ton_vorlauf"], "eins": counter.bar_info(), "bins": [round(x, 3) for x in counter.bar_bins],
                               "ereignisse": [e[1] for e in counter.events[-3:]]})
        recent = [f"{e[1]} (vor {int(t_a - e[0])} s)" for e in counter.events[-3:] if t_a - e[0] < 60]
        BEAT["sync"] = {"schlag": int(b % 4) + 1, "takt": int(b // 4) % 8 + 1, "phrase": int(b // 32) + 1,
                        "audio": locked, "ereignisse": recent,
                        "abweichung": round(counter.diff, 1),      # Diagnose: HA-Position minus Zählung (Schläge)
                        "audio_aus": counter.audio_off, "schlag_nr": round(b, 2), "eins": counter.bar_info()}
        szene = f"Takt {int(b // 4) + 1}.{int(b % 4) + 1} · {info}" + (" · Audio" if live else "")
        if counter.events and t_a - counter.events[-1][0] < 6.0:   # letzte Korrektur kurz anzeigen
            szene += f" · {counter.events[-1][1]}"
        BEAT["szene"] = szene
        lamps.follow(prof, b, live)
        stop.wait(1.0 / FPS)


# --- Thema je Lied: fest aus der Track-ID, auf Wunsch neu gewürfelt (Variante wird gemerkt) -----------
THEMES_FILE = config.DATA / "themen.json"


def _themes():
    try:
        return json.loads(THEMES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _theme_key(title, artist, track_id):
    return track_id or f"{artist}|{title}"


def reroll():
    """Würfelt für das laufende Lied ein neues Thema und merkt es sich für dieses Lied."""
    if BEAT["stop"] is None or not BEAT["start"]:
        return False
    title, artist, _info, track_id, _dur = BEAT["start"]
    themes = _themes()
    key = _theme_key(title, artist, track_id)
    themes[key] = themes.get(key, 0) + 1
    try:
        THEMES_FILE.write_text(json.dumps(themes, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    restart_beat()
    return True


def idle_loop():
    """Ruhe-Animation mit 20 Bildern/s: läuft, solange die Party an ist, aber keine Show (noch keine Musik,
    Lied ohne Tempo, gerade zwischen zwei Shows). Laser aus; die Spots zeigt auch die Vorschau."""
    was_idle = False
    while True:
        time.sleep(0.05)
        idle = IDLE["on"] and BEAT["stop"] is None and not SETTINGS["takttest"]
        if not idle:
            was_idle = False
            continue
        if not was_idle:
            laser.off()
            was_idle = True
        now = time.time()
        for k, v in show.idle_frame(now, "warten").items():
            pan, tilt = heads.aim_show(k, v["ziel"])
            heads.apply(k, pan, tilt, True, v["farbe"], v["gobo"], 0, v["hell"])
            x, y, z = v["ziel"]
            SPOTS[str(k)] = {"x": float(x), "y": float(y), "z": float(z), "hell": int(v["hell"]),
                             "farbe": int(v["farbe"])}
        if not BEAT["szene"].startswith("Warten"):
            BEAT["szene"] = "Warten auf Musik · Sternhimmel"


def start_beat(title, artist, info, track_id=None, duration=None):
    """Startet die Show für einen Titel. info = Tempo-Daten (mindestens bpm)."""
    halt_beat()
    key = _theme_key(title, artist, track_id)
    variant = _themes().get(key, 0)
    prof = show.profile(f"{key}#{variant}" if variant else key, info, duration, nebel=SETTINGS["nebel"])
    stop = threading.Event()
    new_song = not BEAT["start"] or tuple(BEAT["start"][:2]) != (title, artist)
    BEAT["stop"] = stop
    BEAT["start"] = (title, artist, info, track_id, duration)
    BEAT["since"] = time.time()
    BEAT["info"] = f"{title} – {artist}: {prof['bpm']:.1f} BPM, {show.describe(prof)}"
    BEAT["lied"] = {
        "titel": title, "interpret": artist, "bpm": round(prof["bpm"], 1), "stufe": prof["stage"],
        "tempo_quelle": info.get("quelle", "FreqBlog"), "variante": variant,
        "farben": [show.WHEEL[prof["base"]], show.WHEEL[prof["accent"]]],
        "farbnamen": [show.WHEEL_NAMES[prof["base"]], show.WHEEL_NAMES[prof["accent"]]],
        "gobos": [show.GOBO_NAMES[prof["gobo"]], show.GOBO_NAMES[prof["gobo2"]]],
        "lampen_takte": prof["lamp_beats"] // 4, "laser": show.L_ROLE_NAMES[prof["laser_role"]]}
    if AUDIO is not None:
        if new_song:
            AUDIO.new_song()                   # Pegelspitzen des vorigen Liedes vergessen
        AUDIO.set_bpm_hint(prof["bpm"])
    threading.Thread(target=show_loop, args=(prof, time.time(), stop), daemon=True).start()


def restart_beat():
    """Baut die Show für den laufenden Titel neu auf (z. B. nach dem Umschalten von Nebel)."""
    if BEAT["stop"] is not None and BEAT["start"]:
        start_beat(*BEAT["start"])


def halt_beat():
    if BEAT["stop"] is not None:
        BEAT["stop"].set()
        BEAT["stop"] = None
        time.sleep(0.05)
        for k in heads.HEADS:    # kein Strobe nach dem Stopp
            heads.apply(k, strobe=0)
        laser.off()
    SPOTS.clear()
    BEAT.update(szene="", lied=None, b=None, sync=None)


def stop_all():
    halt_beat()
    if WATCH["stop"] is not None:
        WATCH["stop"].set()
        WATCH["stop"] = None
    BEAT["info"] = "aus"


# --- Titel-Überwachung -------------------------------------------------------------------------------
def audio_tempo(since):
    """Tempo aus der Audioanalyse, wenn ein Lied bei FreqBlog fehlt: frühestens 8 s nach dem Liedwechsel
    (Zeit zum Neu-Einrasten ohne Vorgabe) und nur bei sicherem Takt."""
    if AUDIO is None or not SETTINGS["audio"] or time.time() - since < 8:
        return None
    st = AUDIO.status()
    if st["takt"] and st["bpm"] and st["sicher"] >= 0.5:
        return {"bpm": st["bpm"], "quelle": "Audio"}
    return None


def watch_loop(stop, current):
    """Prüft alle 2 s den Titel in HA. Bei einem neuen Titel wird das Tempo geholt und die Show neu
    gestartet. Mit Audio gilt der Ton am Empfänger: Ohne Ton startet keine Show (die Show selbst geht nach
    QUIET_STOP aus), mit Ton startet sie sofort, auch wenn HA noch „pausiert“ meldet."""
    miss = {"at": 0.0, "since": time.time()}
    known = {}                                         # Titel → Tempo-Daten, für den Neustart nach einer Pause
    while not stop.wait(2):
        live = ha.now_playing()
        if not live:
            # HA kennt keinen Titel (Spotify-Integration weg, andere Quelle): läuft keine Show, aber es kommt
            # Musik an, startet eine Show nur nach dem Tempo aus dem Audio
            if BEAT["stop"] is None:
                found = audio_tempo(miss["since"])
                if found:
                    start_beat("Unbekannter Titel", "", found, f"unbekannt-{int(time.time())}")
            continue
        update_live(live)
        key = (live["title"], live["artist"])
        args = (live["title"], live["artist"], None, live.get("id"), live.get("duration"))
        if key == current:
            # Gleicher Titel, aber seine Show läuft nicht: gestoppt, oder es läuft noch die Show des
            # vorigen Liedes, weil das Tempo gefehlt hat
            stale = BEAT["start"] is not None and tuple(BEAT["start"][:2]) != key
            playing = sound() if audio_mode() else live.get("playing")
            if (BEAT["stop"] is None or stale) and playing:
                found = known.get(key)
                if found:
                    start_beat(args[0], args[1], found, *args[3:])
                    continue
                if time.time() - miss["at"] > 20:      # FreqBlog nicht im 2-s-Takt fragen
                    miss["at"] = time.time()
                    found = tempo(*key)
                if not (found and found.get("bpm")):
                    found = audio_tempo(miss["since"])
                if found and found.get("bpm"):
                    start_beat(args[0], args[1], found, *args[3:])
            continue
        current = key
        found = tempo(*key)
        if found and found.get("bpm"):
            known[key] = found
            if audio_mode() and not sound():
                # Kein Ton: nicht starten. Läuft noch die Show des vorigen Liedes, geht sie von selbst aus;
                # kommt Ton, startet die Show oben (gleicher Titel, Tempo bekannt)
                continue
            start_beat(args[0], args[1], found, *args[3:])
        else:
            # Tempo unbekannt: nicht dunkel stehen bleiben. Die Show läuft mit dem alten Lied weiter, bis das
            # Audio das neue Tempo gefunden hat (ohne Vorgabe), dann startet sie damit
            miss.update(at=time.time(), since=time.time())
            if AUDIO is not None:
                AUDIO.set_bpm_hint(None)
            BEAT["info"] = f"{live['title']}: kein Tempo bei FreqBlog, warte auf das Audio …"
            if AUDIO is None or not SETTINGS["audio"]:
                halt_beat()


def start_watch(title, artist):
    if WATCH["stop"] is not None:
        WATCH["stop"].set()
    stop = threading.Event()
    WATCH["stop"] = stop
    threading.Thread(target=watch_loop, args=(stop, (title, artist)), daemon=True).start()


# --- Warnung: kein Audio -----------------------------------------------------------------------------
AUDIO_WARN = {"since": None, "text": "", "notified": False}
AUDIO_WARN_SEC = 45.0      # so lange kein Ton, während Spotify spielt, bis gewarnt wird. Mehr als die bis zu
                           # 30 s, die HA nach einer Pause noch „spielt“ meldet: eine Pause ist kein Fehler
NOTIFY_ID = "lichtregie_audio"


def audio_watch_loop():
    """Warnt, wenn Spotify spielt und die Show läuft, aber am AirPlay-Empfänger kein Ton ankommt
    (z. B. der Empfänger nach einem Neustart nicht mehr in der Sync-Gruppe von Music Assistant).
    Warnung in der Oberfläche und als HA-Benachrichtigung; verschwindet, sobald wieder Ton kommt."""
    while True:
        time.sleep(2.0)
        now = time.time()
        live = LIVE.get("live") or {}
        # Ton erwartet: Spotify spielt über Music Assistant (dann gehört der Empfänger zur Gruppe), auch wenn
        # die Party noch aus ist: Gerade dann muss der Empfänger funktionieren, damit der Ton sie startet
        expect = (AUDIO is not None and SETTINGS["audio"] and live.get("playing") and now - LIVE["at"] < 30
                  and ("Music Assistant" in live.get("source", "") or BEAT["stop"] is not None))
        if not expect or AUDIO.signal(now):
            if AUDIO_WARN["notified"]:
                ha.call("persistent_notification", "dismiss", {"notification_id": NOTIFY_ID})
                print("Audio kommt wieder an", flush=True)
            AUDIO_WARN.update(since=None, text="", notified=False)
            continue
        AUDIO_WARN["since"] = AUDIO_WARN["since"] or now
        quiet = now - AUDIO_WARN["since"]
        if quiet < AUDIO_WARN_SEC:
            continue
        # Music Assistant nimmt einen Empfänger, der sich während der Wiedergabe neu anmeldet (z. B. nach einem
        # Update des Add-ons), nicht wieder in den laufenden Stream auf: Die Gruppe muss neu starten
        hint = (f"In Spotify das Gerät „Party modus“ neu auswählen oder die Wiedergabe in Music Assistant "
                f"stoppen und neu starten; prüfen, dass „{config.AIRPLAY_NAME}“ in der Gruppe ist.")
        st = AUDIO.status()
        cause = ("Es kommen Daten an, aber nur Stille (Lautstärke des Empfängers in Music Assistant?)."
                 if st["stumm"] else "Am Empfänger kommen keine Daten an.")
        AUDIO_WARN["text"] = f"Kein Audio seit {int(quiet)} s, obwohl Spotify spielt. {cause} {hint}"
        if not AUDIO_WARN["notified"]:
            AUDIO_WARN["notified"] = ha.call("persistent_notification", "create", {
                "notification_id": NOTIFY_ID, "title": "Lichtregie: kein Audio",
                "message": f"Kein Audio, obwohl Spotify spielt. {hint} Bis dahin läuft die Show nur nach "
                           f"der Spotify-Position."})
            print("Warnung: kein Audio am AirPlay-Empfänger", flush=True)
