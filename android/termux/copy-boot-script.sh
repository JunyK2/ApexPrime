#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$HOME/.termux/boot"
cp "$ROOT/android/termux/00-start-apexprime" "$HOME/.termux/boot/00-start-apexprime"
chmod 700 "$HOME/.termux/boot/00-start-apexprime"
echo "Script de boot instalado em ~/.termux/boot/00-start-apexprime"
