#!/usr/bin/env bash
# run-strummy-task.sh <task_dir> [model]
# Runs one Strummy reconstruction task in the strummy-eval sandbox: install stub,
# drive the local model to make the real jest test green, record metrics.
# task_dir must contain PROMPT.md, stub.txt, meta.env (EDIT_FILE=, TEST_PATH=).
# Emits ONE JSON line: {task,model,passed,test_runs,tok_sent,tok_recv,wall_s}
set -euo pipefail

TASK_DIR="$(cd "$1" && pwd)"
TASK="$(basename "$TASK_DIR")"
MODEL="${2:-qwen3:8b}"
OLLAMA="${OLLAMA_URL:-http://192.168.1.10:11434}"
IMAGE="${STRUMMY_IMAGE:-strummy-eval}"
TIMEOUT="${TASK_TIMEOUT:-900}"

# shellcheck disable=SC1091
source "$TASK_DIR/meta.env"   # EDIT_FILE, TEST_PATH

start=$(date +%s)
out="$(docker run --rm \
  -e OLLAMA_API_BASE="$OLLAMA" \
  -e AIDER_ANALYTICS=false \
  -e OPENAI_API_KEY=x \
  -e EDIT_FILE="$EDIT_FILE" \
  -e TEST_PATH="$TEST_PATH" \
  -e TASK_TIMEOUT="$TIMEOUT" \
  -v "$TASK_DIR":/task:ro \
  "$IMAGE" "$MODEL" 2>/dev/null | grep '^RESULT' | tail -1)"
end=$(date +%s)

get() { sed -n "s/.*$1=\\([A-Za-z0-9]*\\).*/\\1/p" <<<"$out"; }
passed="$(get passed)"; passed="${passed:-false}"
runs="$(get test_runs)"; runs="${runs:-0}"
tsent="$(get tok_sent)"; tsent="${tsent:-0}"
trecv="$(get tok_recv)"; trecv="${trecv:-0}"

printf '{"task":"%s","model":"%s","passed":%s,"test_runs":%s,"tok_sent":%s,"tok_recv":%s,"wall_s":%s}\n' \
  "$TASK" "$MODEL" "$passed" "$runs" "$tsent" "$trecv" "$((end - start))"
