#!/bin/bash
# run.sh <script.py> [args…] — launchd entry point for the Mac agents.
#
# launchd starts jobs with a bare environment, so this wrapper supplies what a
# systemd EnvironmentFile would on Linux:
#   * INGEST_TOKEN from the login Keychain (item "home-ops-ingest") — never in
#     a file or a plist;
#   * INGEST_URL over the LAN when the Mac is home, else INGEST_FALLBACK_URL
#     (elitedesk's Tailscale address — kept in ~/.config/home-ops/mac.env, not
#     in this public repo); mac-watcher re-checks the network every sample;
#   * overrides from ~/.config/home-ops/mac.env (INGEST_FALLBACK_URL, SHIP=0, …);
#   * psutil through uv (no system-wide pip install).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="${1:?usage: run.sh <script.py> [args…]}"
shift

export HOST_NAME=mac
if [ -f "$HOME/.config/home-ops/mac.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$HOME/.config/home-ops/mac.env"
  set +a
fi
LAN_URL="http://192.168.1.75:64421/api/ingest"
export INGEST_FALLBACK_URL="${INGEST_FALLBACK_URL:-$LAN_URL}"
if ifconfig 2>/dev/null | grep -qE 'inet 192\.168\.1\.'; then
  export INGEST_URL="${INGEST_URL:-$LAN_URL}"
else
  export INGEST_URL="${INGEST_URL:-$INGEST_FALLBACK_URL}"
fi
INGEST_TOKEN="$(security find-generic-password -s home-ops-ingest -a mac -w 2>/dev/null || true)"
export INGEST_TOKEN

exec /opt/homebrew/bin/uv run --quiet --no-project --with psutil python3 "$DIR/$SCRIPT" "$@"
