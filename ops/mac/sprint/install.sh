#!/bin/sh
# install.sh — install the Mac worker for the current user (no sudo):
#   runner + status page → ~/bin/home-ops/sprint/ (with ../gpu/machine.py, procs.py), their LaunchAgents,
#   STATE/config.json from config.example.json if missing, and the GPU supervisor's LaunchAgent
#   once its root-owned code exists (sudo ../gpu/install-gpu.sh first).
# Re-running replaces the code and reloads the agents; a STOP file in STATE keeps the runner idle.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
DEST="$HOME/bin/home-ops/sprint"
STATE="${SPRINT_STATE:-$HOME/.local/state/home-ops/sprint}"
AGENTS="$HOME/Library/LaunchAgents"
UID_=$(id -u)

mkdir -p "$DEST" "$STATE" "$HOME/Library/Logs/home-ops" "$AGENTS"
cp "$HERE"/*.py "$HERE"/*.md "$HERE/../gpu/machine.py" "$HERE/../gpu/procs.py" "$DEST/"
[ -f "$STATE/config.json" ] || cp "$HERE/config.example.json" "$STATE/config.json"

load() {  # load <label> <plist source>
  sed "s|__HOME__|$HOME|g" "$2" > "$AGENTS/$1.plist"
  launchctl bootout "gui/$UID_/$1" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_" "$AGENTS/$1.plist"
  echo "loaded $1"
}

load pl.pionat.home-ops.sprint-status "$HERE/pl.pionat.home-ops.sprint-status.plist"
load pl.pionat.home-ops.sprint "$HERE/pl.pionat.home-ops.sprint.plist"
if [ -f /usr/local/libexec/mac-worker/gpu_worker.py ] && [ -f /usr/local/etc/mac-worker/gpu-jobs.json ]; then
  load pl.pionat.mac-worker.gpu "$HERE/../gpu/pl.pionat.mac-worker.gpu.plist"
else
  echo "GPU supervisor not installed yet: sudo $HERE/../gpu/install-gpu.sh <gpu-jobs.json>, then re-run this script"
fi
