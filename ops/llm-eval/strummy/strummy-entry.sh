#!/usr/bin/env bash
# In-sandbox entrypoint for Strummy reconstruction tasks. Installs the task's
# stub over the real module (broken starting state), drives the local model
# through aider's edit->jest->retry loop, then runs the target test for an
# authoritative pass/fail. $1 = model. Task mounted read-only at /task with:
#   PROMPT.md, stub.txt, meta.env (EDIT_FILE, TEST_PATH — passed in as env).
set -e

MODEL="${1:-qwen3:8b}"
: "${EDIT_FILE:?EDIT_FILE required}" "${TEST_PATH:?TEST_PATH required}"

[ -f /task/stub.txt ] && cp /task/stub.txt "/app/$EDIT_FILE"
cd /app

timeout "${TASK_TIMEOUT:-900}" aider \
  --model "ollama_chat/$MODEL" \
  --edit-format whole \
  --test-cmd "npm test -- $TEST_PATH" --auto-test \
  --yes-always --no-git --no-stream --no-pretty \
  --no-check-update --no-auto-lint --map-tokens 0 \
  --read "$TEST_PATH" \
  --message "$(cat /task/PROMPT.md)" "$EDIT_FILE" \
  > /tmp/aider.log 2>&1 || true

# jest prints "Tests: N passed, M total" per run — count runs, sum tokens
runs=$(grep -cE 'Tests:.*(passed|failed|total)' /tmp/aider.log || true)
tsent=$(grep -oE 'Tokens: [0-9,]+ sent' /tmp/aider.log | grep -oE '[0-9,]+' | tr -d ',' | awk '{s+=$1} END{print s+0}')
trecv=$(grep -oE 'sent, [0-9,]+ received' /tmp/aider.log | grep -oE '[0-9,]+' | tr -d ',' | awk '{s+=$1} END{print s+0}')

if npm test -- "$TEST_PATH" > /tmp/final.log 2>&1; then passed=true; else passed=false; fi

printf 'RESULT passed=%s test_runs=%s tok_sent=%s tok_recv=%s\n' \
  "$passed" "${runs:-0}" "${tsent:-0}" "${trecv:-0}"
