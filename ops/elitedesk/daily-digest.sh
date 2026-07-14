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
# Console board URL (LAN/Tailscale), e.g. http://elitedesk:64421/#tab=board.
# When set, the email links to the interactive Board tab.
DIGEST_BOARD_URL="${DIGEST_BOARD_URL:-}"

# Transport: 'smtplib' (Python stdlib, no install/sudo — default) or 'msmtp'.
DIGEST_TRANSPORT="${DIGEST_TRANSPORT:-smtplib}"
MSMTP_ACCOUNT="${MSMTP_ACCOUNT:-default}"
SMTP_HOST="${SMTP_HOST:-smtp.gmail.com}"
SMTP_PORT="${SMTP_PORT:-587}"
SMTP_USER="${SMTP_USER:-$DIGEST_FROM}"
SMTP_PASS_FILE="${SMTP_PASS_FILE:-$HOME/.config/home-ops/smtp.pass}"

# Mode: 'morning' (default — the overnight LLM narrative + planner focus) or
# 'evening' (end-of-day snapshot that also queues the overnight narrative job).
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
if [[ "$MODE" != morning && "$MODE" != evening ]]; then
  printf 'bad --mode: %s (use morning or evening)\n' "$MODE" >&2; exit 1
fi

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

# --- Today's focus: the pinned Board card, else the top unchecked Next item ---
FOCUS="$(psql_val "SELECT regexp_replace(text, '\*\*', '', 'g')
  FROM board_tasks WHERE slug='home-ops' AND is_focus LIMIT 1;" 2>/dev/null || true)"
if [[ -z "$FOCUS" ]]; then
  FOCUS="$(psql_val "
    SELECT regexp_replace(
             regexp_replace(split_part(next_md, E'\n', 1), '^- \[[ xX]\] ', ''),
             '\*\*', '', 'g')
    FROM projects WHERE slug = 'home-ops';" 2>/dev/null || true)"
fi
[[ -z "$FOCUS" ]] && FOCUS="(no focus pinned — pin one on the Board tab)"

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

# --- At-a-glance scalars for the stat strip ----------------------------------
STAT_HOSTS_OK="$(psql_val "SELECT count(*) FILTER (WHERE ts > now()-interval '5 minutes') FROM (SELECT DISTINCT ON (host) host, ts FROM host_metrics WHERE ts > now()-interval '2 days' ORDER BY host, ts DESC) x;" 2>/dev/null || echo 0)"
STAT_HOSTS_TOTAL="$(psql_val "SELECT count(DISTINCT host) FROM host_metrics WHERE ts > now()-interval '2 days';" 2>/dev/null || echo 0)"
STAT_ERRORS="$(psql_val "SELECT count(*) FROM host_logs WHERE level IN ('error','fatal') AND ts > now()-interval '1 day';" 2>/dev/null || echo 0)"
STAT_FATAL="$(psql_val "SELECT count(*) FROM host_logs WHERE level='fatal' AND ts > now()-interval '1 day';" 2>/dev/null || echo 0)"
STAT_EVALAGE="$(psql_val "SELECT coalesce(extract(day from now()-max(scored_at))::int::text || 'd', '—') FROM eval_scores;" 2>/dev/null || echo '—')"
STAT_GPUQ="$(psql_val "SELECT count(*) FROM gpu_jobs WHERE status='queued';" 2>/dev/null || echo 0)"

# Colour tokens (GitHub-dark palette)
GREEN='#3fb950'; RED='#f85149'; AMBER='#d29922'; ORANGE='#ff9d4d'; BLUE='#58a6ff'
c_hosts=$([[ "$STAT_HOSTS_OK" == "$STAT_HOSTS_TOTAL" && "$STAT_HOSTS_TOTAL" -gt 0 ]] && echo "$GREEN" || echo "$RED")
c_err=$([[ "${STAT_ERRORS:-0}" -gt 0 ]] && echo "$AMBER" || echo "$GREEN")
c_fatal=$([[ "${STAT_FATAL:-0}" -gt 0 ]] && echo "$RED" || echo "$GREEN")
age_n="${STAT_EVALAGE%%d*}"; [[ "$age_n" =~ ^[0-9]+$ ]] || age_n=99
c_eval=$([[ "$age_n" -le 2 ]] && echo "$GREEN" || echo "$AMBER")
STATUS_LINE="${STAT_HOSTS_OK}/${STAT_HOSTS_TOTAL} hosts up · ${STAT_ERRORS:-0} errors · ${STAT_FATAL:-0} fatal (24h) · eval ${STAT_EVALAGE} · gpu queue ${STAT_GPUQ:-0}"

