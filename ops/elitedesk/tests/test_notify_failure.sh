#!/usr/bin/env bash
# Test notify-failure.sh with fake systemctl/journalctl (no systemd needed).
# Run: bash ops/elitedesk/tests/test_notify_failure.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="$ROOT/ops/elitedesk/notify-failure.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/bin" "$TMP/hints"

cat >"$TMP/bin/systemctl" <<'F'
#!/usr/bin/env bash
# systemctl --user show|cat|list-timers ...
case "$2" in
  show) case "$5" in
    Description) echo "Fake job" ;;
    ExecMainStatus) echo 1 ;;
    InvocationID) [[ "${FAKE_NO_INVOCATION:-0}" = 1 ]] || echo abc123 ;;
    *) echo "Sat 2026-11-14 10:00:00 UTC" ;;
  esac ;;
  cat) [[ "$3" = "withtimer.timer" ]] ;;
  list-timers) echo "Sun 2026-11-15 10:00:00 UTC 3h left x" ;;
esac
F
cat >"$TMP/bin/journalctl" <<'F'
#!/usr/bin/env bash
args="$*"
if [[ "$args" == *_SYSTEMD_INVOCATION_ID* ]]; then
  printf 'Starting Fake job...\nzażółć gęślą jaźń zażółć gęślą jaźń zażółć gęślą jaźń zażółć gęślą jaźń błąd\nFailed to start Fake job.\n'
elif [[ "$args" == *"-o cat"* ]]; then
  printf 'Starting Fake job...\nfallback reason line\nFailed to start Fake job.\n'
elif [[ "$args" == *"--since"* ]]; then
  printf '2026-11-10T10:00:01+0000 h fake[9]: Finished 3/5 pages\n2026-11-12T10:00:01+0000 h systemd[1]: Finished Fake job.\n2026-11-14T10:00:01+0000 h fake[9]: Finished 1/5 pages\n'
else
  printf '2026-11-14T10:00:00+0000 h systemd[1]: Starting Fake job...\n'
fi
F
# macOS has no coreutils timeout; the script runs on Linux
printf '#!/usr/bin/env bash\nshift; exec "$@"\n' >"$TMP/bin/timeout"
chmod +x "$TMP/bin/"*
printf '#!/usr/bin/env bash\necho "hint for day $FAILED_DAY"\n' >"$TMP/hints/withtimer.sh"
chmod +x "$TMP/hints/withtimer.sh"

run() { PATH="$TMP/bin:$PATH" HOME="$TMP" FAILURE_HINT_DIR="$TMP/hints" DRY_RUN=1 bash "$SCRIPT" "$@"; }
fail() { echo "FAIL: $1"; exit 1; }
has() { grep -qF -- "$2" <<<"$1" || fail "missing: $2"; }
hasnt() { ! grep -qF -- "$2" <<<"$1" || fail "unexpected: $2"; }

out="$(run withtimer)"
[[ -z "${DUMP_DIR:-}" ]] || printf '%s\n' "$out" >"$DUMP_DIR/with-hint.txt"
subject="$(head -n 1 <<<"$out")"
has "$subject" "Subject: [home-ops] ❌ withtimer: zażółć"
# subject cut by characters: valid UTF-8, <=80 chars of message
printf '%s' "$subject" | iconv -f UTF-8 -t UTF-8 >/dev/null || fail "subject is not valid UTF-8"
has "$out" "2026-11-12 10:00:01"            # last OK from systemd lines only
hasnt "$out" "2026-11-14 10:00:01"
has "$out" "Sun 2026-11-15 10:00:00"    # next timer run
has "$out" "hint for day"                   # per-unit hint
hasnt "$out" "brak timera"

out="$(FAKE_NO_INVOCATION=1 run notimer)"
[[ -z "${DUMP_DIR:-}" ]] || printf '%s\n' "$out" >"$DUMP_DIR/no-timer.txt"
has "$out" "Subject: [home-ops] ❌ notimer: fallback reason line"   # anchored filter works in fallback
has "$out" "2026-11-14T10:00:00+0000"       # display keeps timestamps
has "$out" "brak timera"
hasnt "$out" "Kontekst"
echo "OK: notify-failure tests passed"
