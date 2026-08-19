# MAX Bot Runbook

Last updated: 2026-08-18

## Workspace

- Local workspace root in Codex: `/srv/projects/sud`
- Shell may print the same project as: `/home/Gooc/projects/sud`
- GitHub repo: `Gooc-art/sud`
- Production app directory on self-hosted runner/server: `$HOME/sud-app`

## Bot

- Bot entrypoint: `src/godmod/max_bot.py`
- Compatibility wrapper: `max_bot.py`
- Run command: `PYTHONPATH=src python3 -m godmod.max_bot --dotenv ~/.config/sud/max-bot.env`
- Production systemd user service: `sud-max-bot.service`
- Service install script: `scripts/install_max_bot_service.sh`
- State file on production: `$HOME/.config/sud/max-bot-state.json`
- Env file on production: `$HOME/.config/sud/max-bot.env`
- Do not write tokens or passwords into repo docs.

## Production Deploy

- Deploy workflow: `.github/workflows/max-bot.yml`
- Trigger command from repo:
  `gh workflow run max-bot.yml --ref main`
- The workflow fetches `origin/main`, resets `$HOME/sud-app`, writes env, installs/restarts `sud-max-bot.service`, and kills duplicate `max_bot.py --poll` processes.

## Production Debug

- Debug workflow: `.github/workflows/max-bot-debug.yml`
- Trigger command:
  `gh workflow run max-bot-debug.yml --ref main`
- It prints production commit, service state, running process, selected non-secret env, state JSON, and recent bot journal lines.

## Current Access Setup

- Admin user id in workflow env: `6393482`
- Admin phone in workflow env: `79320588150`
- User explicitly checked during debugging: `23325864`, phone `+79129111119`
- Manual access approvals are persisted in bot state as `approved_user_ids`.

## Current Menu Contract

- Top menu must show:
  - `🏢 Выгрузка по коммерции`
  - `⚖️ Выгрузка по судам`
  - `ℹ️ Помощь`
- Court export is inside `⚖️ Выгрузка по судам`.
- Commerce export opens the restored Godmod wizard:
  1. city
  2. service/category
  3. period
  4. mode
  5. confirmation
- Legacy commerce payloads `max:commerce` and `max:main` are mapped into the new commerce flow.

## Commercial Export

- Commercial export is restored from `Gooc-art/godmod` under `src/godmod`.
- The MAX production service is MAX-only; do not start a separate Telegram bot service.
- Telegram MTProto may still be used as a data source when `TELEGRAM_*` env is configured.
- Keep exactly one MAX long polling process for one MAX token.

## Verification Commands

- Unit tests: `PYTHONPATH=src python3 -m pytest -q`
- Fast court export smoke test:
  `PYTHONPATH=src python3 sud_export.py --from 2026-08-17 --to 2026-08-17 --court salehardsky--ynao.sudrf.ru --timeout 20 --outdir /tmp/sud-export-smoke`
- Fast commerce smoke test:
  `GODMOD_USE_MOCK_DATA=true PYTHONPATH=src python3 -m godmod.cli sample --cities "Салехард" --services "общепит" --period-days 30 --top-n 5 --platforms vk --output /tmp/sud-commerce-smoke/report.xlsx`
- Production deploy status:
  `gh run list --workflow max-bot.yml --limit 1`
- Production debug status:
  `gh run list --workflow max-bot-debug.yml --limit 1`
