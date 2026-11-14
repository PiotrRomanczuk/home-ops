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
#   scripts/deploy-agent.sh elitedesk claude-collector   # agents/claude-collector.py + .timer
#   scripts/deploy-agent.sh mac       mac-watcher        # this Mac, launchd
#
# What it does (Linux/systemd-user hosts):
#   1. rsync agents/_common.py   to ~/bin/_common.py        (shared)
#      + agents/<host>/*_*.py helper modules (e.g. queue_md.py; agent files
#        themselves are hyphenated, helpers use underscores so they import)
#   2. rsync agents/<host>/<agent_name>.py     to ~/bin/
#   3. rsync agents/<host>/<agent_name>.service to ~/.config/systemd/user/
#      + agents/*.py shared libraries (redact.py, claude_*.py, spool.py, …)
#      The script may also live at agents/<agent_name>.py (host-agnostic
#      agents such as claude-collector); the unit stays per host.
#   4. systemctl --user daemon-reload && systemctl --user restart <name>
#      (+ enable --now <name>.timer when agents/<host>/<name>.timer exists)
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
# mac (run it ON the Mac — the laptop is not reachable as an ssh target):
#   1. copy agents/*.py, agents/mac/*.py and agents/mac/run.sh to ~/bin/home-ops/
#   2. install agents/mac/launchd/pl.pionat.home-ops.<agent>.plist into
#      ~/Library/LaunchAgents (__HOME__ → $HOME), logs in ~/Library/Logs/home-ops/
#   3. launchctl bootout + bootstrap gui/$UID, then show the log tail
#   The ingest token comes from the Keychain item "home-ops-ingest" (run.sh).
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
  mac)           PLATFORM=macos ;;
  *) echo "✗ unknown host '$HOST' (expected: elitedesk|rpi|win10|mac)" >&2; exit 1 ;;
esac

SRC_DIR="agents/$HOST"
SCRIPT_PATH="$SRC_DIR/$AGENT.py"
[ -f "$SCRIPT_PATH" ] || SCRIPT_PATH="agents/$AGENT.py"
SERVICE_PATH="$SRC_DIR/$AGENT.service"
TIMER_PATH="$SRC_DIR/$AGENT.timer"

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

  for lib in agents/*.py; do
    [ "$lib" = "$SCRIPT_PATH" ] || run rsync -t "$lib" "$HOST:~/bin/$(basename "$lib")"
  done
  for helper in "$SRC_DIR"/*_*.py; do
    [ -f "$helper" ] && run rsync -t "$helper" "$HOST:~/bin/$(basename "$helper")"
  done
  run rsync -t "$SCRIPT_PATH"    "$HOST:~/bin/$(basename "$SCRIPT_PATH")"
  run rsync -t "$SERVICE_PATH"   "$HOST:~/.config/systemd/user/$(basename "$SERVICE_PATH")"
  if [ -f "$TIMER_PATH" ]; then
    # Timer-driven oneshot: run it once now, then let the timer take over.
    run rsync -t "$TIMER_PATH" "$HOST:~/.config/systemd/user/$(basename "$TIMER_PATH")"
    run ssh "$HOST" "systemctl --user daemon-reload && systemctl --user enable --now $AGENT.timer && systemctl --user start $AGENT && systemctl --user list-timers $AGENT.timer --no-pager"
  else
    run ssh "$HOST" "systemctl --user daemon-reload && systemctl --user restart $AGENT && sleep 2 && systemctl --user is-active $AGENT"
  fi

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

elif [ "$PLATFORM" = macos ]; then
  LABEL="pl.pionat.home-ops.$AGENT"
  PLIST_SRC="agents/mac/launchd/$LABEL.plist"
  PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
  BIN="$HOME/bin/home-ops"
  [ -f "$PLIST_SRC" ] || { echo "✗ no plist at $PLIST_SRC" >&2; exit 1; }
  echo "▶ deploying $AGENT to this Mac (launchd $LABEL)"

  run mkdir -p "$BIN" "$HOME/Library/Logs/home-ops" "$HOME/Library/LaunchAgents"
  run cp agents/*.py agents/mac/*.py agents/mac/run.sh "$BIN/"
  run chmod +x "$BIN/run.sh"
  if [ "${DRY_RUN:-0}" = "1" ]; then echo "+ sed __HOME__ $PLIST_SRC > $PLIST_DST"
  else sed "s#__HOME__#$HOME#g" "$PLIST_SRC" > "$PLIST_DST"; fi
  run launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  run launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
  run launchctl print "gui/$(id -u)/$LABEL" | grep -E 'state|last exit' || true

  echo "▶ recent log:"
  run tail -n 10 "$HOME/Library/Logs/home-ops/$AGENT.log" 2>/dev/null || true
  echo "✓ $AGENT deployed to this Mac"
fi
