# Проверка интерфейса интересов — 15 ноября 2026

Проверка выполнена в каталоге `integrated/05_code` с локальным Python модели и совместимым
bundle в `integrated/models/runtime`. Исходный E5, ранжировщик и манифесты не менялись.

```sh
PYTHONPATH=src HF_HUB_OFFLINE=1 ../../05_code/.venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src ../../05_code/.venv/bin/python scripts/prepare_backend_bundle.py --verify ../models/runtime
../../05_code/.venv/bin/ruff check src/alfa_reco/interests.py src/alfa_reco/personalization.py src/alfa_reco/cold_start.py src/alfa_reco/server.py tests/test_interests.py tests/test_interest_recommendations.py tests/test_api.py
```

Результат: **262 теста прошли без пропусков**, bundle прошёл проверку, ruff — без ошибок.
В `backend` дополнительно выполнен `ALFA_REAL_RECO_URL=http://127.0.0.1:18000
ALFA_REAL_BUNDLE=../models/runtime .venv/bin/python -m unittest discover -s tests -v`:
**37 тестов прошли без пропусков**. Комплект и сервер были доступны локально.

HTTP-проверка обновлённого алгоритма на реальном bundle ранее в этом сеансе: каталог
содержит 5 категорий и 18 тем; одиночные «Развитие бизнеса» и «Старт бизнеса» вернули
по 5 разных результатов, обе темы вместе — 5, все отвечают выбранным темам. Просмотренный
ID исключён; category-only сохранил порядок старого `/recommend`. Устаревшее поколение
и тема из другой категории возвращают HTTP 400. Старые `/search`, `/suggest` и
`/development-plan` ответили успешно. Юнит- и HTTP-тесты покрывают OR, пустые ответы,
отбор до top-5, контроль типов/дублей/полей, конфигурацию, источники и ограничения прав.

Это тест локального интерфейса. Согласование транспорта и подключение публичного API
бэкенда с командой не выполнены; актуальная фильтрация прав и оферт остаётся на платформе.
