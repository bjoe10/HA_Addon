#!/bin/sh
set -eu

OPTIONS_FILE="${OPTIONS_FILE:-/data/options.json}"
S6_INIT="${S6_INIT:-/init}"

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

[ -r "$OPTIONS_FILE" ] || fail "Home Assistant options file not readable: $OPTIONS_FILE"
command -v jq >/dev/null 2>&1 || fail "jq is required to read add-on options"

EXTERNAL_HOST="$(jq -r '.external_host // empty' "$OPTIONS_FILE")"
API_URL="$(jq -r '.api_url // empty' "$OPTIONS_FILE")"
ENCRYPTED_ONLY="$(jq -r 'if .encrypted_only == true then "1" else "0" end' "$OPTIONS_FILE")"
MUST_LOGIN="$(jq -r 'if .must_login == true then "Y" else "N" end' "$OPTIONS_FILE")"
ALLOW_REGISTRATION="$(jq -r 'if .allow_registration == true then "true" else "false" end' "$OPTIONS_FILE")"
JWT_KEY="$(jq -r '.jwt_key // empty' "$OPTIONS_FILE")"

[ -n "$EXTERNAL_HOST" ] || fail "external_host is required (DNS name or IPv4, without scheme or port)"
case "$EXTERNAL_HOST" in
    *[!A-Za-z0-9.-]*) fail "external_host may contain only letters, digits, dots and hyphens" ;;
esac
case "$EXTERNAL_HOST" in
    -*|*-) fail "external_host must not start or end with a hyphen" ;;
esac

[ -n "$API_URL" ] || fail "api_url is required (for example https://rustdesk.example.com)"
case "$API_URL" in
    http://*|https://*) ;;
    *) fail "api_url must start with http:// or https://" ;;
esac
case "$API_URL" in
    *[[:space:]]*) fail "api_url must not contain whitespace" ;;
esac
API_URL="${API_URL%/}"
API_AUTHORITY="${API_URL#*://}"
case "$API_AUTHORITY" in
    ""|/*|*/*|*\?*|*\#*) fail "api_url must be an origin (scheme://host[:port]), without a path, query or fragment" ;;
esac

if [ "$MUST_LOGIN" = "Y" ] && [ -z "$JWT_KEY" ]; then
    fail "jwt_key is required when must_login is enabled; generate one with: openssl rand -hex 32"
fi

export TZ="${TZ:-Europe/Berlin}"
export RELAY="${EXTERNAL_HOST}:21117"
export ENCRYPTED_ONLY
export MUST_LOGIN
export RUSTDESK_API_LANG="en"
export RUSTDESK_API_APP_WEB_CLIENT="1"
export RUSTDESK_API_APP_REGISTER="$ALLOW_REGISTRATION"
export RUSTDESK_API_RUSTDESK_ID_SERVER="${EXTERNAL_HOST}:21116"
export RUSTDESK_API_RUSTDESK_RELAY_SERVER="${EXTERNAL_HOST}:21117"
export RUSTDESK_API_RUSTDESK_API_SERVER="$API_URL"
export RUSTDESK_API_RUSTDESK_KEY_FILE="/data/id_ed25519.pub"
export RUSTDESK_API_JWT_KEY="$JWT_KEY"

printf 'Starting RustDesk Server + API\n'
printf 'External RustDesk host: %s\n' "$EXTERNAL_HOST"
printf 'API URL: %s\n' "$API_URL"
printf 'Encrypted-only mode: %s\n' "$ENCRYPTED_ONLY"
printf 'Login required for RustDesk connections: %s\n' "$MUST_LOGIN"
printf 'User registration enabled: %s\n' "$ALLOW_REGISTRATION"

exec "$S6_INIT"
