# PostgreSQL из продового бэкапа

Карточки читаются напрямую из `Articles`, `Courses`, `Documents`, `Webinars`,
`Podcasts`, `Calculators`/`CalculatorPages`; статусы — из `Statuses`, типы доступа —
из `CourseTypes`/`ContentSettings`, темы — из `Topics`/`ContentSettingsTopics`.
JSON-каталог и `alfa_api_materials` в этом режиме не используются.
SQLAlchemy только читает схему и данные исходных таблиц.

## Сейчас: восстановить только PostgreSQL

Из корня репозитория:

```bash
cd backend
# Создать локальный env с новым паролем; существующий файл не перезаписывается.
python3 scripts/setup_snapshot_env.py
docker compose --env-file .env.snapshot up -d --wait db
```

По умолчанию запускается только `db`. При первом старте нового `snapshot_pgdata`
образ PostgreSQL 17 восстанавливает `../alfa_course_hackathon.backup` через
`pg_restore --single-transaction --exit-on-error --no-owner --no-privileges`.
Файл бэкапа подключён read-only, повторный запуск использует уже восстановленный том.
Healthcheck проходит после завершения восстановления и старта основного сервера.
При ошибке восстановления не используйте неполный том: исправьте ошибку и создайте
отдельный новый том/Compose project для повторной попытки.

База: `alfa_snapshot`, пользователь: `alfa`, локальный порт: `55432` (POSTGRES_PORT).
Старый том `api_pgdata` для демо не используется и не удаляется.
Для проверки:

```bash
docker compose --env-file .env.snapshot ps
docker compose --env-file .env.snapshot exec db psql -U alfa -d alfa_snapshot -c \
  'SELECT count(*) FROM public."Courses";'
docker compose --env-file .env.snapshot exec db psql -U alfa -d alfa_snapshot -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_name LIKE 'alfa_api_%';"
```

Второй счётчик должен быть нулём после восстановления исходного бэкапа.
`docker compose up` не запускает SQL-миграцию и не запускает API.

## Позже: вручную разрешить служебные таблицы и проверить API

В бэкапе нет таблицы пользователей сайта. Регистрация, токены, профиль и новые
события API требуют служебных таблиц из `migrations/001_api_state.sql`.
До их создания авторизованные маршруты не заработают; приложение не создаёт
таблицы автоматически и не переключается на SQLite или фиктивный каталог.
После отдельного решения применить миграцию:

```bash
docker compose --env-file .env.snapshot --profile tools run --rm migrate
docker compose --env-file .env.snapshot --profile app up -d --build api
```

`http://localhost:8080/docs`: зарегистрироваться, авторизоваться, вызвать
`GET /api/v1/catalog`, `GET /api/v1/search`. Режим `demo` в Compose означает
лексический поиск по данным PostgreSQL, а не демо-карточки. `seed-demo`,
`import-catalog`, `init-db` в режиме источника `postgres` запрещены.

## Настоящая модель

Для Python singleton запустите API нативно в окружении с ML-зависимостями:

```bash
export ALFA_DATABASE_URL='postgresql+psycopg://alfa:PASSWORD@localhost:55432/alfa_snapshot'
export ALFA_CATALOG_SOURCE=postgres
export ALFA_AUTO_CREATE_TABLES=false
export ALFA_RECO_MODE=python
export ALFA_RECO_CATALOG=/absolute/path/to/prepared-runtime/catalog
export ALFA_CATALOG_GENERATION=GENERATION_FROM_MODEL_CURRENT_JSON
uv run --no-sync uvicorn app:create_app --factory --port 8080 --workers 1
```

`ALFA_CATALOG_GENERATION` — метка совместимости индекса, не источник карточек.
Она должна совпадать с generation модели; модель возвращает ID вида `course:UUID`,
все поля карточек берутся из PostgreSQL. Совпадение метки само по себе не доказывает,
что модель построена по этому бэкапу: совместимость индекса проверяется отдельно.
Контейнерный API также поддерживает прежний `http`-режим с внешним ML-сервисом.
Базовый Dockerfile содержит только API-зависимости, поэтому `python` в нём
без установки ML-зависимостей не заработает.

## Правила чтения снимка

- Выдаются опубликованные, неудалённые, незакрытые материалы с типом «Открытый».
  Учебные статьи `IsLesson` не публикуются как самостоятельные карточки.
- Для калькуляторов публикация проверяется в `CalculatorPages` по общему ID.
- `Documents.TypeId` относится к DocumentTypes; доступ берётся из ContentSettings.
- Новые пользователи API не присваивают себе права продовых UserId. Платные,
  подписочные и неизвестные типы доступа не выдаются без интеграции идентичностей.
- `Cost` сохраняется как записан в БД. Валюты в этих таблицах нет: currency=null.
- Абсолютный HTTPS URL возвращается как есть; относительные slugs не превращаются
  в выдуманные адреса, canonical_url=null. HTML в заголовках/описаниях очищается.
- История и профиль новых пользователей хранятся в PostgreSQL в служебных таблицах.
  Исторические CourseUserBindings не привязываются к новым аккаунтам без явного
  соответствия пользователей.

Бэкап и восстановленные данные не добавляются в Git. В репозиторий входят только
код адаптера, Compose, тесты на искусственных данных и SQL создания новых таблиц.

## Готовый локальный env

`backend/.env.snapshot` создаётся командой `python3 scripts/setup_snapshot_env.py`
из шаблона `.env.snapshot.example`: отдельный Compose project
`alfa-snapshot`, порт 55432, PostgreSQL-источник и отключённый auto-create.
`ALFA_DATABASE_URL` в файле предназначен для нативного API; Compose заменяет адрес
на `db:5432` внутри сети контейнеров. Пароль генерируется локально и не хранится в Git.
Чтобы загрузить этот файл в нативный API, используйте `uv run --env-file .env.snapshot ...`.
Текущий `ALFA_RECO_MODE=demo` включает лексический поиск по настоящим материалам
PostgreSQL. Для модели используйте настройки из раздела «Настоящая модель».

Бэкап не «перекачивается» в приложение: Docker монтирует его read-only как
`/backup/source.backup`, а `pg_restore` восстанавливает DDL, данные, индексы и
ограничения в `alfa_snapshot`. PostgreSQL хранит результат в `snapshot_pgdata`.
Далее репозиторий читает таблицы через SQL; файл backup на запросах не читается.
