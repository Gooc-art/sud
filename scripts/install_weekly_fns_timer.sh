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
SUD_WEEKLY_CHAT_ID=
EOF
  chmod 600 "$env_file"
elif ! grep -q '^SUD_WEEKLY_CHAT_ID=' "$env_file"; then
  printf '\nSUD_WEEKLY_CHAT_ID=\n' >> "$env_file"
fi

cat > "$HOME/.config/systemd/user/sud-weekly-fns.service" <<EOF
[Unit]
Description=SUD weekly FNS notification
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$HOME/sud-app
EnvironmentFile=$env_file
ExecStart=/usr/bin/python3 $HOME/sud-app/weekly_fns_notify.py --timeout 8
EOF

cat > "$HOME/.config/systemd/user/sud-weekly-fns.timer" <<'EOF'
[Unit]
Description=Run SUD weekly FNS notification every Monday at 00:30

[Timer]
OnCalendar=Mon 00:30
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now sud-weekly-fns.timer
systemctl --user status sud-weekly-fns.timer --no-pager || true
