#!/usr/bin/env bash
# In-sandbox entrypoint: copy the mounted task into a writable dir, drive the
# local Ollama model through aider's edit->test->retry loop, then print one
# authoritative RESULT line. $1 = model (e.g. qwen3:8b).
#
# Task is mounted read-only at /src; work happens in /work.
set -e

MODEL="${1:-qwen3:8b}"
cp -a /src/. /work/
cd /work

timeout "${TASK_TIMEOUT:-600}" aider \
  --model "ollama_chat/$MODEL" \
  --edit-format whole \
  --test-cmd "pytest -q" --auto-test \
  --yes-always --no-git --no-stream --no-pretty \
  --no-check-update --no-auto-lint --map-tokens 0 \
  --message "$(cat PROMPT.md)" solution.py \
  > /work/aider.log 2>&1 || true

# test_runs = number of pytest summary lines aider produced during the loop
runs=$(grep -cE '[0-9]+ (passed|failed|error)' /work/aider.log || true)
tsent=$(grep -oE 'Tokens: [0-9]+ sent' /work/aider.log | grep -oE '[0-9]+' | awk '{s+=$1} END{print s+0}')
trecv=$(grep -oE 'sent, [0-9]+ received' /work/aider.log | grep -oE '[0-9]+' | awk '{s+=$1} END{print s+0}')

# authoritative pass/fail — re-run the test after aider is done
if pytest -q > /work/final.log 2>&1; then passed=true; else passed=false; fi

printf 'RESULT passed=%s test_runs=%s tok_sent=%s tok_recv=%s\n' \
  "$passed" "${runs:-0}" "${tsent:-0}" "${trecv:-0}"
