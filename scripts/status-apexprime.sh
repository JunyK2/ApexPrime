#!/data/data/com.termux/files/usr/bin/bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/runtime/supervisor.pid" ] && kill -0 "$(cat "$ROOT/runtime/supervisor.pid")" 2>/dev/null; then
  echo "ApexPrime supervisor: ONLINE (PID $(cat "$ROOT/runtime/supervisor.pid"))"
else
  echo "ApexPrime supervisor: OFFLINE"
fi
if [ -f "$ROOT/runtime/daemon.pid" ] && kill -0 "$(cat "$ROOT/runtime/daemon.pid")" 2>/dev/null; then
  echo "ApexPrime worker: ONLINE (PID $(cat "$ROOT/runtime/daemon.pid"))"
else
  echo "ApexPrime worker: OFFLINE / reiniciando"
fi
if [ -f "$ROOT/runtime/daemon.log" ]; then
  echo "---- últimas 30 linhas do daemon ----"
  tail -n 30 "$ROOT/runtime/daemon.log"
fi
if [ -f "$ROOT/runtime/supervisor.log" ]; then
  echo "---- últimas 10 linhas do supervisor ----"
  tail -n 10 "$ROOT/runtime/supervisor.log"
fi
