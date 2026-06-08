#!/usr/bin/env bash
# deploy-agent.sh — one-command redeploy for a per-host agent.
#
# Usage:
#   scripts/deploy-agent.sh <host> <agent_name>
#
# Examples:
#   scripts/deploy-agent.sh elitedesk elitedesk-watcher
#   scripts/deploy-agent.sh elitedesk planner-sync
#   scripts/deploy-agent.sh rpi       rpi-watcher
#   scripts/deploy-agent.sh win10     ollama-watcher
#
# What it does (Linux/systemd-user hosts):
#   1. rsync agents/_common.py   to ~/bin/_common.py        (shared)
#   2. rsync agents/<host>/<agent_name>.py     to ~/bin/
#   3. rsync agents/<host>/<agent_name>.service to ~/.config/systemd/user/
#   4. systemctl --user daemon-reload && systemctl --user restart <name>
#   5. tail journalctl --user -u <name> --since "30 sec ago" — confirms
#      the restart self-log lands ("<name> up …").
#
# win10 special-cases:
#   1. scp agents/_common.py to C:/ProgramData/<ServiceName>/_common.py
#   2. scp agents/win10/<agent_name>.py
#   3. clear __pycache__
#   4. ssh win10 "Restart-Service <ServiceName>"
#   5. show last 10 stderr lines from C:/ProgramData/<ServiceName>/<Service>.err.log
#
# Env:
#   DRY_RUN=1   echo commands without running

set -euo pipefail

HOST="${1:?usage: deploy-agent.sh <host> <agent_name>}"
AGENT="${2:?usage: deploy-agent.sh <host> <agent_name>}"

cd "$(dirname "$0")/.."

case "$HOST" in
  elitedesk|rpi) PLATFORM=linux ;;
  win10)         PLATFORM=windows ;;
  *) echo "✗ unknown host '$HOST' (expected: elitedesk|rpi|win10)" >&2; exit 1 ;;
esac

SRC_DIR="agents/$HOST"
SCRIPT_PATH="$SRC_DIR/$AGENT.py"
SERVICE_PATH="$SRC_DIR/$AGENT.service"

if [ ! -f "$SCRIPT_PATH" ]; then
  echo "✗ no script at $SCRIPT_PATH" >&2
  exit 1
fi

run() { if [ "${DRY_RUN:-0}" = "1" ]; then echo "+ $*"; else "$@"; fi }

if [ "$PLATFORM" = linux ]; then
  if [ ! -f "$SERVICE_PATH" ]; then
    echo "✗ no service unit at $SERVICE_PATH" >&2
    exit 1
  fi
  echo "▶ deploying $AGENT to $HOST (linux/systemd-user)"

  run rsync -t agents/_common.py "$HOST:~/bin/_common.py"
  run rsync -t "$SCRIPT_PATH"    "$HOST:~/bin/$(basename "$SCRIPT_PATH")"
  run rsync -t "$SERVICE_PATH"   "$HOST:~/.config/systemd/user/$(basename "$SERVICE_PATH")"
  run ssh "$HOST" "systemctl --user daemon-reload && systemctl --user restart $AGENT && sleep 2 && systemctl --user is-active $AGENT"

  echo "▶ recent logs:"
  run ssh "$HOST" "journalctl --user -u $AGENT --since '30 sec ago' --no-pager | tail -20"
  echo "✓ $AGENT deployed to $HOST"

elif [ "$PLATFORM" = windows ]; then
  # WinSW service names are PascalCase variants of the agent name.
  case "$AGENT" in
    ollama-watcher)   SVC=OllamaWatcher ;;
    win10-watcher)    SVC=Win10Watcher ;;
    *)                SVC="$(echo "$AGENT" | sed 's/-//g')" ;;
  esac
  REMOTE_DIR="C:/ProgramData/$SVC"
  echo "▶ deploying $AGENT to win10 (WinSW service $SVC, dir $REMOTE_DIR)"

  run scp agents/_common.py "win10:$REMOTE_DIR/_common.py"
  run scp "$SCRIPT_PATH"    "win10:$REMOTE_DIR/$(basename "$SCRIPT_PATH")"
  run ssh win10 "powershell -Command \"Remove-Item -Recurse -Force '$REMOTE_DIR/__pycache__' -ErrorAction SilentlyContinue; Restart-Service $SVC; Start-Sleep -Seconds 3; Get-Service $SVC | Format-Table Name,Status -AutoSize\""

  echo "▶ recent stderr:"
  run ssh win10 "powershell -Command \"Get-Content '$REMOTE_DIR/$SVC.err.log' -Tail 10\""
  echo "✓ $AGENT deployed to win10"
fi
