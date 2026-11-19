"""Show-Motor: verbindet Titel und Position (AirPlay), Tempo (FreqBlog), Live-Audio und die Show-Regeln (show.py) und
gibt 40 Bilder pro Sekunde an Köpfe, Laser und Lampen."""
from collections import deque
import threading
import time

import airplay
import config
import ha
import jsonfile
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
LIVE = {"live": None, "at": 0.0, "seeks": 0}   # laufendes Lied von AirPlay (airplay.now_playing); seeks zählt Spulen
SEEK_SEC = 5.0                       # Sprung der Liedposition ab dieser Größe gilt als Spulen
BEAT = {"stop": None, "info": "aus", "szene": "", "start": None, "lied": None, "b": None, "sync": None}   # laufende Show
WATCH = {"stop": None}               # Titel-Überwachung
SPOTS = {}                           # aktuelle Zielpunkte für die Vorschau im Raumbild
SYNC = {"pending": 0}                # Verschiebung der Schlagzählung von Hand (Schläge), wird im Bild übernommen
IDLE = {"on": False}                 # vom Party-Modus gesetzt: Party läuft (dann Ruhe-Animation, wenn keine Show)
BLACKOUT_SEC = 0.6                   # Liedwechsel: so lange dunkel, damit Farb- und Goborad unsichtbar laufen
# Die Show läuft nur mit Ton am Empfänger (wenn Audio an ist).
QUIET_PAUSE = 2.0                    # so lange kein Ton: Pause-Animation (Spots über dem TV)
QUIET_STOP = 10.0                    # so lange kein Ton: Show aus, Warte-Animation; neu, sobald wieder Ton kommt


def kugel():
    """Spiegelkugel aus den Einstellungen, oder None, wenn keine gespeichert ist."""
    k = SETTINGS["kugel_kopf"]
    if k not in (1, 2):
        return None
    return {"kopf": k, "pan": SETTINGS["kugel_pan"], "tilt": SETTINGS["kugel_tilt"], "xyz": SETTINGS["kugel_xyz"],
            "show": SETTINGS["kugel_show"], "gobo": SETTINGS["kugel_gobo"], "zittern": SETTINGS["kugel_zittern"],
            "idle": SETTINGS["kugel_idle"],
            "farbig": SETTINGS["kugel_farbig"], "test": SETTINGS["kugeltest"]}


def aim(k, v):
    """Pan/Tilt für ein Bild: direkt (Spiegelkugel) oder über den Raumpunkt."""
    return heads.aim_raw(k, *v["pt"]) if "pt" in v else heads.aim_show(k, v["ziel"])


def audio_mode():
    """Steuert der Ton die Show? (Audioanalyse vorhanden und in der Oberfläche an)"""
    return AUDIO is not None and SETTINGS["audio"]


def sound(now=None):
    """Kommt gerade Ton am Empfänger an?"""
    return AUDIO is not None and AUDIO.signal(now)


def song_position():
    """Position im Lied in Sekunden (was gerade aus dem Lautsprecher kommt), oder None, wenn nichts spielt. Von
    AirPlay: genau und im Takt des Tons. Die Analyse bekommt den Ton um den Ton-Vorlauf früher als der Lautsprecher.
    (Bis 0.9.16 aus HA, der Spotify-Position: die lag bis 11 s daneben.)"""
    lead = SETTINGS["ton_vorlauf"]
    pos = airplay.position(time.time() - lead)
    if pos is not None:
        return pos
    pos = live_position()
    return None if pos is None else max(0.0, pos - lead)


def live_position():
    """Position im Lied aus dem letzten Stand (hochgerechnet, Zeit der Analyse), oder None."""
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
    old, expected = LIVE.get("live"), live_position()
    if (old and expected is not None and live.get("pos") is not None and live.get("playing")
            and (old["title"], old["artist"]) == (live["title"], live["artist"])
            and abs(live["pos"] - expected) > SEEK_SEC):
        LIVE["seeks"] += 1
    LIVE.update(live=live, at=time.time())


