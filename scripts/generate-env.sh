#!/usr/bin/env bash
# Generates ./.env for the home-ops stack.
#
# - POSTGRES_PASSWORD: 48 hex chars (24 random bytes)
# - INGEST_TOKEN:      64 hex chars (32 random bytes)
# - LOGS_PASSWORD:     prompted interactively (you type this on your phone)
#
# Writes ./.env with mode 0600. Refuses to clobber an existing .env unless
# --force is passed. Prints the INGEST_TOKEN at the end so you can mirror
# it into the per-host agent env files.

set -euo pipefail

target=".env"
force=0
for arg in "$@"; do
  case "$arg" in
    --force) force=1 ;;
    -h|--help)
      sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) printf 'unknown arg: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

if [[ -e "$target" && $force -eq 0 ]]; then
  printf 'refusing to overwrite existing %s (pass --force to override)\n' "$target" >&2
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  printf 'openssl is required but not on PATH\n' >&2
  exit 1
fi

postgres_password=$(openssl rand -hex 24)
ingest_token=$(openssl rand -hex 32)

printf 'LOGS_PASSWORD (the viewer login you will type from your phone): '
read -r -s logs_password
printf '\n'

if [[ -z "$logs_password" ]]; then
  printf 'LOGS_PASSWORD cannot be empty\n' >&2
  exit 1
fi

umask 077
{
  printf '# home-ops stack — generated %s by scripts/generate-env.sh\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'POSTGRES_PASSWORD=%s\n' "$postgres_password"
  printf 'INGEST_TOKEN=%s\n'      "$ingest_token"
  printf 'LOGS_PASSWORD=%s\n'     "$logs_password"
} > "$target"
chmod 600 "$target"

cat <<MSG

Wrote $target (mode 0600).

Mirror INGEST_TOKEN into the per-host agent env files:
  elitedesk: ~/.config/elitedesk-watcher.env
  win10: C:\\ProgramData\\OllamaWatcher\\watcher.env
  win10: C:\\ProgramData\\GpuScheduler\\scheduler.env
  rpi: ~/.config/rpi-watcher.env  (Phase E)

INGEST_TOKEN=$ingest_token
MSG
