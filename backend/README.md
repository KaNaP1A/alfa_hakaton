# Бэкенд для хакатона Alfa

FastAPI-приложение между фронтендом, `alfa_reco` и актуальным каталогом. Авторизация, профиль,
история, доступ, ссылки и цены находятся на стороне API. Исходный ML-код не изменён.

Связка с настоящими E5/CatBoost проверена локально 15 ноября 2026:
[результаты, запуск тестовой базы и повторные проверки](INTEGRATION_CHECK.md).

```text
Фронтенд / Swagger → FastAPI :8080 → alfa_reco :8000 (режим http)
                         ↓
               PostgreSQL / SQLite для демо
```

## ML напрямую из Python

`ALFA_RECO_MODE=python` подключает `alfa_reco` как библиотеку в процессе API.
Singleton `infrastructure/python_recommender.py` загружает каталог, E5 и CatBoost
один раз при создании приложения. Инициализация и обращения к модели защищены
блокировками. Каждый worker имеет свою модель; для одной копии используйте
`--workers 1`. Смена каталога требует перезапуска процесса.
Ошибка загрузки останавливает запуск приложения.

Из `backend` установите ML-библиотеку и зависимости в то же окружение:

```bash
uv sync --frozen
uv pip install ../05_code -r ../05_code/requirements-relevance.txt
export ALFA_RECO_MODE=python
export ALFA_RECO_CATALOG=/absolute/path/to/prepared-runtime/catalog
uv run --no-sync uvicorn app:create_app --factory --port 8080 --workers 1
```

`ALFA_RECO_CATALOG` указывает на подготовленный каталог с `CURRENT.json`.
Пути encoder в артефактах должны соответствовать этой машине (подготовка runtime
описана ниже). Исходники `05_code` менять не требуется.
В БД API импортируйте доверенный каталог той же generation, как и для HTTP-режима.
Поиск, подсказки, рекомендации и план вызываются напрямую; отдельный ML-сервер
не требуется. Текущий Docker-образ содержит только зависимости API; команды выше
предназначены для нативного запуска. Режимы `demo` и `http` также доступны.

## Проверить за несколько минут без модели и дампа

Из корня репозитория, Python 3.11+:

```bash
cd backend
uv sync --frozen
uv run alfa-backend seed-demo
uv run uvicorn app:create_app --factory --port 8080 --no-access-log --no-proxy-headers
```

Открыть **http://127.0.0.1:8080/docs**. Это интерактивный API, отдельный новый сайт не создаётся.
В другом терминале:

```bash
uv run python examples/smoke.py
```

Скрипт регистрирует временного пользователя, проверяет поиск и доступ, сохраняет историю,
получает рекомендации и план, затем выходит. В демокаталоге четыре вымышленных материала,
из них один закрытый; обычный пользователь видит три. Демо использует простой лексический
поиск, не E5/CatBoost. `mode=demo` явно отмечен в ответах. Ссылки и цены не выдуманы:
`canonical_url=null`, `price.status=unknown`.

**Ручной сценарий в Swagger:**

1. `POST /api/v1/auth/register`: `{"username":"reviewer","password":"my-review-password"}`.
2. Скопировать `access_token`, нажать **Authorize**, вставить только токен.
3. `PUT /api/v1/me/profile`: `{"categories":["business"]}`.
4. `GET /api/v1/search?q=кофейня`, затем `/api/v1/catalog`.
5. `POST /api/v1/me/events`:
   `{"generation":"demo-v1","event_id":"review-1","entity_key":"course:demo-coffee","action":"completed"}`.
6. `POST /api/v1/recommend` и `/api/v1/development-plan`: `{"generation":"demo-v1"}`.
7. Проверить `/api/v1/me/events`; перезапуск API сохраняет профиль и события.

SQLite-файл создаётся в текущей директории и исключён из Git. Запускать CLI и API из одной
директории или задать абсолютный `ALFA_DATABASE_URL=sqlite:////абсолютный/путь/backend.sqlite3`.

## PostgreSQL и Docker Compose

```bash
cd backend
cp .env.example .env
# Установить свой POSTGRES_PASSWORD в .env (URL-безопасные символы).
docker compose up --build -d
docker compose exec api alfa-backend seed-demo
```

Swagger: http://127.0.0.1:8080/docs. Данные сохраняются в `api_pgdata`; `docker compose down`
оставляет их. Порт PostgreSQL наружу не публикуется. Не использовать `down -v`, если нужны данные.

Для нативного API с имеющимся PostgreSQL:

```bash
export ALFA_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/alfa_api'
uv run alfa-backend init-db
```

