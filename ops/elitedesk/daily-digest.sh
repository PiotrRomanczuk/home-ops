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
  # First UNCHECKED item — done '[x]' lines are kept in the vault as a log,
  # so the literal first line may be a completed task.
  FOCUS="$(psql_val "
    SELECT regexp_replace(
             regexp_replace(t.line, '^\s*[-*]\s+\[ \]\s+', ''),
             '\*\*', '', 'g')
    FROM projects p,
         unnest(string_to_array(p.next_md, E'\n')) WITH ORDINALITY AS t(line, ord)
    WHERE p.slug = 'home-ops' AND t.line ~ '^\s*[-*]\s+\[ \]'
    ORDER BY t.ord LIMIT 1;" 2>/dev/null || true)"
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

# Colour tokens (terminal / CRT palette — matches the imported HOME-OPS design)
BG='#070b0a'; PANEL='#0a0f0c'; LINE='#16221d'; GREENLINE='#2a4a2f'
GREEN='#43d17f'; RED='#ff5c5c'; AMBER='#e3b341'; TEAL='#4fd6c8'
FG='#cfe3da'; BRIGHT='#eafff5'; MUTED='#8fb8a9'; DIM='#6e8479'; FAINT='#5c7168'; FAINTER='#4a5f56'
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
    -e "s@(── [^─]* ─+)@<span style=\"color:${FAINTER};letter-spacing:2px\">\1</span>@g" \
    -e "s@⚠ SILENT@<span style=\"color:${RED};font-weight:700\">⚠ SILENT</span>@g" \
    -e "s@\bfatal\b@<span style=\"color:${RED};font-weight:600\">fatal</span>@g" \
    -e "s@\berror\b@<span style=\"color:${AMBER}\">error</span>@g" \
    -e "s@\bwarn\b@<span style=\"color:${DIM}\">warn</span>@g" \
    -e "s@\bok\b@<span style=\"color:${GREEN}\">ok</span>@g"
}
# Turn markdown checkboxes/bold/code into tidy styling for the Next/Now lists.
listfmt() {
  sed -E -e "s@- \[[xX]\]@<span style=\"color:${GREEN}\">✓</span>@g" \
         -e "s@- \[ \]@<span style=\"color:${FAINTER}\">□</span>@g" \
         -e "s@\*\*([^*]+)\*\*@<b style=\"color:${BRIGHT}\">\1</b>@g" \
         -e "s@\`([^\`]+)\`@<span style=\"color:${TEAL}\">\1</span>@g"
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

# Terminal aesthetic: the whole email is monospace. JetBrains Mono if the client
# has it, else the platform mono stack (webfonts don't load in most mail clients).
MONO="'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
NOWTIME="$(date +%H:%M)"

# One reusable KPI tile: $1 value, $2 label, $3 colour (number + left accent stripe).
tile() { printf '<td width="20%%" valign="top" style="padding:4px"><div style="background:%s;border:1px solid %s;border-left:3px solid %s;border-radius:5px;padding:12px 13px"><div style="font-size:25px;font-weight:700;color:%s;font-family:%s;line-height:1">%s</div><div style="font-size:9.5px;letter-spacing:.09em;color:%s;margin-top:8px;text-transform:uppercase">%s</div></div></td>' "$PANEL" "$LINE" "$3" "$3" "$MONO" "$1" "$DIM" "$2"; }
TILES="$(tile "${STAT_HOSTS_OK}/${STAT_HOSTS_TOTAL}" "hosts up" "$c_hosts")$(tile "${STAT_ERRORS:-0}" "errors 24h" "$c_err")$(tile "${STAT_FATAL:-0}" "fatal 24h" "$c_fatal")$(tile "${STAT_EVALAGE}" "eval age" "$c_eval")$(tile "${STAT_GPUQ:-0}" "gpu queued" "$DIM")"

PRE="margin:0;color:#a7c4b8;font-size:12.5px;line-height:1.5;white-space:pre-wrap;font-family:${MONO}"
LBL="font-size:11px;letter-spacing:.1em;color:${DIM};text-transform:uppercase;font-weight:600;margin-bottom:10px"
CARD="margin:14px 20px;background:${PANEL};border:1px solid ${LINE};border-radius:6px;padding:14px 16px"

# "Open board" button + caption, only when a console URL is configured.
if [[ -n "$DIGEST_BOARD_URL" ]]; then
  BOARD_BTN="<div style=\"margin-top:12px\"><a href=\"${DIGEST_BOARD_URL}\" style=\"color:${TEAL};font-size:12.5px\">Open board →</a></div>"
  FOCUS_CAPTION="pinned on Board — drag cards or pin a new focus to change it"
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
    NARRATIVE_CARD="<div style=\"margin:14px 20px 4px;background:#0c150f;border:1px solid ${GREENLINE};border-radius:6px;padding:14px 16px\"><div style=\"font-size:11px;letter-spacing:.1em;color:${GREEN};text-transform:uppercase;font-weight:700\">🌙 Overnight narrative</div><pre style=\"${PRE};margin-top:8px\">${NARRATIVE_H}</pre></div>"
  else
    NARRATIVE_CARD="<div style=\"margin:14px 20px 4px;background:${PANEL};border:1px dashed ${LINE};border-radius:6px;padding:12px 16px;color:${DIM};font-size:12px\">🌙 Overnight narrative not ready — the win10 GPU scheduler hasn't finished the night-digest job (busy or still queued). It fills in once the summarise job completes.</div>"
  fi
else
  HEADER_TITLE="Evening digest"
  NARRATIVE_CARD=""   # evening queues the narrative; it lands in the morning email
fi
# Uppercase badge for the masthead (MORNING DIGEST / EVENING DIGEST).
BADGE="$(printf '%s' "$HEADER_TITLE" | tr '[:lower:]' '[:upper:]')"

read -r -d '' HTML <<HTMLDOC || true
<!doctype html><html><body style="margin:0;background:#040706;padding:20px;font-family:${MONO};color:${FG}">
<div style="max-width:720px;margin:0 auto;background:${BG};border:1px solid ${LINE};border-radius:8px;overflow:hidden">

  <!-- chrome bar -->
  <div style="padding:12px 18px;border-bottom:1px solid ${LINE}">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>
      <td style="font-size:12.5px">
        <span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:#ff5f57;vertical-align:middle"></span>
        <span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:#febc2e;vertical-align:middle;margin-left:6px"></span>
        <span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:#28c840;vertical-align:middle;margin-left:6px"></span>
        <span style="color:${FAINT};margin-left:12px">operator@home-ops:~\$</span>
        <span style="color:${MUTED};margin-left:8px">./digest --mode ${MODE}</span>
      </td>
      <td align="right" style="font-size:12.5px;color:${GREEN};white-space:nowrap">● connected <span style="color:${FAINT}">${NOWTIME}</span></td>
    </tr></table>
  </div>

  <!-- masthead -->
  <div style="padding:22px 18px;border-bottom:1px solid ${LINE}">
    <span style="font-size:24px;font-weight:700;letter-spacing:2px;color:${BRIGHT}">HOME-OPS</span>
    <span style="font-size:13px;color:${FAINT};margin-left:12px">${TODAY}</span>
    <span style="font-size:12px;color:${AMBER};border:1px solid #4a3c17;background:#1a1508;padding:2px 9px;border-radius:3px;letter-spacing:1px;margin-left:10px">${BADGE}</span>
    <span style="display:inline-block;width:8px;height:15px;background:${GREEN};vertical-align:middle;margin-left:8px"></span>
    <div style="margin-top:12px;color:${MUTED};font-size:13px">${STATUS_LINE}</div>
  </div>

  <!-- KPI tiles -->
  <div style="padding:16px 15px 2px">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>${TILES}</tr></table>
  </div>

  ${NARRATIVE_CARD}

  <!-- today's focus -->
  <div style="margin:14px 20px 4px;background:#0d1a11;border:1px solid ${GREENLINE};border-radius:6px;padding:14px 16px">
    <div style="font-size:11px;letter-spacing:.1em;color:${GREEN};text-transform:uppercase;font-weight:700">▸ Today's focus</div>
    <div style="font-size:15px;color:${BRIGHT};font-weight:600;margin:8px 0 4px">${FOCUS_H}</div>
    <div style="font-size:11px;color:${DIM}">${FOCUS_CAPTION}</div>
    ${BOARD_BTN}
  </div>

  <div style="${CARD}"><div style="${LBL}">Next · planned</div><pre style="${PRE}">${NEXT_H}</pre></div>
  <div style="${CARD}"><div style="${LBL}">Now · in progress</div><pre style="${PRE}">${NOW_H}</pre></div>
  <div style="${CARD}"><div style="${LBL}">Stack status</div><pre style="${PRE};line-height:1.45">${BODY_H}</pre></div>
  <div style="${CARD}"><div style="${LBL}">Commits · 24h</div><pre style="${PRE}">${COMMITS_H}</pre></div>

  <!-- footer -->
  <div style="padding:14px 20px;border-top:1px solid ${LINE};color:${FAINTER};font-size:11.5px">
    <span style="color:${FAINTER}">\$</span> Generated by <span style="color:${MUTED}">daily-digest.sh --mode ${MODE}</span> · manage tomorrow on the Board tab
    <span style="display:inline-block;width:7px;height:13px;background:${FAINTER};vertical-align:middle;margin-left:4px"></span>
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
  if [[ "$MODE" == evening ]]; then
    printf '%s\n' '--- dry run: would queue_night_digest() for the overnight narrative ---' >&2
  fi
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
