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

run_case "added line ++ x does not hide the next file lines" 1 docs/manual-tests/r.html "++ x
<img src=\"data:image/png;base64,AAAA\">
mail someone${at}company.pl"
run_case "added line ++ x, image only" 1 docs/manual-tests/r.html "++ x
<img src=\"data:image/png;base64,AAAA\">"
run_case "non-ASCII path with image" 1 "docs/manual-tests/zrzut-ź.html" '<img src="data:image/png;base64,AAAA">'
run_case "postgres URL is not an e-mail" 0 notes.txt "postgres://user${at}127.0.0.1:5432/x"
run_case "ssh user at IP is not an e-mail" 0 notes.txt "ssh user${at}192.168.1.25"
run_case "git remote" 0 notes.txt "git${at}github.com:a/b.git"
run_case "systemd unit" 0 notes.txt "backup${at}nightly.service"
run_case "gmail fixture name outside the fixture files" 1 notes.txt "ania${at}gmail.com"
run_case "gmail fixture in allowed test file" 0 ops/elitedesk/tests/test_gmail_llm.py "ania${at}gmail.com"
run_case "phone +48 without separators" 1 notes.txt "call +48600100200"
run_case "dummy phone" 0 notes.txt "call +48 000 000 000"
run_case "upper-case e-mail vs lower-case rule" 0 notes.txt "contact: ME${at}EXAMPLE.COM"
run_case "image with marker, e-mail-like text in base64" 0 docs/manual-tests/r.html "<!-- data-demo=\"true\" --><img src=\"data:image/png;base64,QQ${at}abc.de\">"

run_case "no-reply with prefix is not allowlisted" 1 notes.txt "jan.noreply${at}gmail.com"
run_case "no-reply sender allowed" 0 notes.txt "no-reply${at}x.pl"
run_case "MAC with dashes" 1 notes.txt "device aa-bb-cc-dd-ee-ff"
run_case "svg image file" 1 docs/diagram.svg "<svg/>"
run_case "upper-case PNG extension" 1 docs/manual-tests/S.PNG "x"
run_case "tiff image file" 1 docs/a.tiff "x"

# Missing base: the gate must stop, not pass silently.
rc=0; (cd "$repo" && BASE=nie-ma-takiej ALLOWLIST="$allowlist" "$gate" > "$tmp/out" 2>&1) || rc=$?
if [[ "$rc" -eq 2 ]]; then echo "ok   missing base stops the gate"; else echo "FAIL missing base (rc=$rc)"; cat "$tmp/out"; fails=$((fails + 1)); fi

# Image files under docs/ (binary content, not scanned line by line).
git -C "$repo" checkout -q -B work base
mkdir -p "$repo/docs/manual-tests"
printf '\211PNG\r\n\032\n\000\000' > "$repo/docs/manual-tests/shot.png"
git -C "$repo" add -A && git -C "$repo" commit -q -m png
rc=0; (cd "$repo" && BASE=base ALLOWLIST="$allowlist" "$gate" > "$tmp/out" 2>&1) || rc=$?
if [[ "$rc" -eq 1 ]] && grep -q '^docs/manual-tests/shot.png:0: image file$' "$tmp/out"; then
  echo "ok   image file blocked"
else
  echo "FAIL image file blocked (rc=$rc)"; cat "$tmp/out"; fails=$((fails + 1))
fi
printf 'file:^docs/manual-tests/shot\\.png$\n' > "$tmp/allow"
rc=0; (cd "$repo" && BASE=base ALLOWLIST="$tmp/allow" "$gate" > "$tmp/out" 2>&1) || rc=$?
if [[ "$rc" -eq 0 ]]; then echo "ok   image file allowed by file: rule"; else echo "FAIL image file allowed (rc=$rc)"; cat "$tmp/out"; fails=$((fails + 1)); fi

# file: rule with a Polish file name.
git -C "$repo" checkout -q -B work base
mkdir -p "$repo/docs/manual-tests"
printf '\211PNG' > "$repo/docs/manual-tests/zrzut-żółć.png"
git -C "$repo" add -A && git -C "$repo" commit -q -m pl
printf 'file:^docs/manual-tests/zrzut-żółć\\.png$\n' > "$tmp/allow"
rc=0; (cd "$repo" && BASE=base ALLOWLIST="$tmp/allow" "$gate" > "$tmp/out" 2>&1) || rc=$?
if [[ "$rc" -eq 0 ]]; then echo "ok   file: rule matches a Polish file name"; else echo "FAIL Polish file rule (rc=$rc)"; cat "$tmp/out"; fails=$((fails + 1)); fi
rc=0; (cd "$repo" && BASE=base ALLOWLIST="$allowlist" "$gate" > "$tmp/out" 2>&1) || rc=$?
if [[ "$rc" -eq 1 ]] && grep -q 'zrzut-żółć.png:0: image file' "$tmp/out"; then echo "ok   Polish image name blocked"; else echo "FAIL Polish image name (rc=$rc)"; cat "$tmp/out"; fails=$((fails + 1)); fi

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
