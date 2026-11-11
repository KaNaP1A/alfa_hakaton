# Импорт, гибридный поиск и подсказки

**Экспериментальный этап 3:** [оценка, полные тексты и CatBoost](README_STAGE3.md). Ниже сохранено описание предыдущего этапа, включая его ограничения; фактические результаты этапа 3 приведены отдельно.

**Локальный интерфейс:** дважды нажмите `Запустить демо.command`, затем откройте http://127.0.0.1:8000. [Инструкция и возможности](docs/LOCAL_UI.md).

Рабочий первый этап алгоритма: чтение PostgreSQL backup, локальная база всех исходных таблиц, нормализованный каталог и поиск BM25 + локальные embeddings + RRF.

Подсказки, уроки и HTTP API реализованы. См. [полное описание этапа и контракт для фронтенда](docs/AUTOCOMPLETE.md) и [отчёт проверки второго этапа](STAGE2_REPORT.md).

```bash
PYTHONPATH=src python3 -m alfa_reco suggest "открыть коф"
PYTHONPATH=src python3 -m alfa_reco serve --port 8000
```

## Что уже проверено

- Импортированы **62 таблицы, 102 128 строк**.
- В каталог включены **1 469 карточек**: 834 статьи, 26 курсов, 247 документов, 351 термин, 8 подкастов, 3 вебинара.
- Подготовлены 384-мерные embeddings; поиск выполняется локально.
- Повторный импорт воспроизводит контрольные хеши каталога и SQLite, сохраняет совместимый векторный индекс.
- Тесты и запросы описаны в [отчёте запуска](RUN_REPORT.md).

В этой версии `build` импортирует все COPY-таблицы в **SQLite**, не поднимая PostgreSQL-сервер. Все исходные поля сохраняются как TEXT/NULL; исходные индексы, ограничения и PostgreSQL-типы не воспроизводятся. Это безопасная локальная копия данных для исследования и поиска. SQL/JS из записей не исполняется. Для нативного PostgreSQL отдельно подготовлен рецепт Docker ниже; он здесь не запускался, Docker отсутствует.

## Быстрый запуск на этом компьютере

Откройте терминал в `05_code`. Подготовленные данные уже находятся в `artifacts/catalog/`.

```bash
PYTHONPATH=src python3 -m alfa_reco search "Хочу открыть кофейню"
PYTHONPATH=src python3 -m alfa_reco search "Как повысить лояльность сотрудников"
PYTHONPATH=src python3 -m alfa_reco search "Нужен шаблон договора аренды" --kind document
PYTHONPATH=src python3 -m alfa_reco search "Frontend" --mode bm25
PYTHONPATH=src python3 scripts/run_examples.py
```

Результат JSON содержит реальные названия, темы, типы, source ranks, BM25/cosine/RRF и пометки неопределённости. Это внутренние оценки поиска, не вероятности покупки. `unmatched_query_terms` показывает слова/нормализованные формы без буквального совпадения; это диагностический сигнал, а не доказательство отсутствия смыслового ответа.

## Повторить импорт из исходного backup

На этом Mac сохранён локально собранный PostgreSQL 17.6 `pg_restore` и его библиотека. Они находятся в `artifacts/tools/`, исключены из Git и не являются переносимыми бинарниками для Linux/Windows.

```bash
PYTHONPATH=src python3 -m alfa_reco build \
  --backup ../02_data/raw/alfa_course_hackathon.backup \
  --pg-restore ./artifacts/tools/pg_restore \
  --output artifacts/catalog
```

На другом компьютере установите PostgreSQL client tools 17 и используйте `--pg-restore pg_restore`. Требуется Python 3.11 или новее; импорт и BM25 не требуют Python-зависимостей. Протестировано на локальном Python 3.13.

Программа сначала строит поколение во временной директории, проверяет целостность SQLite и хеши, затем переключает `CURRENT.json`. Сбой нового импорта не переключает рабочую версию. Одновременные build/embed для одной директории отклоняются файловой блокировкой (macOS/Linux).

