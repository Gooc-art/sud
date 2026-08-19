# sud

Отдельный проект для бота/выгрузчика судебных заседаний по ЯНАО.

## Идея

Сервис собирает данные с официальных сайтов судов ЯНАО и делает месячную
таблицу для просмотра/экспорта.

Минимальная таблица:

| Дата | Время | Дело | Суд | Судья | Причина | Адвокат | Ссылка |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Источник

Основной источник: сайты судов общей юрисдикции ЯНАО на `sudrf.ru`, раздел
`Судебное делопроизводство`.

Примеры:

- `https://salehardsky--ynao.sudrf.ru/modules.php?name=sud_delo`
- `https://noyabrsky--ynao.sudrf.ru/modules.php?name=sud_delo`
- `https://oblsud--ynao.sudrf.ru/modules.php?name=sud_delo`

## Что выяснено

- Нормального публичного API/CSV-выгрузки не видно.
- Расписание заседаний доступно как HTML-страницы по датам.
- В расписании обычно есть номер дела, время, зал, информация по делу, судья и результат.
- Адвокат чаще виден не в строке расписания, а в карточке дела в разделе `СТОРОНЫ`.
- Роль адвоката может называться `Защитник (адвокат)`.
- Иногда данные скрыты как `Информация скрыта`.
- Список на сайте не гарантирует полный реестр всех дел: часть категорий не публикуется.

## MVP

1. Пользователь выбирает месяц.
2. Сервис проходит по каждому дню месяца и каждому суду ЯНАО.
3. Берет список назначенных заседаний.
4. Переходит в карточку каждого дела.
5. Достает адвокатов/представителей из `СТОРОНЫ`.
6. Показывает таблицу и дает выгрузку CSV/XLSX.

## Ограничения

- Нужен аккуратный парсинг HTML, потому что официального API не найдено.
- Прямой запрос с нероссийского IP может блокироваться или возвращать ошибку.
- Для стабильной работы лучше запускать с российского сервера.
- Нельзя считать отсутствие адвоката в карточке доказательством, что адвоката нет.

## Запуск

```bash
python3 sud_export.py --from 2026-07-01 --to 2026-07-31 --outdir output
```

Результаты:

- `output/report.xlsx` — основной Excel.
- `output/report.csv` — резервная CSV-таблица.
- `output/report.html` — печатная HTML-версия с нормальной кириллицей.
- `output/report.pdf` — простая PDF-версия.
- `output/run_log.csv` — ошибки скачивания/парсинга.

Для нормального PDF с кириллицей на сервере должен быть установлен один
конвертер: `libreoffice`, `wkhtmltopdf` или `chromium`. Без него PDF остается
резервной простой версией, а печатным файлом считать `report.html`.

Для быстрой проверки одного суда:

```bash
python3 sud_export.py --from 2026-07-27 --to 2026-07-27 \
  --court salehardsky--ynao.sudrf.ru --max-cases 5 --outdir output
```

## Деплой

В репозитории есть workflow `.github/workflows/deploy.yml`.
Он рассчитан на GitHub Actions self-hosted runner внутри той же сети, где
доступен сервер/папка деплоя. GitHub-hosted runner не достучится до приватного
IP `10.10.68.10`.

Push в `main` автоматически выкладывает код в:

```text
$HOME/sud-app
```

Workflow деплоя только обновляет файлы. Для перезапуска MAX-бота используйте
ручной workflow `.github/workflows/max-bot.yml`.

Статус runner проверяется на странице Actions runners в GitHub или командой:

```bash
gh api repos/Gooc-art/sud/actions/runners
```

Runner `BOTSGSN-sud` на сервере работает как systemd service:

```text
actions.runner.Gooc-art-sud.BOTSGSN-sud.service
```

Рабочая папка runner-а:

```text
/home/localadmin/actions-runner/actions-runner-sud
```

Важно: `/home/localadmin/actions-runner` относится к другому репозиторию
`Gooc-art/energo`; для `sud` нужен именно вложенный `actions-runner-sud`.

## MAX бот

Для первого запуска используется Long Polling:

```bash
cd ~/sud-app
MAX_TOKEN=token_from_max PYTHONPATH=src python3 -m godmod.max_bot --dotenv ~/.config/sud/max-bot.env
```

Установка user-service:

```bash
cd ~/sud-app
./scripts/install_max_bot_service.sh
```

Установка еженедельной проверки ФНС:

```bash
cd ~/sud-app
./scripts/install_weekly_fns_timer.sh
```

Токен хранится вне репозитория:

```bash
nano ~/.config/sud/max-bot.env
systemctl --user restart sud-max-bot.service
```

Команды бота:

- `🏢 Выгрузка по коммерции` — города ЯНАО, услуги, период, режим, Excel/PDF.
- `⚖️ Выгрузка по судам` — судебная выгрузка ЯНАО.
- `/start` — главное меню MAX.

Коммерческая выгрузка живёт в пакете `src/godmod` и использует доступные
источники `VK`, `Telegram MTProto`, `Google Places`, `2GIS`. Telegram-бот как
отдельный production service не запускается.
- `/weekly_here` — сохранить текущий групповой чат для еженедельных уведомлений ФНС.
- `/cancel` — отмена ввода.

Автоуведомление по ФНС:

```bash
./scripts/install_weekly_fns_timer.sh
```

Таймер запускает сбор на следующую неделю по понедельникам в 00:30 и шлет `report.xlsx` в привязанный чат (`/weekly_here`, файл `SUD_WEEKLY_CHAT_ID_FILE`) или `SUD_WEEKLY_CHAT_ID`, если ФНС найдена. Workflow `weekly-fns` оставлен для ручного запуска.
