#!/usr/bin/env bash
# Tests for scripts/check-public-data.sh, run against a throwaway git repo.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
gate="$here/../check-public-data.sh"
allowlist="$here/../public-data-allowlist.txt"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fails=0
repo="$tmp/repo"
git init -q -b base "$repo"
git -C "$repo" config user.email t@t.invalid
git -C "$repo" config user.name test
mkdir -p "$repo/docs/manual-tests"
echo seed > "$repo/seed.txt"
git -C "$repo" add -A && git -C "$repo" commit -q -m seed

# run_case <name> <expected rc> <path> <content>
run_case() {
  local name="$1" want="$2" path="$3" content="$4" rc=0
  git -C "$repo" checkout -q -B work base
  mkdir -p "$repo/$(dirname "$path")"
  printf '%s\n' "$content" > "$repo/$path"
  git -C "$repo" add -A && git -C "$repo" commit -q -m case
  (cd "$repo" && BASE=base ALLOWLIST="$allowlist" "$gate" > "$tmp/out" 2>&1) || rc=$?
  if [[ "$rc" -eq "$want" ]]; then echo "ok   $name"; else echo "FAIL $name (rc=$rc, want $want)"; cat "$tmp/out"; fails=$((fails + 1)); fi
}

at="@"
run_case "clean diff" 0 notes.txt "nothing personal here, port 8080, 2026-11-17"
run_case "e-mail" 1 notes.txt "contact: someone${at}company.pl"
run_case "allowlisted e-mail" 0 notes.txt "contact: me${at}example.com, noreply${at}x.pl"
run_case "phone with +48" 1 notes.txt "call +48 600 100 200"
run_case "phone with separators" 1 notes.txt "call 600-100-200 now"
run_case "MAC address" 1 notes.txt "device aa:bb:cc:dd:ee:ff"
run_case "data:image without marker" 1 docs/manual-tests/r.html '<img src="data:image/png;base64,AAAA">'
run_case "data:image with marker" 0 docs/manual-tests/r.html '<!-- data-demo="true" --><img src="data:image/png;base64,AAAA">'

# Output names file and kind, never the value.
git -C "$repo" checkout -q -B work base
printf 'x someone%scompany.pl\n' "$at" > "$repo/leak.txt"
git -C "$repo" add -A && git -C "$repo" commit -q -m leak
(cd "$repo" && BASE=base ALLOWLIST="$allowlist" "$gate" 2>/dev/null) > "$tmp/out" || true
if grep -q '^leak.txt:1: e-mail$' "$tmp/out" && ! grep -q company "$tmp/out"; then
  echo "ok   output format"
else
  echo "FAIL output format"; cat "$tmp/out"; fails=$((fails + 1))
fi

exit "$((fails > 0))"
