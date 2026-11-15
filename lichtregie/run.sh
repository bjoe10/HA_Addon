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
export LICHTREGIE_GERAETE="$(bashio::config 'geraete')"
export LICHTREGIE_LASER_SWITCH="$(bashio::config 'laser_schalter')"
export LICHTREGIE_AIRPLAY_NAME="$(bashio::config 'airplay_name')"

# --- AirPlay-Empfänger für die Audioanalyse ---------------------------------------------------------
# Music Assistant spielt synchron an den Lautsprecher und an diesen Empfänger; shairport-sync schreibt
# die Musik als Rohdaten in eine Pipe, die server.py liest. Schlägt etwas fehl, läuft die Show ohne Audio.
PIPE=/tmp/lichtregie.pcm
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
  [ -p "$PIPE" ] || mkfifo "$PIPE"
  cat > /etc/shairport-sync.conf <<CONF
general = {
  name = "${NAME}";
  output_backend = "pipe";
  mdns_backend = "avahi";
  port = 5123;
  udp_port_base = 6101;
  ignore_volume_control = "yes";
  interpolation = "basic";
};
pipe = {
  name = "${PIPE}";
};
CONF
  shairport-sync -c /etc/shairport-sync.conf &
  export LICHTREGIE_AUDIO_PIPE="$PIPE"
  bashio::log.info "AirPlay-Empfänger \"${NAME}\" gestartet"
fi

cd /app
exec python3 -u server.py
