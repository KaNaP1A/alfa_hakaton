# Локальный поиск и рекомендации Alfa

**Новое:** [как обучена ML и что показал новый синтетический подбор](docs/ML_AND_SYNTHETIC_HOLDOUT_2026-11-12.md). Также: [1000 сценариев + 120 сложных, разметка и ограничения](docs/CHALLENGE_1000_2026-11-12.md). Для поиска, проверки просмотров и разметки откройте **`Открыть лабораторию.command`**. Повторное обучение — `Обучить ML локально.command`.

Проект импортирует PostgreSQL backup в SQLite, строит каталог, подсказки и поисковые индексы. Есть BM25, гибрид BM25 + embeddings, экспериментальный CatBoost и ансамбль. Отдельная эвристика главной страницы учитывает выбранные направления и локальные интересы; история пользователя не передаётся в поиск по задаче.

Снимок содержит 1469 карточек; поиск показывает 1118 после исключения 351 термина. Это локальный прототип. Цены, права пользователя и доступность URL не подтверждены онлайн.

## Запуск на этом компьютере

Все команды ниже выполняются из `05_code`. Дважды нажмите `Запустить демо.command` или запустите:

```bash
PYTHONPATH=src .venv/bin/python -m alfa_reco serve --hybrid --no-llm --open-browser --port 0
```

Порт выбирается автоматически. Для включения локального разбора Gemma уберите `--no-llm`; он требует Ollama. В установленном ансамбле `llm_boost=0`, поэтому разбор не меняет порядок. Терминал остаётся открытым; остановка — Ctrl+C.

Лаборатория с одним поисковым профилем: `serve --relevance --no-llm --open-browser --start-page /lab --port 0`. Она не требует генеративной LLM. Другие алгоритмы доступны для локальных экспериментов отдельно от пользовательского интерфейса.

```bash
PYTHONPATH=src .venv/bin/python -m alfa_reco search "налоги ИП" --mode hybrid --no-llm
PYTHONPATH=src .venv/bin/python -m alfa_reco search "договор аренды" --mode bm25 --kind document
PYTHONPATH=src .venv/bin/python -m alfa_reco suggest "открыть коф"
```

CLI по умолчанию использует экспериментальный `ensemble`, которому нужны embeddings, CatBoost и совместимые веса. Для самостоятельного лексического режима укажите `--mode bm25`. API без загруженных embeddings по умолчанию использует BM25; при `serve --hybrid` — ансамбль. Неподготовленный режим возвращает ошибку, а не случайные результаты. Интерфейс рассчитан на подготовленный ансамбль.

## Установка на другом компьютере

Требуется Python 3.11+; файловые блокировки импорта рассчитаны на macOS/Linux. Импорт, BM25 и подсказки работают на стандартной библиотеке.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -r requirements-dev.txt
# Для hybrid и экспериментов:
.venv/bin/python -m pip install -r requirements-semantic.txt -r requirements-rank.txt
```

Зафиксированы верхнеуровневые версии, полного переносимого lock-файла транзитивных зависимостей пока нет. Не копируйте `.venv` с другого компьютера.

## Импорт и embeddings

Исходный backup передаётся извне. PostgreSQL client tools 17 должны содержать `pg_restore`.

```bash
PYTHONPATH=src .venv/bin/python -m alfa_reco build \
  --backup /absolute/path/alfa_course_hackathon.backup \
  --pg-restore pg_restore --output artifacts/catalog
PYTHONPATH=src .venv/bin/python -m alfa_reco embed --output artifacts/catalog
```

Первый `embed` может скачать закреплённую ревизию `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Для полностью локальной загрузки передайте `--model-path /absolute/path/to/model`. Векторы запроса и каталога должны использовать одну модель. На текущем компьютере инструменты и модели уже есть локально; `artifacts/tools/pg_restore` не является переносимым бинарником.