Пароль в URL должен быть percent-encoded при наличии специальных символов. API создаёт только
таблицы с префиксом `alfa_api_`. Для исходного дампа и служебного API лучше разные базы.
Начальная схема создаётся через SQLAlchemy `create_all`; изменения схемы в следующих версиях
потребуют миграций, текущая версия не изменяет существующие колонки автоматически.

## Подключить настоящий алгоритм

Расположение весов и запуск комплекта: [models/README.md](../models/README.md).

1. Получить у владельца совместимый комплект каталога, E5, CatBoost и векторов. В Git его нет.
   Проверить комплект по [BACKEND_HANDOFF.md](../05_code/docs/BACKEND_HANDOFF.md).
2. В окружении алгоритма запустить из `05_code`:

   ```bash
   PYTHONPATH=src HF_HUB_OFFLINE=1 uv run python -m alfa_reco serve --output ../models/recommender/catalog --relevance --no-llm --port 8000
   ```

3. Подготовить актуальный доверенный каталог по формату ниже. `generation` должен совпадать
   с `/health` алгоритма; импортировать его через CLI.
4. Запустить публичный API:

   ```bash
   export ALFA_RECO_MODE=http
   export ALFA_RECO_URL=http://127.0.0.1:8000
   uv run uvicorn app:create_app --factory --port 8080 --no-access-log --no-proxy-headers
   ```

5. Проверить `/ready`, настоящий поиск, рекомендации и план. Режим `http` не переключается
   на демо при ошибке или отсутствии модели.

При обращении из контейнера к алгоритму на хосте нужны достижимый адрес и разрешённый `Host`.
В `.env` API: `ALFA_RECO_URL=http://host.docker.internal:8000`,
`ALFA_RECO_HOST_HEADER=localhost:8000`. Сам алгоритм должен слушать интерфейс, доступный
контейнеру, с сетевым ограничением входа. В CLI алгоритма есть опция `--host 0.0.0.0`; не открывать
его порт в интернет. На Linux loopback хоста недоступен через container gateway: одного
`host.docker.internal` без изменения bind недостаточно. Самый простой вариант хакатона — оба
Python-процесса нативно на одной машине.

## Актуальный каталог, доступ и цены

Импорт — полный атомарный снимок **из доверенного источника сайта**, а не доказательство
актуальности ML-снимка. Экземпляр формата: [examples/catalog.json](examples/catalog.json),
только вымышленные данные.

```bash
uv run alfa-backend import-catalog /закрытый/путь/catalog.json
```

Формат:

```json
{
  "generation": "тот-же-generation-что-в-алгоритме",
  "materials": [{
    "entity_key": "course:source-id",
    "kind": "course",
    "title": "Подтверждённое название",
    "description": "Подтверждённое описание",
    "topics": ["Подтверждённая тема"],
    "published": true,
    "access": "restricted",
    "canonical_url": "https://example.org/verified-course",
    "price_amount": "1500.00",
    "price_currency": "RUB"
  }]
}
```

По умолчанию `published=false`, `access=restricted`. Неизвестная цена задаётся двумя `null`;
не превращается в ноль. При замене каталога отсутствующие материалы исчезают из выдачи.
При смене поколения старая история сохраняется, но не передаётся новой модели. Grants сохраняются
по стабильному `entity_key`; если источник переиспользует ID, требуется отдельная миграция прав.

Выдать или отозвать доступ можно только доверенной CLI-командой, не клиентским событием:

```bash
uv run alfa-backend grant reviewer course:demo-private
uv run alfa-backend revoke reviewer course:demo-private
```

Доступ проверяется на каждом запросе. Обогащаются только разрешённые карточки; произвольные поля,
объяснения и ссылки алгоритма не передаются фронтенду. Если шаг плана недоступен, весь маршрут
возвращается пустым с `insufficient_evidence`: отфильтрованный план нельзя выдавать за исходный.

**Исходная PostgreSQL:** дамп не предоставлен, поэтому соответствия его таблиц актуальным ценам,
подпискам и публикациям не выдуманы. Чтобы посмотреть схему без чтения строк или изменения базы:

```bash
ALFA_DATABASE_URL='postgresql+psycopg://READONLY_USER:...@HOST/SOURCE_DB' \
  uv run alfa-backend inspect-source
```

После получения схемы надо написать конкретное преобразование источника в этот контракт и
организовать повторный импорт при изменении публикаций/цен. `materials.jsonl` алгоритма содержит
поля `*_snapshot` и сам по себе не подходит в качестве подтверждения прав. Ни CLI, ни старт API
не публикуют и не загружают исходные данные на GitHub.

## Публичный контракт

Префикс `/api/v1`; все методы, кроме регистрации, входа, `/health`, `/ready` и документации,
требуют `Authorization: Bearer <token>`. Полная схема и примеры типов — `/docs` и `/openapi.json`.

