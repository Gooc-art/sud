#!/usr/bin/env bash
set -eu

env_dir="$HOME/.config/sud"
env_file="$env_dir/max-bot.env"
mkdir -p "$HOME/.config/systemd/user" "$env_dir"
if [ ! -f "$env_file" ]; then
  cat > "$env_file" <<'EOF'
MAX_TOKEN=
MAX_API_BASE=https://platform-api2.max.ru
SUD_MAX_DAYS=45
SUD_EXPORT_TIMEOUT_SECONDS=14400
SUD_HTTP_TIMEOUT_SECONDS=20
SUD_ADMIN_USER_IDS=6393482
SUD_ADMIN_PHONES=79320588150
SUD_COMMERCE_PASSWORD=
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

cat > "$HOME/.config/systemd/user/sud-max-bot.service" <<EOF
[Unit]
Description=SUD MAX bot
After=network-online.target

[Service]
WorkingDirectory=$HOME/sud-app
EnvironmentFile=$env_file
ExecStart=/usr/bin/python3 $HOME/sud-app/max_bot.py --poll
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable sud-max-bot.service
systemctl --user status sud-max-bot.service --no-pager || true
