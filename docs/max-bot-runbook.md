# MAX Bot Runbook

Last updated: 2026-08-18

## Workspace

- Local workspace root in Codex: `/srv/projects/sud`
- Shell may print the same project as: `/home/Gooc/projects/sud`
- GitHub repo: `Gooc-art/sud`
- Production app directory on self-hosted runner/server: `$HOME/sud-app`

## Bot

- Bot entrypoint: `max_bot.py`
- Run command: `python3 max_bot.py --poll`
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

- Top menu must only show:
  - `🏛 Выгрузка суды`
  - `💼 Выгрузка коммерции`
- Court export is inside `🏛 Выгрузка суды`.
- Commerce export is password-protected and then opens a 5-step wizard:
  1. city
  2. sphere
  3. period
  4. mode
  5. confirmation
- Legacy commerce payloads `max:commerce` and `max:main` are mapped into the new commerce flow.

## Known Limitation

- This repo currently has no real commercial exporter.
- `sud_export.py` is the real court exporter.
- The commerce wizard must not launch `sud_export.py` as if it were commercial export.
- Until a real commercial export command/script is added, `commerce_run_confirm` must stop with: `Коммерческий экспортер не настроен. Судовая выгрузка не запущена.`

## Verification Commands

- Unit tests: `python3 -m unittest`
- Fast court export smoke test:
  `python3 sud_export.py --from 2026-08-17 --to 2026-08-17 --court salehardsky--ynao.sudrf.ru --max-cases 1 --timeout 20 --outdir /tmp/sud-export-smoke`
- Production deploy status:
  `gh run list --workflow max-bot.yml --limit 1`
- Production debug status:
  `gh run list --workflow max-bot-debug.yml --limit 1`