## Установка semantic-зависимостей на новом компьютере

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-semantic.txt
PYTHONPATH=src python -m alfa_reco embed --output artifacts/catalog
```

Модель: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Первый запуск без `--model-path` скачает эту ревизию. На этом компьютере использован существующий локальный snapshot; его путь зафиксирован в manifest. При переносе пересоберите embeddings на новом компьютере или передайте `embed --model-path /absolute/path/to/model`. Нельзя подменять модель запроса другой моделью без пересчёта каталога.

Основные библиотеки зафиксированы в requirements; это не полный lock транзитивных зависимостей для всех платформ. Подбор лучшей retrieval-модели и переносимый lock остаются следующими задачами. Обработка queries и каталога локальная; внешние LLM API не используются.

## Docker для импорта и BM25

```bash
docker build -t alfa-reco-stage1 .
docker run --rm \
  -v "$PWD/../02_data/raw:/input:ro" \
  -v "$PWD/artifacts:/artifacts" \
  alfa-reco-stage1 build --backup /input/alfa_course_hackathon.backup --output /artifacts/catalog
docker run --rm -v "$PWD/artifacts:/artifacts" \
  alfa-reco-stage1 search "договор аренды" --output /artifacts/catalog --mode bm25
```

Этот образ намеренно содержит только импорт и lexical search. Для hybrid нужны semantic-зависимости/модель. Docker-рецепт не проверен запуском в текущем окружении.

## Нативное восстановление PostgreSQL

```bash
cp .env.example .env
# Задайте свой локальный POSTGRES_PASSWORD в .env.
sh scripts/restore_postgres.sh
```

Скрипт запускает PostgreSQL 17.6, проверяет, что public-схема пустая, и выполняет транзакционное восстановление схемы и данных из backup. Уже существующие таблицы не перезаписывает. База не публикует TCP-порт наружу; доступ через `docker compose exec db psql -U alfa -d alfa`. Секреты не коммитить. Рецепт предоставлен, но его фактический запуск ещё не проверен.

## Каталог и ограничения первого этапа

- Используются название, описание, существующие темы, теги и отрасли. HTML очищается, script/style удаляются.
- Полные тексты закрытых уроков, ArticleEmbedItems и LessonEmbedItems не используются в поисковом индексе этого этапа.
- Черновики, удалённые и `IsClosed=true` исключены консервативно.
- Калькуляторы сохранены в исходной SQLite, но не вошли в поисковый каталог: в их таблице нет подтверждённого статуса публикации. 235 допустимых связей уроков включены в поисковый текст курсов; отдельные карточки уроков не создаются.
- `Published=null` у опубликованных документов не блокирует включение.
- Тип доступа не равен цене или подтверждённому праву пользователя. `free_only` пока явно отклоняется вместо ложной фильтрации.
- Поле source_url сохраняется без изменений. canonical_url заполняется только для абсолютного HTTPS URL домена kurs.alfabank.ru; относительные slug не превращаются в придуманный адрес. Доступность URL по сети не проверялась.
- Это CLI для исследования кандидатов, не готовая публичная выдача: карточки с непроверенной ссылкой показываются с флагом url_unverified.
- Нормализация русских окончаний — лёгкая эвристика, не полноценная лемматизация.
- BM25 k1=1.5, b=0.75; title повторён дважды; RRF k=60, равные вклады, до 60 кандидатов на источник. Это стартовый baseline, не подобранные веса.
- Dense-канал всегда находит ближайшие векторы даже вне темы. Поле coverage остаётся unknown, пока не настроен gate по разметке. Не считать каждую выдачу релевантной автоматически.
- Подсказки и локальный HTTP API реализованы. CatBoost, персонализация и LLM ещё не подключены.

## Файлы

- `src/alfa_reco/cli.py` — импорт и команды; поиск, уроки и подсказки вынесены в отдельные модули.
- `tests/test_pipeline.py` — проверки чтения COPY, безопасности ссылок, очистки и lexical search.
- `scripts/run_examples.py` — несколько фактических поисковых запросов.
- `artifacts/catalog/CURRENT.json` — активное поколение.
- `artifacts/catalog/generation-*/source.sqlite` — все исходные таблицы, закрытые данные остаются локальными.
- `artifacts/catalog/generation-*/catalog.json` — нормализованный каталог.
- `artifacts/catalog/generation-*/manifest.json` — версии, количества, хеши и причины исключения.
- `artifacts/catalog/generation-*/vectors.npy` — локальные embeddings.
- `artifacts/search_examples.json` — результаты примеров.

`artifacts/` содержит исходные и производные данные и должен оставаться вне публичного Git. [Спецификация](../04_docs/architecture/ALGORITHM_SPEC.md) и [навигация](../README.md).

## Тесты

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
