#!/usr/bin/env bash
# run-coding-task.sh <task_dir> [model]
#
# Drives a local Ollama model through aider's edit -> run-test -> feed-failure
# -> retry loop inside a throwaway Docker sandbox, until the task's pytest goes
# green (or aider gives up / times out). Generated code only runs in the container.
#
# Emits ONE JSON line on stdout:
#   {"task","model","passed":bool,"test_runs":int,"tok_sent":int,"tok_recv":int,"wall_s":int}
#
# Env:
#   OLLAMA_URL     default http://192.168.1.10:11434  (wfh on the LAN)
#   RUNNER_IMAGE   default llm-eval-runner
#   TASK_TIMEOUT   per-task hard cap in seconds, default 600
set -euo pipefail

TASK_DIR="$(cd "$1" && pwd)"
TASK="$(basename "$TASK_DIR")"
MODEL="${2:-qwen3:8b}"
OLLAMA="${OLLAMA_URL:-http://192.168.1.10:11434}"
IMAGE="${RUNNER_IMAGE:-llm-eval-runner}"
TIMEOUT="${TASK_TIMEOUT:-600}"

start=$(date +%s)
out="$(docker run --rm \
  -e OLLAMA_API_BASE="$OLLAMA" \
  -e AIDER_ANALYTICS=false \
  -e OPENAI_API_KEY=x \
  -e TASK_TIMEOUT="$TIMEOUT" \
  -v "$TASK_DIR":/src:ro \
  "$IMAGE" "$MODEL" 2>/dev/null | grep '^RESULT' | tail -1)"
end=$(date +%s)

get() { sed -n "s/.*$1=\\([A-Za-z0-9]*\\).*/\\1/p" <<<"$out"; }
passed="$(get passed)";     passed="${passed:-false}"
runs="$(get test_runs)";    runs="${runs:-0}"
tsent="$(get tok_sent)";    tsent="${tsent:-0}"
trecv="$(get tok_recv)";    trecv="${trecv:-0}"

printf '{"task":"%s","model":"%s","passed":%s,"test_runs":%s,"tok_sent":%s,"tok_recv":%s,"wall_s":%s}\n' \
  "$TASK" "$MODEL" "$passed" "$runs" "$tsent" "$trecv" "$((end - start))"
