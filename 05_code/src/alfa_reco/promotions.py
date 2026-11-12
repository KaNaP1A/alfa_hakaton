"""Benefit-led copy from reviewed catalog facts, with a conservative title fallback."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path


def content_fingerprint(item):
    return hashlib.sha256(
        json.dumps([item["title"], item.get("description", "")], ensure_ascii=False).encode()
    ).hexdigest()


@lru_cache(maxsize=1)
def reviewed_copy():
    return json.loads(Path(__file__).with_name("promotion_copy.json").read_text())


def promotion_for(item):
    copy = reviewed_copy().get(item["entity_key"])
    if copy and copy["source_sha256"] == content_fingerprint(item):
        return {
            "text": copy["text"],
            "source": "reviewed_catalog_copy",
            "source_fields": ["title", "description"],
        }
    title = item["title"].rstrip(" .!?")
    if title.startswith("Можно ли "):
        text = f"Разберитесь, можно ли {title[9:10].lower() + title[10:]}. Изучите вопрос до того, как принимать решение."
    elif title.startswith("Как "):
        text = f"Разберитесь, как {title[4:5].lower() + title[5:]}. Откройте материал и начните с понятного вам шага."
    elif item["kind"] == "document":
        text = "Нужен документ для рабочей задачи? Ознакомьтесь с этим образцом и проверьте, подходит ли он для вашей ситуации."
    elif item["kind"] == "course":
        text = "Выберите время для обучения и переходите к разбору темы. Откройте программу курса, чтобы выбрать первый шаг."
    else:
        text = f"Погрузитесь в тему «{title}». Откройте материал, чтобы перейти от общего интереса к подробностям."
    return {"text": text, "source": "title_template", "source_fields": ["title"]}
