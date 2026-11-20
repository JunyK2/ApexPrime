#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f .env ] || { echo "ERRO: .env não encontrado. Copie config/.env.redmi6a.example para .env."; exit 1; }
mkdir -p runtime logs
if [ -f runtime/supervisor.pid ] && kill -0 "$(cat runtime/supervisor.pid)" 2>/dev/null; then
  echo "Supervisor ApexPrime já está em execução (PID $(cat runtime/supervisor.pid))."
  exit 0
fi
termux-wake-lock >/dev/null 2>&1 || true
nohup bash "$ROOT/scripts/apexprime-supervisor.sh" >> "$ROOT/runtime/supervisor.log" 2>&1 </dev/null &
echo $! > "$ROOT/runtime/supervisor.pid"
sleep 3
if kill -0 "$(cat "$ROOT/runtime/supervisor.pid")" 2>/dev/null; then
  echo "Supervisor iniciado (PID $(cat runtime/supervisor.pid)). O worker sobe em seguida."
else
  echo "Supervisor não iniciou. Confira runtime/supervisor.log"
  exit 1
fi
