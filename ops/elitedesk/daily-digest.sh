#!/usr/bin/env bash
# daily-digest.sh — assemble and send the morning home-ops digest.
#
# What it does:
#   1. Runs daily-digest.sql inside the home-ops-postgres-1 container to build
#      the metrics/eval/errors body (read-only).
#   2. Pulls "Today's focus" + the full Next list from the projects table
#      (which planner-sync keeps in step with ~/Obsidian/MainCV-Planner/
#      projects/home-ops.md every 60s).
#   3. Lists the last 24h of commits from the repo clone.
#   4. Wraps it all in an HTML email and sends it via msmtp.
#
# Steering: to change tomorrow's "Today's focus", reorder/edit the `## Next`
# list in projects/home-ops.md in Obsidian. Nothing to change here.
#
# Invoked by ops/elitedesk/daily-digest.timer at 07:00 Europe/Warsaw.
# Run with --dry-run to print the message to stdout without sending.
#
# Config: ops/elitedesk/daily-digest.env (see daily-digest.env.example).
# Mail transport: msmtp — see ops/elitedesk/README.md for ~/.msmtprc setup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- config (env file overrides these defaults) ------------------------------
if [[ -f "${SCRIPT_DIR}/daily-digest.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/daily-digest.env"
fi

CONTAINER="${CONTAINER:-home-ops-postgres-1}"
DB="${DB:-home_ops}"
DB_USER="${DB_USER:-postgres}"
REPO_DIR="${REPO_DIR:-${HOME}/logs-stack}"
DIGEST_TO="${DIGEST_TO:-}"
DIGEST_FROM="${DIGEST_FROM:-}"
DIGEST_SUBJECT_PREFIX="${DIGEST_SUBJECT_PREFIX:-[home-ops]}"

# Transport: 'smtplib' (Python stdlib, no install/sudo — default) or 'msmtp'.
DIGEST_TRANSPORT="${DIGEST_TRANSPORT:-smtplib}"
MSMTP_ACCOUNT="${MSMTP_ACCOUNT:-default}"
SMTP_HOST="${SMTP_HOST:-smtp.gmail.com}"
SMTP_PORT="${SMTP_PORT:-587}"
SMTP_USER="${SMTP_USER:-$DIGEST_FROM}"
SMTP_PASS_FILE="${SMTP_PASS_FILE:-$HOME/.config/home-ops/smtp.pass}"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

if [[ "$DRY_RUN" -eq 0 ]]; then
  if [[ -z "$DIGEST_TO" || -z "$DIGEST_FROM" ]]; then
    printf 'DIGEST_TO and DIGEST_FROM must be set (see daily-digest.env.example)\n' >&2
    exit 1
  fi
  case "$DIGEST_TRANSPORT" in
    smtplib)
      command -v python3 >/dev/null 2>&1 || {
        printf 'python3 not found (needed for smtplib transport)\n' >&2; exit 1; }
      [[ -f "$SMTP_PASS_FILE" ]] || {
        printf 'app-password file missing: %s — see ops/elitedesk/README.md\n' \
          "$SMTP_PASS_FILE" >&2; exit 1; }
      ;;
    msmtp)
      command -v msmtp >/dev/null 2>&1 || {
        printf 'msmtp not installed. See ops/elitedesk/README.md.\n' >&2; exit 1; }
      ;;
    *)
      printf 'unknown DIGEST_TRANSPORT: %s (use smtplib or msmtp)\n' \
        "$DIGEST_TRANSPORT" >&2; exit 1 ;;
  esac
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  printf 'container %s is not running\n' "$CONTAINER" >&2
  exit 1
fi

# --- helper: run a single read-only query, return the raw value --------------
psql_val() {
  docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB" -X -q -t -A -c "$1"
}

TODAY="$(date +%Y-%m-%d)"

# --- Today's focus: first unchecked item of the Next list --------------------
FOCUS="$(psql_val "
  SELECT regexp_replace(
           regexp_replace(split_part(next_md, E'\n', 1), '^- \[[ xX]\] ', ''),
           '\*\*', '', 'g')
  FROM projects WHERE slug = 'home-ops';" || true)"
[[ -z "$FOCUS" ]] && FOCUS="(no Next items — add one to projects/home-ops.md)"

NEXT_LIST="$(psql_val "SELECT coalesce(next_md, '(none)') FROM projects WHERE slug='home-ops';" || true)"
NOW_LIST="$(psql_val "SELECT coalesce(now_md, '(none)') FROM projects WHERE slug='home-ops';" || true)"

# --- Digest body from SQL ----------------------------------------------------
BODY="$(docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB" -X -q < "${SCRIPT_DIR}/daily-digest.sql")"

