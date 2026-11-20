#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

cd "$(dirname "$0")/../.."

pkg update -y
pkg install -y python git procps termux-api
python -m pip install -r requirements.txt
mkdir -p runtime logs "$HOME/.termux/boot"

if [ ! -f .env ]; then
  cp config/.env.redmi6a.example .env
  chmod 600 .env
  echo "Arquivo .env criado. Edite-o antes de iniciar o ApexPrime."
else
  chmod 600 .env
  echo "Arquivo .env existente preservado."
fi

echo "Instalação de pacotes concluída. Configure .env e depois execute scripts/start-apexprime.sh"
