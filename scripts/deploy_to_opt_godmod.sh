#!/usr/bin/env bash
set -eu

src_dir="${1:-/tmp/sud-godmod-deploy}"
app_dir="/opt/godmod"
venv_dir="$app_dir/.venv"
env_file="$app_dir/.env"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo $0 $src_dir" >&2
  exit 1
fi

systemctl stop godmod-max-bot.service || true

rsync -a --delete \
  --exclude .git \
  --exclude .tmp \
  --exclude output \
  --exclude venv \
  --exclude .venv \
  --exclude .env \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  --exclude '*.egg-info' \
  "$src_dir/" "$app_dir/"

python3 -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install -e "$app_dir"

if ! grep -q '^MAX_API_BASE=' "$env_file"; then
  printf '\nMAX_API_BASE=https://platform-api.max.ru\n' >> "$env_file"
fi

systemctl daemon-reload
systemctl enable godmod-max-bot.service
systemctl restart godmod-max-bot.service
systemctl status godmod-max-bot.service --no-pager