Импорт сохраняет 62 таблицы/102128 строк как TEXT/NULL в SQLite, без восстановления PostgreSQL-типов и ограничений. Значения не исполняются как SQL/JS. Новое поколение публикуется через `CURRENT.json` после проверки хешей. Одновременные `build/embed` запрещены. `embed` обновляет несколько файлов существующего поколения: **остановите сервер перед пересчётом**; атомарная публикация всего embedding-комплекта ещё не реализована.

Полные тексты индексируются только по консервативной политике открытости. Уроки прикрепляются к курсам после проверки binding и предков. Условия допуска и уточнений: [RESULT_POLICY](docs/RESULT_POLICY_2026-11-12.md), [подсказки и уроки](docs/AUTOCOMPLETE.md). `free_only` отклоняется: проверенного фильтра бесплатности нет.

## Подготовка экспериментального CatBoost и ансамбля

Для нового каталога нужны собственные совместимые артефакты:

```bash
PYTHONPATH=src .venv/bin/python scripts/large_experiment.py --install-small
PYTHONPATH=src .venv/bin/python scripts/ensemble_experiment.py --install
```

Обучение использует слабую синтетику и не доказывает качество для людей. Второй скрипт — исторический подбор по внутренним спискам; итоговую выдачу проверяйте через новый аудит ниже. Его предварительные веса не следует объявлять оптимальными. Имена рабочих файлов: `catboost_small.cbm`, `catboost_small_meta.json`, `ensemble_config.json` в активном поколении. [Объяснение установленной модели](docs/MODEL_EXPLAINED.md).

## Проверки и подбор BM25

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests scripts
.venv/bin/ruff check src --extend-select S
.venv/bin/ruff format --check src tests scripts
PYTHONPATH=src HF_HUB_OFFLINE=1 .venv/bin/python scripts/audit_ranking.py \
  --phase full --output evaluation/my_new_audit
PYTHONPATH=src .venv/bin/python scripts/audit_training_data.py \
  --output evaluation/my_training_audit.json
```

Каталог и embeddings должны быть подготовлены. Для аудита нужен совместимый CatBoost; LLM в нём отключена. Папка вывода должна быть новой. `baseline` проверяет четыре режима, 193 запроса, 64 пары, отсутствие ответа и BM25 на 50000 документов; `calibrate` отдельно подбирает параметры на validation. Тесты API требуют доступ к loopback-порту.

Результат подбора сохраняется как `selected_config.json`, автоматически не устанавливается. Его можно использовать через `SearchEngine.search(..., ranking_config=RankingConfig(...))` для эксперимента. При ручном переносе в `ranking_config.json` активного поколения требуется перезапуск сервера. Изменение `bm25_k1/bm25_b` требует переобучения CatBoost и пересчёта весов ансамбля; несовместимые параметры отклоняются.

[Результаты аудита](docs/RANKING_AUDIT_2026-11-12.md), [ML и синтетические данные](docs/ML_DATA_PLAN.md), [методика оценки](evaluation/README.md), [инструкция разметки](docs/ANNOTATION_GUIDE.md).

## HTTP API

Локальный сервер слушает `127.0.0.1`, проверяет Host/Origin и не записывает запросы в access log. Маршруты: `GET /health`, `/suggest`, `/search`, `/catalog`, `/lab/data`, `/lab/pool`, `/lab/template`; `POST /recommend`. `/lab` — интерфейс лаборатории. JSON содержит исходный запрос, результаты, альтернативы, уточнение и диагностические скоры. `top` — максимум, а не обязательное число результатов. Скор не является вероятностью. Исходный запрос и выбранный фокус возвращаются раздельно.

Это development-сервер. Docker-рецепт и нативное восстановление PostgreSQL сохранены в `Dockerfile`, `compose.yaml`, `scripts/restore_postgres.sh`, но в этом аудите не запускались. Дамп, SQLite, векторы, локальные профили и секреты не публикуются.
