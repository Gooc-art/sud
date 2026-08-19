# Статус проекта sud

Дата фиксации: 2026-07-29.

## Что делаем

Проект собирает судебные заседания судов ЯНАО с официальных сайтов `sudrf.ru`
и формирует выгрузки:

- Excel: `report.xlsx`
- PDF: `report.pdf`
- HTML: `report.html`
- CSV: `report.csv`
- лог ошибок: `run_log.csv`

Официальный бесплатный API/CSV/XLSX для расписаний и карточек дел не найден.
Рабочий источник — HTML-страницы `Судебное делопроизводство` на сайтах судов.

## Репозиторий и сервер

- GitHub: `https://github.com/Gooc-art/sud`
- Сервер: `localadmin@10.10.68.10`
- Рабочая папка на сервере: `/home/localadmin/sud-app`
- GitHub Actions runner: `BOTSGSN-sud`
- Автодеплой: push в `main` обновляет `/home/localadmin/sud-app`
- Deploy workflow: `.github/workflows/deploy.yml`, только обновляет файлы.
- Restart MAX-бота: ручной workflow `.github/workflows/max-bot.yml`.
- Runner service: `actions.runner.Gooc-art-sud.BOTSGSN-sud.service`
- Runner folder: `/home/localadmin/actions-runner/actions-runner-sud`
- Не путать с `/home/localadmin/actions-runner`: это runner для `Gooc-art/energo`.

## Основной CLI

Файл: `sud_export.py`.

Пример запуска:

```bash
python3 sud_export.py \
  --from 2026-07-20 \
  --to 2026-07-26 \
  --outdir output/week-2026-07-20 \
  --timeout 8 \
  --sort-by-lawyer
```

Опции:

- `--from YYYY-MM-DD` — дата начала.
- `--to YYYY-MM-DD` — дата окончания.
- `--outdir PATH` — папка результата.
- `--court HOST` — ограничить одним судом; можно повторять.
- `--timeout N` — таймаут HTTP-запросов.
- `--max-cases N` — ограничить обогащение карточек для smoke-тестов.
- `--sort-by-lawyer` — сортировать отчет по представителям/адвокатам.
- `--refresh` — перекачать HTML заново, не брать кэш.

## Суды в MVP

- `oblsud--ynao.sudrf.ru`
- `salehardsky--ynao.sudrf.ru`
- `noyabrsky--ynao.sudrf.ru`
- `nadymsky--ynao.sudrf.ru`
- `novourengoysky--ynao.sudrf.ru`
- `muravlenkovsky--ynao.sudrf.ru`
- `tazovsky--ynao.sudrf.ru`
- `yamalsky--ynao.sudrf.ru`
- `labytnangsky.ynao.sudrf.ru`

## Колонки отчета

- `Группа представителя`
- `Кол-во дел у представителя`
- `Суд`
- `Дата заседания`
- `Время`
- `Номер дела`
- `Категория / причина`
- `Судья`
- `Стороны`
- `Адвокаты / представители`
- `Результат / статус`
- `Ссылка на карточку`
- `Статус проверки`

Сортировка по представителям:

1. Сначала представители/адвокаты с большим числом дел.
2. Их дела идут подряд.
3. Внутри группы сортировка по дате, времени и номеру дела.
4. Дела без представителя идут в конце группой `Без представителя`.

Упрощение MVP: если в деле несколько представителей, строка попадает в группу
первого найденного представителя, но в колонке `Адвокаты / представители`
остаются все найденные представители.

## HTML-кэш

Выгрузчик сохраняет сырой HTML:

```text
output/cache/schedules/
output/cache/cases/
```

Зачем:

- повторный запуск быстрее;
- меньше запросов к `sudrf.ru`;
- можно смотреть исходные страницы при ошибках парсинга.

Ожидаемый размер:

- неделя по региону: примерно `50-300 МБ`;
- месяц по региону: примерно `200 МБ - 1+ ГБ`.

## PDF

`report.html` — главный печатный шаблон с нормальной кириллицей.

`report.pdf` нормально формируется, если на сервере есть один из конвертеров:

- `libreoffice`
- `wkhtmltopdf`
- `chromium`

Без конвертера используется простая резервная PDF-версия; в некоторых
просмотрщиках кириллица может отображаться некорректно.

## MAX-бот

Файл: `src/godmod/max_bot.py`; корневой `max_bot.py` оставлен как wrapper для
старых команд.

Токена MAX пока нет. Когда появится, он хранится вне репозитория:

