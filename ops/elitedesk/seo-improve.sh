#!/usr/bin/env bash
# seo-improve.sh — weekly "make the promotion better" job for gitarawarszawa.pl.
#
# Monday 06:45 (seo-improve.timer). Reads the last 7 morning analyses from
# seo_analysis_daily, hands them to headless Claude Code *inside a clone of the
# gitara-lekcje repo*, lets it edit the site (titles, FAQ, district / metro
# sections, a new poradnik article…), runs the repo's quality gates and opens a
# pull request. It never merges: Piotr reviews every PR.
#
# Safety rails: fresh branch from origin/main every run; skip when an open
# `seo-auto` PR already exists; failed gates → changes discarded, PR not opened;
# nothing is pushed unless lint + typecheck + tests are green.
#
# Env (seo-collect.env): SEO_SITE_REPO (default ~/code/gitara-lekcje),
# SEO_SITE_GIT (clone URL, used once), CLAUDE_MODEL, CLAUDE_BIN, CLAUDE_TIMEOUT.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${SEO_SITE_REPO:-$HOME/code/gitara-lekcje}"
GIT_URL="${SEO_SITE_GIT:-git@github.com:PiotrRomanczuk/gitara-lekcje.git}"
SITE="${SEO_SITE:-gitarawarszawa.pl}"
CONTAINER="${CONTAINER:-home-ops-postgres-1}"; DB="${DB:-home_ops}"; DB_USER="${DB_USER:-postgres}"
CLAUDE="${CLAUDE_BIN:-claude}"; MODEL="${CLAUDE_MODEL:-sonnet}"; TIMEOUT_S="${CLAUDE_TIMEOUT:-1500}"
TODAY="$(date +%F)"; BRANCH="seo/auto-${TODAY}"; LABEL="seo-auto"
DRY="${1:-}"

log() { printf '%s seo-improve: %s\n' "$(date +%T)" "$*" >&2; }

# ── 0. preconditions ─────────────────────────────────────────────────────
command -v "$CLAUDE" >/dev/null || { log "claude CLI not found — skipping"; exit 0; }
command -v gh >/dev/null || { log "gh not found — skipping"; exit 0; }
if [[ ! -d "$REPO/.git" ]]; then
  log "cloning $GIT_URL → $REPO"; git clone -q "$GIT_URL" "$REPO"
fi
cd "$REPO"
if [[ -n "$(gh pr list --label "$LABEL" --state open --json number --jq '.[].number')" ]]; then
  log "an open $LABEL PR already exists — not stacking another; exit 0"; exit 0
fi

