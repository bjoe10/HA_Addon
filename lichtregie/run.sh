#!/usr/bin/with-contenv bashio
# HA-Zugang über den Supervisor (SUPERVISOR_TOKEN kommt aus der Umgebung), Daten unter /data,
# Art-Net-Nodes aus der gemappten HA-Konfiguration (/homeassistant/configuration.yaml).
export LICHTREGIE_DATA=/data
export LICHTREGIE_PORT=8475
# Host-Netzwerk: die Oberfläche nur über den HA-Ingress-Proxy erreichbar machen
export LICHTREGIE_ALLOWED_CLIENTS=172.30.32.2,127.0.0.1
export LICHTREGIE_HA_API=http://supervisor/core/api
export LICHTREGIE_HA_CONFIG=/homeassistant:/config
export LICHTREGIE_PLAYER="$(bashio::config 'spotify_player')"
export LICHTREGIE_FREQBLOG_KEY="$(bashio::config 'freqblog_key')"
export LICHTREGIE_LAMPEN_GRUND="$(bashio::config 'lampen_grund')"
export LICHTREGIE_LAMPEN_AKZENT="$(bashio::config 'lampen_akzent')"
export LICHTREGIE_LAMPEN_AUS="$(bashio::config 'lampen_aus')"
export LICHTREGIE_LAMPEN_TV="$(bashio::config 'lampen_tv')"
export LICHTREGIE_GERAETE="$(bashio::config 'geraete')"
export LICHTREGIE_LASER_SWITCH="$(bashio::config 'laser_schalter')"
export LICHTREGIE_AIRPLAY_NAME="$(bashio::config 'airplay_name')"

# --- AirPlay-Empfänger für die Audioanalyse ---------------------------------------------------------
# Music Assistant spielt synchron an den Lautsprecher und an diesen Empfänger; shairport-sync schreibt
# die Musik als Rohdaten auf seine Standardausgabe, die server.py liest. Schlägt etwas fehl, läuft die Show ohne Audio.
if bashio::config.true 'airplay'; then
  NAME="$(bashio::config 'airplay_name')"
  mkdir -p /run/dbus /var/run/dbus
  rm -f /run/dbus/dbus.pid /var/run/dbus/dbus.pid
  dbus-daemon --system || bashio::log.warning "dbus startet nicht"
  cat > /etc/avahi/avahi-daemon.conf <<CONF
[server]
host-name=lichtregie
use-ipv4=yes
use-ipv6=no
enable-dbus=yes
ratelimit-interval-usec=1000000
ratelimit-burst=1000
[publish]
publish-hinfo=no
publish-workstation=no
CONF
  avahi-daemon -D --no-chroot --no-drop-root || bashio::log.warning "avahi startet nicht"
  # Ausgang „stdout“: die Lichtregie startet shairport-sync selbst und liest den Ton direkt (keine Pipe-Datei;
  # die Pipe-Ausgabe von shairport-sync 5 lieferte keine Daten). Format fest, damit die Analyse passt.
  cat > /etc/shairport-sync.conf <<CONF
general = {
  name = "${NAME}";
  output_backend = "stdout";
  mdns_backend = "avahi";
  port = 5123;
  udp_port_base = 6101;
  ignore_volume_control = "yes";
  interpolation = "basic";
};
stdout = {
  output_format = "S16_LE";
  output_rate = 44100;
  output_channels = 2;
};
metadata = {
  enabled = "yes";
  include_cover_art = "no";
  pipe_name = "/tmp/shairport-sync-metadata";
  progress_interval = 1.0;
};
diagnostics = {
  log_verbosity = 1;
};
CONF
  # Metadaten (Titel, Position im Lied) über eine Pipe, die die Lichtregie mitliest (airplay.py)
  rm -f /tmp/shairport-sync-metadata && mkfifo /tmp/shairport-sync-metadata
  export LICHTREGIE_AIRPLAY_META=/tmp/shairport-sync-metadata
  export LICHTREGIE_AUDIO_CMD="shairport-sync -c /etc/shairport-sync.conf"
  bashio::log.info "AirPlay-Empfänger \"${NAME}\" gestartet"
fi

cd /app
exec python3 -u server.py
