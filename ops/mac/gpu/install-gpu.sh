#!/bin/sh
# install-gpu.sh — install the GPU supervisor's code and job list as root-owned files, so that a
# Claude agent running as the user cannot edit the supervisor or the job list. The commands in the
# list may still run code from user-writable directories (worktrees, ~/Documents), so what actually
# executes on the GPU is only as trusted as those directories.
#   sudo ./install-gpu.sh [gpu-jobs.json]      (without an argument only the code is updated)
# Then, as the user: ../sprint/install.sh (loads the LaunchAgent; the supervisor itself runs as the user).
set -eu
[ "$(id -u)" = 0 ] || { echo "Uruchom przez sudo: sudo $0 [gpu-jobs.json]"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=/usr/local/libexec/mac-worker
ETC=/usr/local/etc/mac-worker

install -d -o root -g wheel -m 755 "$LIB" "$ETC"
install -o root -g wheel -m 644 "$HERE/gpu_worker.py" "$HERE/gpu_jobs.py" "$HERE/gpu_report.py" \
  "$HERE/gpu_pause.py" "$HERE/machine.py" "$HERE/procs.py" "$LIB/"
# a module missing from the list above would crash the supervisor in a launchd restart loop: fail here instead
/usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0, sys.argv[1]); import gpu_worker' "$LIB"
if [ "${1:-}" ]; then
  /usr/bin/python3 -I -c 'import sys; sys.path.insert(0, sys.argv[2]); import gpu_jobs; gpu_jobs.load(__import__("pathlib").Path(sys.argv[1]))' "$1" "$LIB"
  install -o root -g wheel -m 644 "$1" "$ETC/gpu-jobs.json"
  echo "job list: $ETC/gpu-jobs.json"
fi
echo "code: $LIB"
if [ "${SUDO_USER:-}" ]; then
  launchctl asuser "$(id -u "$SUDO_USER")" launchctl kickstart -k "gui/$(id -u "$SUDO_USER")/pl.pionat.mac-worker.gpu" 2>/dev/null \
    && echo "GPU supervisor restarted" || echo "Now as the user: $HERE/../sprint/install.sh"
fi
