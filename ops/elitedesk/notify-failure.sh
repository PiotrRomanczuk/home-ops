#!/usr/bin/env bash
# notify-failure.sh <unit> — e-mail when a home-ops unit ends in "failed".
#
# Run by unit-failure-mail@.service (OnFailure= in the units). Same transport
# and recipient as the daily digest (daily-digest.env + send-digest.py), so no
# new credentials. Body = last 40 journal lines of the failed unit.
set -euo pipefail

UNIT="${1:?usage: notify-failure.sh <unit>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
[[ -f "${SCRIPT_DIR}/daily-digest.env" ]] && source "${SCRIPT_DIR}/daily-digest.env"
: "${DIGEST_TO:?DIGEST_TO not set (daily-digest.env)}"
: "${DIGEST_FROM:?DIGEST_FROM not set (daily-digest.env)}"

# Same name the agents log under (elitedesk), not the OS hostname — the
# console groups per host, and three spellings of one box read as three hosts.
HOST="${HOST_NAME:-elitedesk}"
LOG="$(journalctl --user -u "$UNIT" -n 40 --no-pager -o short-iso 2>&1 || true)"
ESCAPED="$(printf '%s' "$LOG" | python3 -c 'import html,sys; print(html.escape(sys.stdin.read()))')"
HTML="<p><b>${UNIT}</b> na <b>${HOST}</b> zakończył się błędem ($(date '+%F %T')).</p>
<p>Ponów: <code>systemctl --user start ${UNIT}</code></p><pre>${ESCAPED}</pre>"

printf '%s' "$HTML" | MAIL_FROM="$DIGEST_FROM" MAIL_TO="$DIGEST_TO" \
  MAIL_SUBJECT="[home-ops] ❌ ${UNIT} — błąd na ${HOST}" \
  SMTP_PASS_FILE="${SMTP_PASS_FILE:-$HOME/.config/home-ops/smtp.pass}" \
  python3 "${SCRIPT_DIR}/send-digest.py"
