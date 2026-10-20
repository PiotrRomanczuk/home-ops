#!/usr/bin/env bash
# seo-brief-export.sh — push the morning SEO card into the daily-brief repo.
#
# The daily brief runs as a Claude cloud routine and cannot reach this host, so
# it never saw SEO. seo-analyse (06:30) already writes digest.d/seo-<site>.txt;
# this job (06:50) copies it to daily-brief/inputs/seo-<site>.md with a dated
# header and pushes to main. The morning brief reads inputs/seo-*.md.
#
# Own clone (SEO_BRIEF_REPO), separate from brief-pull's read-only one; pushes
# with the host's GitHub key (same as seo-improve). Only inputs/ is touched.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE="${SEO_SITE:-gitarawarszawa.pl}"
REPO="${SEO_BRIEF_REPO:-$HOME/code/daily-brief-inputs}"
GIT_URL="${SEO_BRIEF_GIT:-git@github.com:PiotrRomanczuk/daily-brief.git}"
CARD="${SCRIPT_DIR}/digest.d/seo-${SITE//./-}.txt"
OUT="inputs/seo-${SITE//./-}.md"
TODAY="$(date +%F)"

log() { printf '%s seo-brief-export: %s\n' "$(date +%T)" "$*" >&2; }

[[ -s "$CARD" ]] || { log "no card at $CARD — seo-analyse did not run?"; exit 1; }
CARD_DAY="$(date -r "$CARD" +%F)"
[[ "$CARD_DAY" == "$TODAY" ]] || log "warning: card is from $CARD_DAY, not today — exporting with that date"

[[ -d "$REPO/.git" ]] || git clone -q "$GIT_URL" "$REPO"
cd "$REPO"
git fetch -q origin main && git checkout -q main && git reset -q --hard origin/main

mkdir -p inputs
{
  printf -- '---\nsite: %s\nday: %s\nsource: home-ops seo-analyse (uwh)\n---\n\n' "$SITE" "$CARD_DAY"
  printf '```text\n'; cat "$CARD"; printf '```\n'
} > "$OUT"

git add "$OUT"
if git diff --cached --quiet; then log "no change"; exit 0; fi
git -c user.name="home-ops (uwh)" -c user.email="noreply@home-ops.local" \
  commit -q -m "inputs: SEO ${SITE} ${CARD_DAY}"
for attempt in 1 2 3; do
  git push -q origin main && { log "pushed $OUT ($CARD_DAY)"; exit 0; }
  log "push failed (attempt $attempt) — rebasing on the brief routine's commits"
  git pull -q --rebase origin main
done
exit 1
