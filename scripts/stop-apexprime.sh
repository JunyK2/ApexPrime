#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/runtime/supervisor.pid" ]; then
  PID="$(cat "$ROOT/runtime/supervisor.pid")"
  kill "$PID" 2>/dev/null || true
fi
sleep 2
if [ -f "$ROOT/runtime/daemon.pid" ]; then
  kill "$(cat "$ROOT/runtime/daemon.pid")" 2>/dev/null || true
fi
rm -f "$ROOT/runtime/supervisor.pid" "$ROOT/runtime/daemon.pid"
if command -v termux-wake-unlock >/dev/null 2>&1; then termux-wake-unlock >/dev/null 2>&1 || true; fi
echo "Solicitado encerramento do ApexPrime."