# --- HTML escaping + colourising for the pre-formatted blocks -----------------
esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
# Colourise severity / health keywords and section rules inside the status block.
colourise() {
  sed -E \
    -e "s@(── [^─]* ─+)@<span style=\"color:${BLUE};font-weight:700\">\1</span>@g" \
    -e "s@⚠ SILENT@<span style=\"color:${RED};font-weight:700\">⚠ SILENT</span>@g" \
    -e "s@\bfatal\b@<span style=\"color:${RED};font-weight:600\">fatal</span>@g" \
    -e "s@\berror\b@<span style=\"color:${ORANGE}\">error</span>@g" \
    -e "s@\bwarn\b@<span style=\"color:${AMBER}\">warn</span>@g" \
    -e "s@\bok\b@<span style=\"color:${GREEN}\">ok</span>@g"
}
# Turn markdown checkboxes/bold/code into tidy styling for the Next/Now lists.
listfmt() {
  sed -E -e "s@- \[[xX]\]@<span style=\"color:${GREEN}\">✓</span>@g" \
         -e "s@- \[ \]@<span style=\"color:#6e7681\">•</span>@g" \
         -e "s@\*\*([^*]+)\*\*@<b style=\"color:#e6edf3\">\1</b>@g" \
         -e "s@\`([^\`]+)\`@<span style=\"color:#79c0ff\">\1</span>@g"
}

BODY_H="$(printf '%s' "$BODY"       | esc | colourise)"
NOW_H="$(printf '%s' "$NOW_LIST"    | esc | listfmt)"
NEXT_H="$(printf '%s' "$NEXT_LIST"  | esc | listfmt)"
COMMITS_H="$(printf '%s' "$COMMITS" | esc)"
FOCUS_H="$(printf '%s' "$FOCUS"     | esc)"

# --- Compose the email -------------------------------------------------------
if [[ "$MODE" == evening ]]; then
  SUBJECT="${DIGEST_SUBJECT_PREFIX} ${TODAY} evening · ${STAT_HOSTS_OK}/${STAT_HOSTS_TOTAL} up · ${STAT_ERRORS:-0} err"
else
  SUBJECT="${DIGEST_SUBJECT_PREFIX} ${TODAY} · ${STAT_HOSTS_OK}/${STAT_HOSTS_TOTAL} up · ${STAT_ERRORS:-0} err · ${FOCUS}"
fi
SUBJECT="$(printf '%.140s' "$SUBJECT")"

SANS="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

# One reusable stat tile: $1 value, $2 label, $3 colour.
tile() { printf '<td width="20%%" valign="top" style="padding:3px"><div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:11px 4px;text-align:center"><div style="font-size:20px;font-weight:700;color:%s;font-family:%s">%s</div><div style="font-size:9px;letter-spacing:.04em;color:#8b949e;margin-top:3px;text-transform:uppercase">%s</div></div></td>' "$3" "$MONO" "$1" "$2"; }
TILES="$(tile "${STAT_HOSTS_OK}/${STAT_HOSTS_TOTAL}" "hosts up" "$c_hosts")$(tile "${STAT_ERRORS:-0}" "errors 24h" "$c_err")$(tile "${STAT_FATAL:-0}" "fatal 24h" "$c_fatal")$(tile "${STAT_EVALAGE}" "eval age" "$c_eval")$(tile "${STAT_GPUQ:-0}" "gpu queued" "$BLUE")"

PRE="margin:0;color:#c9d1d9;font-size:12.5px;line-height:1.5;white-space:pre-wrap;font-family:${MONO}"
LBL="font-size:10.5px;letter-spacing:.08em;color:${BLUE};text-transform:uppercase;font-weight:700;margin-bottom:8px"
CARD="margin:14px 22px;background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:13px 15px"

# "Open board" button + caption, only when a console URL is configured.
if [[ -n "$DIGEST_BOARD_URL" ]]; then
  BOARD_BTN="<a href=\"${DIGEST_BOARD_URL}\" style=\"display:inline-block;margin-top:9px;background:#1f6feb;color:#fff;text-decoration:none;font-size:12px;font-weight:600;padding:6px 13px;border-radius:6px\">Open board →</a>"
  FOCUS_CAPTION="pinned on the Board tab — drag cards or pin a new focus to change it"
else
  BOARD_BTN=""
  FOCUS_CAPTION="pin a card as Today's focus on the Board tab to change it"
fi