| Метод | Назначение |
|---|---|
| `POST /auth/register`, `/auth/login`, `/auth/logout` | Регистрация, токен с TTL, отзыв текущего токена |
| `GET /me` | Пользователь и сохранённый профиль |
| `PUT /me/profile` | Интересы и дополнительные поля профиля |
| `POST /me/events` | Событие с `event_id`, `generation`, `entity_key`, `action`, необязательным `position` |
| `GET /me/events` | Последние доступные события текущего пользователя и поколения |
| `GET /catalog` | `q`, `kind`, `limit`, `offset`; только опубликованные доступные карточки |
| `GET /suggest` | `q`, `limit`; проверенные подсказки модели (http) или названия каталога (demo) |
| `GET /search` | `q`, `kind`, `top`; selection_id + selection_generation либо clarification_token либо clarification_text |
| `POST /recommend` | `{"generation":"..."}`; профиль и история берутся сервером из БД |
| `POST /development-plan` | `{"generation":"..."}`; до трёх тематических шагов |

У `/health` и `/ready` префикса нет. `/health` проверяет БД/каталог; `/ready` дополнительно проверяет
версию и доступность внутреннего API. Успешная readiness-проверка не заменяет настоящий поиск.

Публичный контракт отличается от внутреннего API алгоритма. Фронтенду не надо отправлять
`viewed`/`completed` и обращаться напрямую к :8000. В http-режиме для подсказки передаются
исходный `q`, `selection_id` и `selection_generation`; в demo используется новый `q=label`.
Уточнение передаётся с исходным `q` через `clarification_token` либо `clarification_text`.
Произвольные диагностические данные алгоритма не раскрываются.

Порядок карточек сохраняется после проверки доступа, дублей нет. Список может быть коротким или
пустым. В http-режиме подсказки берутся из модели и проверяются по доступу; demo использует доступные названия.

Поля профиля `goal`, `industry`, `business_stage`, `experience`, `preferred_kinds`, `region`
сохраняются, но существующий внутренний HTTP `/recommend` их не принимает. В рекомендации
передаются только `categories` и история. Чтобы учитывать расширенный профиль в ML, нужна
отдельная интеграция Python `recommend_for_profile`; этот API её не имитирует.

События: `impression`, `clicked`, `viewed`, `interested`, `started`, `completed`.
Одинаковый `event_id` с тем же телом не создаёт дубль, с другим телом даёт 409. Показы/клики не
считаются завершением. `started` и `completed` допустимы только для курсов. События имеют
`source=self_reported`: это учебная отметка пользователя, не подтверждённая LMS-сертификация.
Клиент не может отправить покупку или выдать себе доступ. Интеграция платёжного провайдера,
подтверждённого LMS-прогресса и возвратов требует реальных источников и контрактов.

Ошибки: 401 — токен, 404 — материал недоступен, 409 — поколение/конфликт, 422 — входные поля,
429 — лимит, 502 — ошибка алгоритма, 503 — нет каталога/БД, 504 — таймаут. У ответа есть
`X-Request-ID`; логи не содержат паролей, запросов поиска, токенов или тел событий.

Для отдельного dev-фронтенда: `ALFA_CORS_ORIGINS=http://localhost:5173`; можно перечислить несколько
origin через запятую. По умолчанию cross-origin не разрешён, wildcard не используется.

## Проверки

```bash
cd backend
./ci.sh
```

Повторить те же тесты на **отдельной пустой PostgreSQL**:

```bash
ALFA_TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST/alfa_backend_test' \
  uv run python -m unittest discover -s tests -v
```

Тесты пересоздают только таблицы API в тестовой БД; имя БД обязательно должно оканчиваться `_test`.
Не указывать рабочую базу! По умолчанию ci.sh использует SQLite; PostgreSQL проверяется с ALFA_TEST_DATABASE_URL.

## Границы версии для хакатона

- Демо полностью автономно; реальный E5/CatBoost требует закрытых артефактов.
- Проверка доступа и цены опираются на последний доверенный импорт; автоматической синхронизации
  с неизвестной схемой исходного дампа нет.
- Нет платёжной системы, A/B-эксперимента, подтверждённых покупок и полного учебного графа.
  Продуктовые события сохраняются, но клики не объявляются продажами.
- Токены случайные, в БД только SHA-256; пароли — scrypt. Для публичной эксплуатации нужны HTTPS,
  политика регистрации и восстановления аккаунтов. Не передавать Bearer-токены по открытому HTTP.
- Лимит запросов хранится в памяти одного процесса; для нескольких воркеров нужен общий limiter.
  Профили, история, права и сессии хранятся в БД и переживают перезапуск.
- Текущий `/recommend` отдаёт максимум 5 результатов, план — 3; поиск запрашивает до 50 кандидатов,
  но после проверки прав заполнение списка не гарантируется.