# ── 1. brief = plan (ready hypotheses first) + last 7 analyses ────────────
BRIEF="$(mktemp -t seo-brief.XXXXXX.md)"
READY_IDS="$(docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB" -X -q -t -A -c \
  "SELECT string_agg(id::text, ',') FROM (SELECT id FROM seo_plan WHERE site='${SITE}' AND status='ready' ORDER BY priority DESC, id LIMIT 3) t")"
{
  printf '# Brief SEO — tydzień do %s\n\n## DO WYKONANIA (hipotezy ready)\n\n' "$TODAY"
  docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB" -X -q -t -A <<SQL
SELECT '- #' || id || ' ' || title || E'\n  zmiana: ' || change || E'\n  dlaczego: ' || COALESCE(rationale,'') ||
       E'\n  mierzymy: ' || metric || ' dla fraz /' || target_queries || '/ i stron ' || array_to_string(target_pages, ', ')
FROM seo_plan WHERE site = '${SITE}' AND status = 'ready' ORDER BY priority DESC, id LIMIT 3;
SQL
  printf '\n## Reszta planu\n\n'
  docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB" -X -q -t -A <<SQL
SELECT '- #' || id || ' [' || status || ' p' || priority || '] ' || title || COALESCE(' · werdykt 28d: ' || (verdict->'day28'->>'status'), '')
FROM seo_plan WHERE site = '${SITE}' AND status NOT IN ('ready','retired') ORDER BY priority DESC, id LIMIT 15;
SQL
  printf '\n## Analizy dzienne\n\n'
  docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB" -X -q -t -A <<SQL
SELECT '### ' || day || E'\n\n' || card || E'\n\n' || COALESCE(narrative, '(bez narracji)') || E'\n'
FROM seo_analysis_daily WHERE site = '${SITE}' AND kind = 'daily'
ORDER BY day DESC LIMIT 7;
SQL
} > "$BRIEF"
if [[ "$(wc -c < "$BRIEF")" -lt 300 ]]; then log "brief is empty (no analyses yet) — exit 0"; exit 0; fi
PROMPT="$(sed -e "/{{BRIEF}}/{r $BRIEF" -e 'd}' "$SCRIPT_DIR/seo-improve.prompt.md")"
[[ "$DRY" == "--dry-run" ]] && { printf '%s\n' "$PROMPT"; exit 0; }

# ── 2. fresh branch, headless edit session ────────────────────────────────
git fetch -q origin main
git checkout -q -B "$BRANCH" origin/main
[[ -d node_modules ]] || npm ci --silent
ALLOWED="Read,Edit,Write,Glob,Grep,Bash(npm run lint),Bash(npm run typecheck),Bash(npm test),Bash(npx vitest run*),Bash(git diff*),Bash(git status*),Bash(ls*)"
edit_session() {  # $1 = prompt text, $2 = log suffix
  set +e
  timeout "$TIMEOUT_S" "$CLAUDE" -p --model "$MODEL" --output-format text --max-turns 80 \
    --permission-mode acceptEdits --allowedTools "$ALLOWED" \
    <<< "$1" > "/tmp/seo-improve-${TODAY}$2.log" 2>&1
  local rc=$?
  set -e
  log "claude exited $rc (log /tmp/seo-improve-${TODAY}$2.log)"
}
gates_ok() { npm run lint --silent && npm run typecheck --silent && npm test --silent; }
judge() {  # prints verdict JSON; sets JUDGE_OK=0/1
  local facts diff prompt
  facts="$(grep -E "prices|single|street|phoneDisplay|email|postalCode|openingHours|opens|closes" lib/site.ts | head -20)"
  git add -A; diff="$(git diff --cached | head -c 60000)"; git reset -q
  prompt="$(FACTS="$facts" DIFF="$diff" python3 -c '
import os, sys
t = open(sys.argv[1]).read()
print(t.replace("{{FACTS}}", os.environ["FACTS"]).replace("{{DIFF}}", os.environ["DIFF"]))' "$SCRIPT_DIR/seo-judge.prompt.md")"
  VERDICT="$(timeout 300 "$CLAUDE" -p --model "$MODEL" --output-format text --tools "" --max-turns 2 <<< "$prompt" 2>/dev/null || true)"
  printf '%s\n' "$VERDICT" > "/tmp/seo-judge-${TODAY}.json"
  printf '%s' "$VERDICT" | grep -q '"ok": *true' && JUDGE_OK=1 || JUDGE_OK=0
}
discard() { log "$1 — discarding changes"; git reset -q; git checkout -q -- .; git clean -qfd; exit 1; }

edit_session "$PROMPT" ""
if git diff --quiet && [[ -z "$(git status --porcelain)" ]]; then log "no changes proposed — exit 0"; exit 0; fi

# ── 3. gates + LLM-as-judge, with ONE repair round ────────────────────────
gates_ok || discard "quality gates FAILED"
judge
if [[ "$JUDGE_OK" != 1 ]]; then
  log "judge rejected the diff — one repair round"
  REPAIR="Sędzia odrzucił Twoje zmiany w tym repozytorium. Popraw DOKŁADNIE wymienione zastrzeżenia (nie rób nic innego), ponownie uruchom lint/typecheck/test i zaktualizuj raport docs/manual-tests. Zastrzeżenia:
${VERDICT}

Fakty o dojeździe i zasady twarde z pierwotnego zadania obowiązują nadal."
  edit_session "$REPAIR" "-repair"
  gates_ok || discard "quality gates FAILED after repair"
  judge
  [[ "$JUDGE_OK" == 1 ]] || discard "judge rejected the diff after repair (see /tmp/seo-judge-${TODAY}.json)"
fi

# ── 4. commit, push, PR (never merge) ─────────────────────────────────────
git add -A
git -c user.name="seo-improve (elitedesk)" -c user.email="p.romanczuk@gmail.com" \
  commit -q -m "feat(seo): propozycje z tygodniowej analizy ${TODAY}" \
  -m "Automatyczna propozycja z ops/elitedesk/seo-improve.sh (home-ops). Do przejrzenia, nie scalać bez czytania."
git push -q -u origin "$BRANCH"
gh label create "$LABEL" --color 1D76DB --description "automatyczna propozycja SEO z elitedesk" 2>/dev/null || true
{ printf '%s\n\n## Werdykt sędziego\n\n```json\n%s\n```\n' "$(cat "$BRIEF")" "$VERDICT"; } > "${BRIEF}.pr"
PR_URL="$(gh pr create --label "$LABEL" --title "SEO: propozycje z tygodnia do ${TODAY}" --body-file "${BRIEF}.pr")"
log "PR opened: $PR_URL"
if [[ -n "$READY_IDS" ]]; then
  docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB" -X -q -c \
    "UPDATE seo_plan SET status='in_pr', pr_url='${PR_URL}', updated_at=now() WHERE id IN (${READY_IDS}) AND status='ready'"
  log "plan rows ${READY_IDS} → in_pr"
fi
