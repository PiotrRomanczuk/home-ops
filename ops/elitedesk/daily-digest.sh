#!/usr/bin/env bash
# daily-digest.sh — fetch the digest model, render it, send it.
#
#   1. GET /api/digest?mode=… from the ingest API (one JSON model: verdict,
#      open decisions with signed links, problems, hosts, sites, today's
#      focus, routine cards, narrative). All the querying lives in the API.
#   2. Append legacy digest.d/*.txt cards that are still fresh (< 26 h).
#      Routines should move to POST /api/cards; stale files are skipped so a
#      months-old text file can no longer pose as today's news.
#   3. render-digest.py turns the model into email-safe HTML.
#   4. send-digest.py (stdlib smtplib) or msmtp sends it.
#
# The evening run no longer queues an overnight LLM job: the win10 GPU lane
# was switched off on 2026-07-16 and every queued job just piled up.
#
# Invoked by daily-digest.timer (07:00) and daily-digest-evening.timer (21:00).
# --dry-run prints the HTML to stdout instead of sending.
# Config: ops/elitedesk/daily-digest.env (see daily-digest.env.example).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
[[ -f "${SCRIPT_DIR}/daily-digest.env" ]] && source "${SCRIPT_DIR}/daily-digest.env"

# The ingest URL + token: reuse the watcher's env file unless overridden.
DIGEST_API_ENV="${DIGEST_API_ENV:-$HOME/.config/elitedesk-watcher.env}"
if [[ -z "${INGEST_URL:-}" || -z "${INGEST_TOKEN:-}" ]] && [[ -f "$DIGEST_API_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$DIGEST_API_ENV"
fi
API_BASE="${INGEST_URL%/api/ingest}"
DIGEST_TO="${DIGEST_TO:-}"
DIGEST_FROM="${DIGEST_FROM:-}"
DIGEST_SUBJECT_PREFIX="${DIGEST_SUBJECT_PREFIX:-[home-ops]}"
DIGEST_BOARD_URL="${DIGEST_BOARD_URL:-}"
DIGEST_TRANSPORT="${DIGEST_TRANSPORT:-smtplib}"
MSMTP_ACCOUNT="${MSMTP_ACCOUNT:-default}"
SMTP_PASS_FILE="${SMTP_PASS_FILE:-$HOME/.config/home-ops/smtp.pass}"
EXTRA_MAX_AGE_MIN="${EXTRA_MAX_AGE_MIN:-1560}"   # 26 h

MODE=morning
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)       DRY_RUN=1 ;;
    --mode)          shift; MODE="${1:-morning}" ;;
    --mode=*)        MODE="${1#*=}" ;;
    morning|evening) MODE="$1" ;;
    *) printf 'unknown argument: %s (use --mode morning|evening, --dry-run)\n' "$1" >&2; exit 1 ;;
  esac
  shift
done
[[ "$MODE" == morning || "$MODE" == evening ]] || { printf 'bad --mode: %s\n' "$MODE" >&2; exit 1; }
[[ -n "${INGEST_URL:-}" && -n "${INGEST_TOKEN:-}" ]] || {
  printf 'INGEST_URL / INGEST_TOKEN not set (looked in %s)\n' "$DIGEST_API_ENV" >&2; exit 1; }
if [[ "$DRY_RUN" -eq 0 && ( -z "$DIGEST_TO" || -z "$DIGEST_FROM" ) ]]; then
  printf 'DIGEST_TO and DIGEST_FROM must be set (see daily-digest.env.example)\n' >&2; exit 1
fi

# --- 1. the model -------------------------------------------------------------
MODEL="$(curl -fsS --max-time 30 -H "X-Ingest-Token: ${INGEST_TOKEN}" \
  "${API_BASE}/api/digest?mode=${MODE}")" || {
  printf 'could not fetch %s/api/digest — is the ingest container up?\n' "$API_BASE" >&2; exit 1; }

# --- 2. fresh legacy extras + board link, merged into the model ----------------
EXTRAS_DIR="${SCRIPT_DIR}/digest.d"
MODEL="$(printf '%s' "$MODEL" | BOARD_URL="$DIGEST_BOARD_URL" EXTRAS_DIR="$EXTRAS_DIR" \
  MAX_AGE_MIN="$EXTRA_MAX_AGE_MIN" python3 -c '
import json, os, sys, time, pathlib
m = json.load(sys.stdin)
m["board_url"] = os.environ.get("BOARD_URL") or None
extras, d = [], pathlib.Path(os.environ["EXTRAS_DIR"])
limit = time.time() - int(os.environ["MAX_AGE_MIN"]) * 60
for f in sorted(d.glob("*.txt")) if d.is_dir() else []:
    text = f.read_text(errors="replace").strip()
    if text and f.stat().st_mtime >= limit:
        extras.append({"name": f.stem.replace("-", " "), "text": text[:4000]})
m["extras"] = extras
json.dump(m, sys.stdout)
')"

# --- 3. render ----------------------------------------------------------------
HTML="$(printf '%s' "$MODEL" | python3 "${SCRIPT_DIR}/render-digest.py")"
VERDICT="$(printf '%s' "$MODEL" | python3 -c 'import json,sys; print(json.load(sys.stdin)["verdict"])')"
SUBJECT="$(printf '%.140s' "${DIGEST_SUBJECT_PREFIX} ${VERDICT}")"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '%s\n' "$HTML"
  printf -- '--- dry run: not sent · subject: %s\n' "$SUBJECT" >&2
  exit 0
fi

# --- 4. send ------------------------------------------------------------------
case "$DIGEST_TRANSPORT" in
  smtplib)
    printf '%s' "$HTML" | MAIL_FROM="$DIGEST_FROM" MAIL_TO="$DIGEST_TO" MAIL_SUBJECT="$SUBJECT" \
      SMTP_PASS_FILE="$SMTP_PASS_FILE" python3 "${SCRIPT_DIR}/send-digest.py" ;;
  msmtp)
    printf 'From: %s\nTo: %s\nSubject: %s\nMIME-Version: 1.0\nContent-Type: text/html; charset=utf-8\n\n%s\n' \
      "$DIGEST_FROM" "$DIGEST_TO" "$SUBJECT" "$HTML" | msmtp -a "$MSMTP_ACCOUNT" "$DIGEST_TO"
    printf 'digest sent to %s\n' "$DIGEST_TO" ;;
  *) printf 'unknown DIGEST_TRANSPORT: %s\n' "$DIGEST_TRANSPORT" >&2; exit 1 ;;
esac