# --- Commits in the last 24h -------------------------------------------------
if [[ -d "${REPO_DIR}/.git" ]]; then
  COMMITS="$(git -C "$REPO_DIR" log --since='24 hours ago' --pretty='  %h %s' 2>/dev/null || true)"
  [[ -z "$COMMITS" ]] && COMMITS="  (no commits in last 24h)"
else
  COMMITS="  (repo clone not found at ${REPO_DIR})"
fi

# --- HTML escaping for the pre-formatted blocks ------------------------------
esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

BODY_H="$(printf '%s' "$BODY"       | esc)"
NOW_H="$(printf '%s' "$NOW_LIST"    | esc)"
NEXT_H="$(printf '%s' "$NEXT_LIST"  | esc)"
COMMITS_H="$(printf '%s' "$COMMITS" | esc)"
FOCUS_H="$(printf '%s' "$FOCUS"     | esc)"

# --- Compose the email -------------------------------------------------------
SUBJECT="${DIGEST_SUBJECT_PREFIX} daily digest · ${TODAY} · ${FOCUS}"
# Keep the subject to a sane length.
SUBJECT="$(printf '%.140s' "$SUBJECT")"

read -r -d '' HTML <<HTMLDOC || true
<!doctype html><html><body style="margin:0;background:#0d1117;padding:20px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace">
<div style="max-width:720px;margin:0 auto;background:#161b22;border:1px solid #30363d;border-radius:10px;overflow:hidden">
  <div style="background:#1f6feb;color:#fff;padding:16px 22px">
    <div style="font-size:12px;letter-spacing:.08em;opacity:.85">HOME-OPS · ${TODAY}</div>
    <div style="font-size:20px;font-weight:700;margin-top:2px">Morning digest</div>
  </div>
  <div style="padding:18px 22px 8px">
    <div style="font-size:11px;letter-spacing:.08em;color:#8b949e">🎯 TODAY'S FOCUS</div>
    <div style="font-size:16px;color:#e6edf3;font-weight:600;margin:6px 0 4px">${FOCUS_H}</div>
    <div style="font-size:12px;color:#8b949e">top of the Next list — edit projects/home-ops.md in Obsidian to change it</div>
  </div>
  <div style="padding:8px 22px 4px"><div style="font-size:11px;letter-spacing:.08em;color:#8b949e">NEXT (planned)</div>
    <pre style="color:#c9d1d9;font-size:12.5px;line-height:1.5;white-space:pre-wrap;margin:6px 0">${NEXT_H}</pre></div>
  <div style="padding:4px 22px"><div style="font-size:11px;letter-spacing:.08em;color:#8b949e">NOW (in progress)</div>
    <pre style="color:#c9d1d9;font-size:12.5px;line-height:1.5;white-space:pre-wrap;margin:6px 0">${NOW_H}</pre></div>
  <div style="padding:4px 22px"><div style="font-size:11px;letter-spacing:.08em;color:#8b949e">STACK STATUS</div>
    <pre style="color:#c9d1d9;font-size:12.5px;line-height:1.45;white-space:pre-wrap;margin:6px 0">${BODY_H}</pre></div>
  <div style="padding:4px 22px 18px"><div style="font-size:11px;letter-spacing:.08em;color:#8b949e">COMMITS (24h)</div>
    <pre style="color:#c9d1d9;font-size:12.5px;line-height:1.5;white-space:pre-wrap;margin:6px 0">${COMMITS_H}</pre></div>
  <div style="background:#0d1117;color:#6e7681;padding:12px 22px;font-size:11px;border-top:1px solid #30363d">
    Generated by ops/elitedesk/daily-digest.sh · steer tomorrow by editing the Next list in Obsidian
  </div>
</div></body></html>
HTMLDOC

MESSAGE="$(cat <<MSG
From: ${DIGEST_FROM}
To: ${DIGEST_TO}
Subject: ${SUBJECT}
MIME-Version: 1.0
Content-Type: text/html; charset=utf-8

${HTML}
MSG
)"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '%s\n' "$MESSAGE"
  printf '\n--- dry run: not sent (transport=%s) ---\n' "$DIGEST_TRANSPORT" >&2
  exit 0
fi

case "$DIGEST_TRANSPORT" in
  smtplib)
    printf '%s' "$HTML" | \
      MAIL_FROM="$DIGEST_FROM" MAIL_TO="$DIGEST_TO" MAIL_SUBJECT="$SUBJECT" \
      SMTP_HOST="$SMTP_HOST" SMTP_PORT="$SMTP_PORT" SMTP_USER="$SMTP_USER" \
      SMTP_PASS_FILE="$SMTP_PASS_FILE" \
      python3 "${SCRIPT_DIR}/send-digest.py"
    ;;
  msmtp)
    printf '%s\n' "$MESSAGE" | msmtp -a "$MSMTP_ACCOUNT" "$DIGEST_TO"
    printf 'digest sent to %s\n' "$DIGEST_TO"
    ;;
esac
