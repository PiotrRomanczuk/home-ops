#!/usr/bin/env bash
# notify-failure.sh <unit> — e-mail when a home-ops unit ends in "failed".
#
# Run by unit-failure-mail@.service (OnFailure= in the units). Same transport
# and recipient as the daily digest (daily-digest.env + send-digest.py).
#
# The mail answers, in this order: what failed and why (in words), when it
# last worked and when it runs next, what to do — then the log of the FAILED
# RUN ONLY (by InvocationID; the old "last 40 lines" mixed in earlier,
# successful runs of the same day).
#
# Per-unit context: an executable ~/.config/home-ops/failure-hints/<unit>.sh
# prints extra plain text (e.g. the unit's own report) shown under "Kontekst";
# it receives FAILED_DAY (YYYY-MM-DD of the failed run).
# DRY_RUN=1 prints the HTML instead of sending it.
set -euo pipefail

UNIT="${1:?usage: notify-failure.sh <unit>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
[[ -f "${SCRIPT_DIR}/daily-digest.env" ]] && source "${SCRIPT_DIR}/daily-digest.env"
HOST="${HOST_NAME:-elitedesk}"   # the name agents log under, not the OS hostname
HINT="${FAILURE_HINT_DIR:-$HOME/.config/home-ops/failure-hints}/${UNIT}.sh"

show() { systemctl --user show "$UNIT" -p "$1" --value 2>/dev/null || true; }
esc() { python3 -c 'import html,sys; print(html.escape(sys.stdin.read()), end="")'; }
NAME="${UNIT%.service}"
DESC="$(show Description)"
CODE="$(show ExecMainStatus)"
STARTED="$(show ExecMainStartTimestamp)"
ENDED="$(show ExecMainExitTimestamp)"
INVOCATION="$(show InvocationID)"

# Only this run's lines; fall back to the tail when the ID is unknown.
RUNLOG=""
[[ -n "$INVOCATION" ]] &&
  RUNLOG="$(journalctl --user _SYSTEMD_INVOCATION_ID="$INVOCATION" --no-pager -o cat 2>/dev/null | tail -n 60 || true)"
[[ -n "$RUNLOG" ]] || RUNLOG="$(journalctl --user -u "$UNIT" -n 40 --no-pager -o short-iso 2>&1 || true)"

# The reason = the program's own last words, minus systemd's bookkeeping.
REASON="$(printf '%s\n' "$RUNLOG" |
  grep -vE '^(Starting|Started|Finished|Failed to start|.*: (Main process exited|Failed with result|Consumed|Triggering OnFailure))' |
  grep -vE '^\s*(#.*)?$|^STATUS:' | tail -n 3 || true)"
[[ -n "$REASON" ]] || REASON="Proces zakończył się kodem ${CODE:-?} bez komunikatu."
SHORT="$(printf '%s' "$REASON" | tail -n 1 |
  sed -E 's/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+([+-][0-9:]+|Z)? //; s/ — log: .*//' | cut -c1-80)"

LAST_OK="$(journalctl --user -u "$UNIT" --no-pager -o short-iso 2>/dev/null |
  grep -E ' Finished ' | tail -n 1 | cut -d' ' -f1 | sed 's/T/ /; s/+.*//' || true)"
NEXT=""
systemctl --user cat "${NAME}.timer" >/dev/null 2>&1 &&
  NEXT="$(systemctl --user list-timers --no-legend "${NAME}.timer" 2>/dev/null | awk '{print $1, $2, $3}')"

CONTEXT=""
# Hints get the failed run's date: a mail read (or re-sent) after midnight
# must still point at that day's report.
FAILED_DAY="$(date -d "$(printf '%s' "$ENDED" | sed -E 's/^[A-Za-z]{3} //')" +%F 2>/dev/null || date +%F)"
[[ -x "$HINT" ]] && CONTEXT="$(FAILED_DAY="$FAILED_DAY" timeout 20 "$HINT" 2>&1 || true)"

row() { printf '<tr><td style="color:#6b6157;padding:2px 12px 2px 0">%s</td><td>%s</td></tr>' "$1" "$2"; }
HTML="<p style=\"font-size:15px\"><b>${NAME}</b> na <b>${HOST}</b> nie powiódł się.</p>
<p style=\"font-size:15px;background:#fbf1d3;padding:8px 12px;border-radius:6px\">$(printf '%s' "$REASON" | esc | sed 's/$/<br>/')</p>
<table style=\"font-size:13px\">
$(row 'Usługa' "$(printf '%s' "${DESC:-$UNIT}" | esc)")
$(row 'Przebieg' "$(printf '%s' "${STARTED:-?} → ${ENDED:-?} · kod ${CODE:-?}" | esc)")
$(row 'Ostatni udany' "${LAST_OK:-brak w dzienniku}")
$(row 'Następny' "${NEXT:-brak timera — tylko ręcznie}")
</table>
<p style=\"font-size:13px\"><b>Co zrobić:</b> przeczytaj przyczynę i kontekst poniżej. Jeśli to chwilowe, poczekaj na następny przebieg albo uruchom ręcznie: <code>systemctl --user start ${UNIT}</code>. Log: <code>journalctl --user -u ${UNIT} --since today</code></p>"
[[ -n "$CONTEXT" ]] && HTML+="<h4 style=\"margin-bottom:4px\">Kontekst</h4><pre style=\"font-size:12px;white-space:pre-wrap\">$(printf '%s' "$CONTEXT" | esc)</pre>"
HTML+="<h4 style=\"margin-bottom:4px\">Log tego przebiegu</h4><pre style=\"font-size:12px;white-space:pre-wrap;color:#4a4037\">$(printf '%s' "$RUNLOG" | esc)</pre>"

SUBJECT="[home-ops] ❌ ${NAME}: ${SHORT}"
if [[ "${DRY_RUN:-0}" = 1 ]]; then
  printf 'Subject: %s\n\n%s\n' "$SUBJECT" "$HTML"; exit 0
fi
: "${DIGEST_TO:?DIGEST_TO not set (daily-digest.env)}"
: "${DIGEST_FROM:?DIGEST_FROM not set (daily-digest.env)}"
printf '%s' "$HTML" | MAIL_FROM="$DIGEST_FROM" MAIL_TO="$DIGEST_TO" MAIL_SUBJECT="$SUBJECT" \
  SMTP_PASS_FILE="${SMTP_PASS_FILE:-$HOME/.config/home-ops/smtp.pass}" \
  python3 "${SCRIPT_DIR}/send-digest.py"
