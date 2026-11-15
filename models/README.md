# Модели рекомендательной системы

Локальный комплект находится в `models/recommender/`. Здесь вместе хранятся
E5-small, CatBoost, токенизатор, векторы и совместимый каталог одной версии.

```text
models/
├── README.md
├── recommender/                 # исходный совместимый комплект
│   ├── encoder/                 # E5-small и токенизатор
│   ├── catalog/
│   │   ├── CURRENT.json         # активное поколение
│   │   └── generation-.../
│   │       ├── catalog.json
│   │       ├── manifest.json
│   │       ├── suggestions.json
│   │       └── relevance/
│   │           ├── CURRENT.json
│   │           └── model-.../
│   │               ├── ranker.cbm
│   │               ├── vectors.npz
│   │               ├── normalized_catalog.json
│   │               └── manifest.json
│   └── handoff_manifest.json    # версии и контрольные суммы
└── runtime/                     # отдельная запускаемая копия, создаётся скриптом
```

Названия внутренних файлов и каталогов поколений сохраняются: их использует
загрузчик, а манифесты проверяют совместимость и контрольные суммы. Выносить
`ranker.cbm` или E5 отдельно из комплекта не нужно.

`recommender/` включён в репозиторий; `encoder/model.safetensors` хранится через Git LFS.
Перед использованием выполните `git lfs install` и `git lfs pull`. `runtime/` — локальная
копия и исключена из Git. В комплекте нет исходной базы или пользовательских данных.

## Запуск из корня проекта

Подготовить окружение модели, если оно ещё не создано:

```bash
uv venv --python 3.12 05_code/.venv
uv pip install --python 05_code/.venv/bin/python -e ./05_code -r 05_code/requirements-relevance.txt
```

Создать новую runtime-копию и запустить отдельный сервис модели:

```bash
python3 backend/scripts/model_runtime.py \
  --runtime models/runtime \
  --python 05_code/.venv/bin/python \
  --port 8000
```

Путь `--bundle` по умолчанию — `models/recommender`, независимо от текущей папки.
Можно передать другой комплект явно. `--runtime` должна быть новой папкой.
Скрипт проверяет исходный комплект, копирует его, обновляет encoder_path официальным
`--relocate` и запускает relevance-поиск с E5/CatBoost без LLM и скачивания весов.

Для последующих запусков готовой runtime-копии:

```bash
PYTHONPATH=05_code/src HF_HUB_OFFLINE=1 05_code/.venv/bin/python -m alfa_reco serve \
  --output models/runtime/catalog --relevance --no-llm --port 8000
```

Бэкенд подключается через `ALFA_RECO_MODE=http` и
`ALFA_RECO_URL=http://127.0.0.1:8000`. Его доверенный каталог должен иметь ту же
generation; ML-снимок не подтверждает текущие права и цены.

Проверка интеграции из `backend/`:

```bash
ALFA_REAL_RECO_URL=http://127.0.0.1:8000 \
ALFA_REAL_BUNDLE=../models/recommender \
uv run python -m unittest discover -s tests -p test_real_model.py -v
```

После переноса комплекта на другую машину или в другую папку используйте
`05_code/scripts/prepare_backend_bundle.py --relocate ПУТЬ`, а затем `--verify ПУТЬ`.
Манифесты вручную не редактируются.

Для локальной проверки FastAPI с настоящей моделью без актуального каталога сайта есть
[отдельная тестовая база и сквозной сценарий](../backend/INTEGRATION_CHECK.md).
Права доступа в этой базе искусственные; цены и ссылки неизвестны.