# --- mode-specific header + overnight narrative card ------------------------
if [[ "$MODE" == morning ]]; then
  HEADER_TITLE="Morning digest"
  # The overnight LLM narrative: latest completed night-digest summarise job,
  # queued by yesterday evening's run and generated on the game-free GPU.
  NARRATIVE="$(psql_val "
    SELECT left(result->>'summary', 6000)
    FROM gpu_jobs
    WHERE kind='summarise'
      AND payload->>'conversation_id' LIKE 'night-digest-%'
      AND status='done' AND result ? 'summary' AND (result->>'summary') <> ''
      AND created_at > now() - interval '18 hours'
    ORDER BY created_at DESC LIMIT 1;" 2>/dev/null || true)"
  if [[ -n "$NARRATIVE" ]]; then
    NARRATIVE_H="$(printf '%s' "$NARRATIVE" | esc)"
    NARRATIVE_CARD="<div style=\"margin:16px 22px 4px;background:#12261a;border-left:3px solid ${GREEN};border-radius:6px;padding:13px 16px\"><div style=\"font-size:10.5px;letter-spacing:.08em;color:${GREEN};text-transform:uppercase;font-weight:700\">🌙 Overnight narrative</div><pre style=\"${PRE};margin-top:8px\">${NARRATIVE_H}</pre></div>"
  else
    NARRATIVE_CARD="<div style=\"margin:16px 22px 4px;background:#0d1117;border:1px dashed #30363d;border-radius:6px;padding:11px 16px;color:#8b949e;font-size:12px\">🌙 Overnight narrative not ready — the win10 GPU scheduler hasn't finished the night-digest job (busy or still queued). It fills in once the summarise job completes.</div>"
  fi
else
  HEADER_TITLE="Evening digest"
  NARRATIVE_CARD=""   # evening queues the narrative; it lands in the morning email
fi

read -r -d '' HTML <<HTMLDOC || true
<!doctype html><html><body style="margin:0;background:#010409;padding:20px;font-family:${SANS}">
<div style="max-width:720px;margin:0 auto;background:#161b22;border:1px solid #30363d;border-radius:12px;overflow:hidden">
  <div style="background:#1f6feb;padding:18px 22px">
    <div style="font-size:11px;letter-spacing:.1em;color:#cfe0ff;text-transform:uppercase">HOME-OPS · ${TODAY}</div>
    <div style="font-size:22px;font-weight:700;color:#ffffff;margin-top:3px">${HEADER_TITLE}</div>
    <div style="font-size:12px;color:#cfe0ff;margin-top:6px;font-family:${MONO}">${STATUS_LINE}</div>
  </div>
  <div style="padding:14px 19px 0">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>${TILES}</tr></table>
  </div>
  ${NARRATIVE_CARD}
  <div style="margin:16px 22px 4px;background:#0d2136;border-left:3px solid #1f6feb;border-radius:6px;padding:13px 16px">
    <div style="font-size:10.5px;letter-spacing:.08em;color:${BLUE};text-transform:uppercase;font-weight:700">🎯 Today's focus</div>
    <div style="font-size:15px;color:#e6edf3;font-weight:600;margin:7px 0 4px">${FOCUS_H}</div>
    <div style="font-size:11px;color:#8b949e">${FOCUS_CAPTION}</div>
    ${BOARD_BTN}
  </div>
  <div style="${CARD}"><div style="${LBL}">Next · planned</div><pre style="${PRE}">${NEXT_H}</pre></div>
  <div style="${CARD}"><div style="${LBL}">Now · in progress</div><pre style="${PRE}">${NOW_H}</pre></div>
  <div style="${CARD}"><div style="${LBL}">Stack status</div><pre style="${PRE};line-height:1.45">${BODY_H}</pre></div>
  <div style="${CARD}"><div style="${LBL}">Commits · 24h</div><pre style="${PRE}">${COMMITS_H}</pre></div>
  <div style="background:#0d1117;color:#6e7681;padding:13px 22px;font-size:11px;border-top:1px solid #30363d">
    Generated by <span style="font-family:${MONO}">daily-digest.sh --mode ${MODE}</span> · manage tomorrow on the Board tab
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
  [[ "$MODE" == evening ]] && \
    printf '--- dry run: would queue_night_digest() for the overnight narrative ---\n' >&2
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

# Evening run kicks off the overnight LLM narrative now that the GPU is free of
# games; the win10 scheduler runs it overnight and the morning digest reads it.
# Idempotent per day (queue_night_digest skips if already queued).
if [[ "$MODE" == evening ]]; then
  NIGHT_ID="$(psql_val "SELECT queue_night_digest();" 2>/dev/null || true)"
  if [[ -n "$NIGHT_ID" ]]; then
    printf 'queued overnight narrative job id=%s\n' "$NIGHT_ID"
  else
    printf 'overnight narrative already queued for today (skipped)\n'
  fi
fi
