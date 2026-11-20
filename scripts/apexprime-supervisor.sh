#!/data/data/com.termux/files/usr/bin/bash
# Keep the worker alive. The worker itself handles network outages.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p runtime logs
CHILD_PID=""
finish() {
  if [ -n "$CHILD_PID" ]; then
    kill "$CHILD_PID" 2>/dev/null || true
    wait "$CHILD_PID" 2>/dev/null || true
  fi
  rm -f "$ROOT/runtime/daemon.pid" "$ROOT/runtime/supervisor.pid"
  command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock >/dev/null 2>&1 || true
  exit 0
}
trap finish INT TERM HUP
termux-wake-lock >/dev/null 2>&1 || true
while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando worker ApexPrime" >> "$ROOT/runtime/supervisor.log"
  python -m apexprime.daemon >> "$ROOT/runtime/daemon.log" 2>&1 &
  CHILD_PID=$!
  echo "$CHILD_PID" > "$ROOT/runtime/daemon.pid"
  wait "$CHILD_PID"
  EXIT_CODE=$?
  CHILD_PID=""
  rm -f "$ROOT/runtime/daemon.pid"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Worker encerrou (código $EXIT_CODE); nova tentativa em 15s" >> "$ROOT/runtime/supervisor.log"
  sleep 15
done