```text
~/.config/sud/max-bot.env
```

Шаблон:

```env
MAX_TOKEN=
MAX_BOT_TOKEN=
MAX_API_BASE=https://platform-api.max.ru
SUD_MAX_DAYS=31
SUD_ADMIN_USER_IDS=6393482
GODMOD_ACCESS_ADMIN_USER_IDS=6393482
GODMOD_USE_MOCK_DATA=false
```

Установка user-service:

```bash
cd ~/sud-app
./scripts/install_max_bot_service.sh
```

После получения токена:

```bash
nano ~/.config/sud/max-bot.env
systemctl --user restart sud-max-bot.service
systemctl --user status sud-max-bot.service
```

Команды бота:

- `/start`
- `/month`
- `/week`
- `/period`
- `/status`
- `/weekly_here`
- `/cancel`

Бот запускает выгрузки с `--sort-by-lawyer`.

Inline-экраны:

- Главное меню: `📊 Выгрузка за месяц`, `📅 Выбрать период`, `📌 Статус выгрузки`, `❌ Отмена`.
- Выбор периода: `📆 Текущая неделя`, `📊 Прошлая неделя`, `✏️ Свой период`, `⬅️ Назад`, `🏠 Главное меню`.
- Выбор суда: `🏛 Все суды`, отдельные суды ЯНАО, `⬅️ Назад`, `🏠 Главное меню`.
- Подтверждение: `✅ Запустить выгрузку`, `📅 Изменить период`, `🏛 Изменить суд`, `🏠 Главное меню`.
- Статус: `🔄 Обновить статус`, `🏠 Главное меню`.

Автоуведомление по ФНС:

- файл: `weekly_fns_notify.py`
- установка: `./scripts/install_weekly_fns_timer.sh`
- workflow: `.github/workflows/weekly-fns.yml` для ручного запуска
- расписание: понедельник 00:30
- чат: `/weekly_here` или `SUD_WEEKLY_CHAT_ID` в `~/.config/sud/max-bot.env`

Правило меню: бот хранит ID последнего меню и редактирует его через MAX
`PUT /messages`, поэтому меню не должно дублироваться в чате. Если MAX не
вернет ID сообщения или редактирование не пройдет, бот отправит новое меню как
fallback.

## GitHub Actions

### deploy

Файл: `.github/workflows/deploy.yml`.

Запускается на push в `main`.
Обновляет серверную папку:

```text
/home/localadmin/sud-app
```

### export

Файл: `.github/workflows/export.yml`.

Ручной запуск выгрузки через GitHub Actions:

```bash
gh workflow run export \
  --repo Gooc-art/sud \
  -f date_from=2026-07-20 \
  -f date_to=2026-07-26 \
  -f outdir=output/week-2026-07-20
```

Последний полный недельный запуск:

- run id: `30449350562`
- период: `2026-07-20..2026-07-26`
- статус: `success`
- длительность: примерно 39 минут
- папка: `/home/localadmin/sud-app/output/week-2026-07-20`

## Как скачать отчет

```bash
scp localadmin@10.10.68.10:/home/localadmin/sud-app/output/week-2026-07-20/report.xlsx ~/Downloads/
scp localadmin@10.10.68.10:/home/localadmin/sud-app/output/week-2026-07-20/report.pdf ~/Downloads/
```

Если папка загрузок русская:

```bash
scp localadmin@10.10.68.10:/home/localadmin/sud-app/output/week-2026-07-20/report.xlsx ~/Загрузки/
scp localadmin@10.10.68.10:/home/localadmin/sud-app/output/week-2026-07-20/report.pdf ~/Загрузки/
```

## Проверки

Локально:

```bash
python3 -m unittest -q
python3 -m py_compile sud_export.py max_bot.py
```

Smoke одного суда:

```bash
python3 sud_export.py \
  --from 2026-07-20 \
  --to 2026-07-26 \
  --court salehardsky--ynao.sudrf.ru \
  --outdir /tmp/sud-week-enriched10 \
  --timeout 8 \
  --max-cases 10 \
  --sort-by-lawyer
```

## Известные ограничения

- Данные берутся только из опубликованных HTML-страниц `sudrf.ru`.
- Если сайт скрывает данные, выгрузчик не может восстановить их.
- Отсутствие адвоката в карточке не доказывает, что адвоката нет.
- Полная неделя по всем судам занимает десятки минут.
- Основная нагрузка — ожидание `sudrf.ru`, не CPU сервера.
- Для стабильного PDF нужен системный HTML-to-PDF конвертер.