## Структура

Код лежит непосредственно в `backend/`:

- `api/`: тонкие HTTP-обработчики, зависимости, middleware и обработчики ошибок.
- `services/`: сценарии приложения и Protocol-контракты репозитория, алгоритма и паролей.
- `domain/`: сущности, контракты ответов и собственный `AppError`.
- `repositories/`: SQL-запросы и транзакции, преобразование ORM в независимые сущности.
- `infrastructure/`: SQLAlchemy-модели, UoW, подключение к БД, HTTP-клиент алгоритма и scrypt.
- `app.py`: сборка зависимостей и управление ресурсами.
- `config/settings.py`: настройки приложения и чтение окружения.
- `schemas/requests.py`: проверяемые DTO входных данных.

Сервисы не импортируют FastAPI, SQLAlchemy, инфраструктуру или реализацию репозитория.
API получает сервис через Depends; сервис получает реализации Protocol в composition root.
Объекты ORM не выходят из репозитория. Проверка `mypy --strict` включена в `ci.sh`.

Единый контракт ошибок (вместо прежнего `detail`):

```json
{"error": {"code": "unauthorized", "message": "Authentication required", "details": null}}
```

Валидация возвращает тот же конверт с безопасными `loc`, `msg`, `type` в `details`,
без исходных значений пароля. Клиентам нужно читать `error.message` и `error.code`.

## Транзакции через Unit of Work

`UnitOfWorkPort` задаёт контракт, `SqlAlchemyUnitOfWork` управляет сессией, commit,
rollback и закрытием. Репозитории выполняют только flush. Сервис явно вызывает
commit после завершения операции; при выходе из UoW незакоммиченные изменения
откатываются, включая исключения. Регистрация и выпуск токена атомарны.
CLI импорта и управления правами использует тот же UoW.

## Границы слоёв и подмена хранилища

HTTP-маршруты вызывают отдельные сервисы: `AuthService`, `ProfileService`,
`CatalogService`, `ActivityService`, `SearchService`, `RecommendationService`
и `HealthService`. Общий `RecommendationContext` собирает доступный пользователю
каталог и ML-порт; проверки generation вынесены в `services/validation.py`.

Контракты в `domain/ports.py` описаны через `typing.Protocol`:

- `UserRepository` — пользователи, токены и профиль;
- `CatalogRepository` — generation, импорт и видимые материалы;
- `ActivityRepository` — события и история обучения;
- `TransactionPort` — фиксация операции;
- `UnitOfWorkPort` — репозитории `users`, `catalog`, `activity`, commit/rollback
  и жизненный цикл транзакции;
- `UnitOfWorkFactory` — создание Unit of Work для запроса;
- `RecommendationPort` и `PasswordPort` — ML и хеширование паролей.

Сервисы получают узкие контракты через конструкторы и не импортируют SQLAlchemy,
конкретные репозитории или FastAPI. SQL-адаптер реализует три контракта хранилища
на одной сессии, сохраняя атомарность регистрации пользователя и выдачи токена.
FastAPI переиспользует один Unit of Work в пределах запроса, включая авторизацию.
При выходе он откатывает незавершённые изменения и закрывает сессию.

Для другого хранилища реализуйте `UnitOfWorkPort` и передайте фабрику:

```python
app = create_app(settings, uow_factory=MyUnitOfWork)
```

При переданной фабрике приложение не создаёт SQLAlchemy engine и не инициализирует
SQL-таблицы. Реализация должна возвращать доменные сущности, обеспечивать атомарный
commit и rollback при выходе. Пример подмены через публичный API без SQL находится
в `tests/test_service_contracts.py`.

Инверсия зависимостей: `domain/ports.py` принадлежит внутреннему слою.
Сервисы и адаптеры импортируют эти контракты; домен не импортирует реализации.
Входные DTO находятся в `domain/commands.py`, `schemas/requests.py` сохраняет
совместимые экспорты. `services/dependencies.py` содержит типизированный набор
зависимостей, который собирается в `app.py`. В `create_app` можно передать
`uow_factory`, `recommender`, `passwords` и `demo_factory`. API не зависит от
SQLAlchemy: Unit of Work преобразует ошибки драйвера в доменную ошибку.
Направление импортов проверяется в `tests/test_architecture.py`.

Singleton ML — `infrastructure/python_recommender.py`, класс `PythonRecommender`.
`__new__` под `_load_lock` создаёт и публикует `_instance` после успешной загрузки
`SearchEngine` и `relevance_backend()`. Повторный вызов возвращает тот же экземпляр;
модель загружается один раз на процесс. Выбирается через `ALFA_RECO_MODE=python`
в точке сборки `app.py`; сервисы работают через `RecommendationPort`.