def show_loop(prof, t0, stop):
    """Eine Show für ein Lied. Die Taktposition hängt an der Liedposition von AirPlay (ohne: an der Zeit
    seit dem Start); mit eingerastetem Audio zählt BeatCounter die Schläge selbst."""
    bpm = prof["bpm"]
    started = time.time()
    counter = BeatCounter()
    last_b = None
    frames, fps_t = 0, time.time()
    next_t = time.time()
    frame_times = deque(maxlen=600)
    seeks = LIVE["seeks"]
    last_sound = started
    lamps.LIVE_AT["fn"] = (lambda t, bpm_: AUDIO.live(t, bpm_)) if AUDIO is not None else None
    seen_model = downbeat.STATE["letzte"]
    prev_model = None                  # Tempo der vorigen Messung von Beat This (für die Bestätigung)
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
        b_pos = b
        live = None
        locked = False
        if audio_mode() and AUDIO.signal(t_a):
            live = AUDIO.live(t_a, bpm)            # Pegel, Break, Drop
            frac = None
            if AUDIO.phase_ok(t_a):                # Schlagphase, sobald das Raster eingerastet ist
                frac = AUDIO.phase(t_a)
                locked = True
            b = counter.update(t_a, b, frac, AUDIO.drop_at, AUDIO.change_at, bpm)
            st = downbeat.STATE
            # Auch ohne eingerasteten Takt: Liegt das Tempo aus der Datenbank falsch, kann der Takt gar nicht
            # einrasten (die Analyse ist auf das Tempo festgelegt); dann muss gerade das gemessene Tempo greifen
            if st["letzte"] != seen_model and BEAT["start"] and st["lied"] == tuple(BEAT["start"][:2]):
                seen_model = st["letzte"]                      # neues Ergebnis von Beat This für dieses Lied
                ratio = st["bpm"] / bpm if st["bpm"] else 1.0
                agree = prev_model is not None and abs(st["bpm"] / prev_model - 1.0) < 0.02
                prev_model = st["bpm"]
                if st["schlaege"] >= 16 and abs(ratio - 1.0) >= 0.04 and agree:
                    # Gemessenes Tempo schlägt die Datenbank (sie gilt nur, bis Beat This gemessen hat), z. B. FreqBlog
                    # 65 statt 130 BPM. Große Abweichung: erst wenn zwei Messungen übereinstimmen, dann die Show mit
                    # dem Tempo des Modells neu starten (Zählung, Abgleich und Bahnen hängen am Tempo); merken
                    title, artist, info, track_id, duration = BEAT["start"]
                    print(f"Tempo {bpm:.1f} → {st['bpm']:.1f} BPM (Beat This): {title}", flush=True)
                    save_tempo_fix(title, artist, st["bpm"])
                    threading.Thread(target=start_beat, daemon=True, args=(
                        title, artist, dict(info, bpm=st["bpm"], quelle="Beat This"), track_id, duration)).start()
                    return
                if st["bpm"] and 0.003 < abs(ratio - 1.0) < 0.04:
                    # Tempo aus der Datenbank etwas daneben: das genaue Tempo des Modells übernehmen
                    counter.events.append((t_a, f"Tempo {bpm:.1f} → {st['bpm']:.1f} BPM (Beat This)"))
                    bpm = prof["bpm"] = st["bpm"]
                    AUDIO.set_bpm_hint(bpm)
                    BEAT["lied"] = dict(BEAT["lied"] or {}, bpm=round(bpm, 1), tempo_quelle="Beat This")
                    save_tempo_fix(*BEAT["start"][:2], bpm)
                if locked:
                    b += counter.model_anchor(t_a, st["eins"], bpm, st["beats"])
            if counter.audio_off:              # Audio-Takt läuft nicht mit der Musik: nicht als eingerastet werten
                locked = False
        else:
            b = counter.update(t_a, b)
        # Pause (Musik pausiert oder kein Ton): Spots bleiben stehen und leuchten leise, Laser aus
        player = LIVE.get("live")
        paused = ((bool(player) and not player.get("playing") and now - LIVE["at"] < 10 and live is None)
                  or quiet > QUIET_PAUSE)
        if paused and last_b is not None:
            b = last_b
        last_b = b
        b_move = b + SETTINGS["vorlauf"] * bpm / 60.0   # Bewegung vorziehen, damit sie auf dem Schlag ankommt
        out, info = show.frame(prof, b, b_move, strobe_on=SETTINGS["strobe"], tempo=SETTINGS["tempo"],
                               strobe_amount=SETTINGS["strobe_menge"],
                               live=live, locked=locked, kugel=kugel())
        if paused:                             # Ruhe-Animation: Spots treffen sich über dem TV und atmen
            out = show.idle_frame(now, "pause", [show.WHEEL[prof["base"]]], kugel())
            info = "Pause"
        if SETTINGS["takttest"]:
            # Takt-Test zum Einstellen von Ton-Vorlauf und Takt-Sync: weiß auf TV-Wand-Mitte, Blitz auf jedem
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
            pan, tilt = aim(k, v)
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
        heads.FRAME.set()                      # Bild fertig: der Sender schickt es sofort
        frames += 1
        frame_times.append(now)
        if now - fps_t >= 2.0:                 # Bildrate für die Anzeige (Soll: 40)
            BEAT["fps"] = round(frames / (now - fps_t), 1)
            BEAT["bilder"] = heads.gaps(frame_times)
            frames, fps_t = 0, now
        BEAT["b"] = b
        if record.REC["on"]:
            record.trace(now, {"b": round(b, 3), "b_ha": round(b_pos, 3), "pos": pos, "bpm": bpm, "locked": locked,
                               "break": bool(live and live["break"]), "drop": bool(live and live["drop"]),
                               "info": info, "vorlauf": SETTINGS["ton_vorlauf"], "eins": counter.bar_info(),
                               "ereignisse": [e[1] for e in counter.events[-3:]],
                               "koepfe": {k: [s["pan"], s["tilt"], s["hell"] if s["on"] else 0]
                                          for k, s in heads.snapshot().items()}})
        recent = [f"{e[1]} (vor {int(t_a - e[0])} s)" for e in counter.events[-3:] if t_a - e[0] < 60]
        BEAT["sync"] = {"schlag": int(b % 4) + 1, "takt": int(b // 4) % 8 + 1, "phrase": int(b // 32) + 1,
                        "audio": locked, "ereignisse": recent,
                        "abweichung": round(counter.diff, 1),      # Diagnose: Position minus Zählung (Schläge)
                        "audio_aus": counter.audio_off, "schlag_nr": round(b, 3), "eins": counter.bar_info(),
                        "bpm": round(bpm, 2), "pause": bool(paused)}   # bpm/pause: die Oberfläche zählt selbst weiter
        szene = f"Takt {int(b // 4) + 1}.{int(b % 4) + 1} · {info}" + (" · Audio" if live else "")
        if counter.events and t_a - counter.events[-1][0] < 6.0:   # letzte Korrektur kurz anzeigen
            szene += f" · {counter.events[-1][1]}"
        BEAT["szene"] = szene
        lamps.follow(prof, b, live)
        # fester Takt gegen die Uhr: Bild k zur Zeit Start + k/FPS (eine Verzögerung verschiebt nicht alle folgenden)
        next_t += 1.0 / FPS
        if time.time() - next_t > 0.1:         # lange hängen geblieben: neu ansetzen statt nachzuholen
            next_t = time.time()
        stop.wait(max(0.0, next_t - time.time()))


# --- Thema je Lied: fest aus der Track-ID, auf Wunsch neu gewürfelt (Variante wird gemerkt) -----------
THEMES_FILE = config.DATA / "themen.json"
TEMPO_FILE = config.DATA / "tempo_korrektur.json"     # Tempo je Lied aus Beat This, wenn die Datenbank daneben lag


def save_tempo_fix(title, artist, bpm):
    fixes = jsonfile.load(TEMPO_FILE)
    fixes[f"{artist}|{title}"] = round(float(bpm), 2)
    jsonfile.save(TEMPO_FILE, fixes)


def song_tempo(title, artist):
    """Tempo-Daten aus der Datenbank; hat Beat This das Lied schon einmal genauer gemessen, gilt dieses Tempo."""
    found = tempo(title, artist)
    fix = jsonfile.load(TEMPO_FILE).get(f"{artist}|{title}")
    if fix:
        found = dict(found or {}, bpm=fix, quelle="Beat This")
    return found



def _theme_key(title, artist, track_id=None):
    """Das Thema hängt an Interpret und Titel (seit 0.9.16; bis dahin an der Spotify-ID aus HA)."""
    return f"{artist}|{title}"


def reroll():
    """Würfelt für das laufende Lied ein neues Thema und merkt es sich für dieses Lied."""
    if BEAT["stop"] is None or not BEAT["start"]:
        return False
    title, artist, _info, track_id, _dur = BEAT["start"]
    themes = jsonfile.load(THEMES_FILE)
    key = _theme_key(title, artist, track_id)
    themes[key] = themes.get(key, 0) + 1
    jsonfile.save(THEMES_FILE, themes)
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
        for k, v in show.idle_frame(now, "warten", kugel=kugel()).items():
            pan, tilt = aim(k, v)
            heads.apply(k, pan, tilt, True, v["farbe"], v["gobo"], 0, v["hell"])
            x, y, z = v["ziel"]
            SPOTS[str(k)] = {"x": float(x), "y": float(y), "z": float(z), "hell": int(v["hell"]),
                             "farbe": int(v["farbe"])}
        heads.FRAME.set()
        if not BEAT["szene"].startswith("Warten"):
            BEAT["szene"] = "Warten auf Musik · Sternhimmel"


def start_beat(title, artist, info, track_id=None, duration=None):
    """Startet die Show für einen Titel. info = Tempo-Daten (mindestens bpm)."""
    halt_beat()
    key = _theme_key(title, artist, track_id)
    variant = jsonfile.load(THEMES_FILE).get(key, 0)
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
    if not audio_mode() or time.time() - since < 8:
        return None
    st = AUDIO.status()
    if st["takt"] and st["bpm"] and st["sicher"] >= 0.5:
        return {"bpm": st["bpm"], "quelle": "Audio"}
    return None


def watch_loop(stop, current):
    """Prüft jede Sekunde den Titel von AirPlay. Bei einem neuen Titel wird das Tempo geholt und die Show neu
    gestartet. Mit Audio gilt der Ton am Empfänger: Ohne Ton startet keine Show (die Show selbst geht nach
    QUIET_STOP aus), mit Ton startet sie sofort, auch wenn AirPlay noch „pausiert“ meldet."""
    miss = {"at": 0.0, "since": time.time()}
    known = {}                                         # Titel → Tempo-Daten, für den Neustart nach einer Pause
    while not stop.wait(1):
        airplay.LEAD = SETTINGS["ton_vorlauf"]          # neuer Titel gilt, wenn sein Ton aus dem Lautsprecher kommt
        live = airplay.now_playing()
        if not live:
            # Kein Titel (Music Assistant schickt keine Metadaten, andere Quelle): läuft keine Show, aber es kommt
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
                if time.time() - miss["at"] > 20:      # FreqBlog nicht jede Sekunde fragen
                    miss["at"] = time.time()
                    found = song_tempo(*key)
                if not (found and found.get("bpm")):
                    found = audio_tempo(miss["since"])
                if found and found.get("bpm"):
                    start_beat(args[0], args[1], found, *args[3:])
            continue
        current = key
        found = song_tempo(*key)
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
            if not audio_mode():
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
    """Warnt, wenn Spotify spielt, aber am AirPlay-Empfänger kein Ton ankommt (z. B. der Empfänger nach einem
    Neustart nicht mehr in der Sync-Gruppe von Music Assistant). Dann kommen auch keine AirPlay-Metadaten an; nur
    HA weiß noch, dass Spotify spielt. Deshalb fragt nur diese Warnung den Spotify-Player in HA (Add-on-Option,
    optional), und nur solange kein Ton ankommt. Warnung in der Oberfläche und als HA-Benachrichtigung."""
    while True:
        time.sleep(2.0)
        now = time.time()
        if not audio_mode() or AUDIO.signal(now) or not config.PLAYER:
            expect = False
        else:
            # Spotify spielt über Music Assistant (dann gehört der Empfänger zur Gruppe), auch wenn die Party noch
            # aus ist: Gerade dann muss der Empfänger funktionieren, damit der Ton sie startet
            sp = ha.now_playing() or {}
            expect = bool(sp.get("playing")) and ("Music Assistant" in sp.get("source", "") or BEAT["stop"] is not None)
        if not expect:
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
                "message": f"Kein Audio, obwohl Spotify spielt. {hint}"})
            print("Warnung: kein Audio am AirPlay-Empfänger", flush=True)
