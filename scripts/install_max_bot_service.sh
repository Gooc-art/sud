#!/usr/bin/env bash
set -eu

env_dir="$HOME/.config/sud"
env_file="$env_dir/max-bot.env"
app_dir="$HOME/sud-app"
venv_dir="$app_dir/.venv"
mkdir -p "$HOME/.config/systemd/user" "$env_dir"
if [ ! -f "$env_file" ]; then
  cat > "$env_file" <<'EOF'
MAX_TOKEN=
MAX_BOT_TOKEN=
MAX_API_BASE=https://platform-api2.max.ru
SUD_MAX_DAYS=45
SUD_EXPORT_TIMEOUT_SECONDS=14400
SUD_HTTP_TIMEOUT_SECONDS=20
SUD_ADMIN_USER_IDS=6393482
GODMOD_ACCESS_ADMIN_USER_IDS=6393482
SUD_ADMIN_PHONES=79320588150
SUD_COMMERCE_PASSWORD=
GODMOD_USE_MOCK_DATA=false
MAX_ALLOWED_CHAT_IDS=
VK_API_TOKEN=
VK_SERVICE_TOKEN=
VK_COMMUNITY_TOKEN=
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_USER_SESSION=
TWOGIS_API_KEY=
GOOGLE_PLACES_API_KEY=
EOF
  chmod 600 "$env_file"
elif ! grep -q '^SUD_ADMIN_USER_IDS=' "$env_file"; then
  printf '\nSUD_ADMIN_USER_IDS=6393482\n' >> "$env_file"
fi
if ! grep -q '^SUD_ADMIN_PHONES=' "$env_file"; then
  printf '\nSUD_ADMIN_PHONES=79320588150\n' >> "$env_file"
fi
if ! grep -q '^SUD_COMMERCE_PASSWORD=' "$env_file"; then
  printf '\nSUD_COMMERCE_PASSWORD=\n' >> "$env_file"
fi
if ! grep -q '^GODMOD_ACCESS_ADMIN_USER_IDS=' "$env_file"; then
  printf '\nGODMOD_ACCESS_ADMIN_USER_IDS=6393482\n' >> "$env_file"
fi
if ! grep -q '^GODMOD_USE_MOCK_DATA=' "$env_file"; then
  printf '\nGODMOD_USE_MOCK_DATA=false\n' >> "$env_file"
fi

python3 -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install -e "$app_dir"

cat > "$HOME/.config/systemd/user/sud-max-bot.service" <<EOF
[Unit]
Description=SUD MAX bot
After=network-online.target

[Service]
WorkingDirectory=$app_dir
EnvironmentFile=$env_file
Environment=PYTHONPATH=$app_dir/src
ExecStart=$venv_dir/bin/python -m godmod.max_bot --dotenv $env_file
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable sud-max-bot.service
pkill -f '[m]ax_bot.py --poll' || true
pkill -f '[g]odmod.max_bot' || true
systemctl --user restart sud-max-bot.service
systemctl --user status sud-max-bot.service --no-pager || true
