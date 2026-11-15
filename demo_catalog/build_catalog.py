"""Build a private, explicitly fictional/public local demo catalogue and reconciliation audit."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

TOPICS = [
    ("Финансы", "Денежный поток: от плана к действию", "Составьте учебный план управления поступлениями и расходами.", 2990),
    ("Маркетинг", "Продвижение продукта: практикум", "Разберите гипотетический план продвижения продукта.", 2490),
    ("Команда", "Управление командой: учебный маршрут", "Разберите примеры постановки задач и обратной связи.", 1990),
    ("Бизнес", "Запуск проекта: первые шаги", "Учебный пример выбора идеи и составления плана запуска.", 3490),
    ("Продажи", "Работа с клиентами: практикум", "Учебные упражнения по общению с клиентами.", 2790),
    ("Технологии", "Данные для малого бизнеса", "Учебный пример работы с показателями бизнеса.", 2290),
]


def build(public_path, old_path):
    old_data = json.loads(Path(old_path).read_text(encoding="utf-8"))
    old = old_data.get("materials", []) if isinstance(old_data, dict) else old_data
    historical = {x["entity_key"]: x for x in old if x.get("entity_key")}
    rows, seen_urls, keys = [], set(), set()
    titles = Counter()
    source_ids = Counter()
    stats = Counter()
    kinds = Counter()
    for line in Path(public_path).read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        data = json.loads(line)
        stats["source_rows"] += 1
        url = data.get("source_url", "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "kurs.alfabank.ru" or parsed.username or parsed.password:
            raise ValueError("Unexpected source URL")
        if url in seen_urls:
            raise ValueError("Duplicate source URL")
        seen_urls.add(url)
        if data.get("source_noindex_raw") is True:
            stats["excluded_noindex"] += 1
            continue
        kind, title, description = data.get("kind"), data.get("title"), data.get("description")
        if kind not in {"article", "course", "document", "podcast", "webinar", "calculator"} or not isinstance(title, str) or not title.strip():
            stats["excluded_invalid"] += 1
            continue
        source_id = data.get("source_id")
        key = data.get("entity_key")
        if key and key != f"{kind}:{source_id}":
            raise ValueError("Inconsistent source identifier")
        identity_match = bool(key and key in historical and historical[key].get("kind") == kind)
        titles[(kind, " ".join(title.casefold().split()))] += 1
        if key:
            source_ids[key] += 1
        stats["missing_description"] += not bool(description)
        stats["missing_observed_at"] += not bool(data.get("observed_at"))
        stats["exact_historical_id_matches"] += identity_match
        stats["missing_source_id"] += not bool(source_id)
        stats["no_historical_match"] += not identity_match
        # A stable demo ID is not a confirmed platform entity mapping.
        demo_id = "public:" + hashlib.sha256(url.encode()).hexdigest()[:24]
        if demo_id in keys:
            raise ValueError("Duplicate demo ID")
        keys.add(demo_id)
        rows.append({
            "id": demo_id, "kind": kind, "title": title.strip(), "description": description or "",
            "origin": "public_snapshot", "source_url": url, "source_id": source_id,
            "historical_id_match": identity_match, "observed_at": data.get("observed_at"),
            "price": {"status": "unknown"}, "publication": "unknown", "access": "unknown",
            "offer": "unknown", "subscription_price": "unknown", "purchase_price": "unknown",
            "user_access": "unknown", "parent_course": "unknown", "topics": [],
            "provenance": {"source": url, "observed_at": data.get("observed_at"),
                           "source_type": "public_page_html", "title_source": data.get("title_source"),
                           "fields": ["title", "description"]},
        })
        kinds[kind] += 1
    for index, (topic, title, description, price) in enumerate(TOPICS, 1):
        rows.append({"id": f"synthetic:course:{index}", "kind": "course", "title": title,
                     "description": description, "origin": "synthetic", "source_url": None,
                     "source_id": None, "observed_at": None, "publication": "fictional",
                     "access": "fictional", "offer": "fictional", "topics": [topic],
                     "price": {"status": "fictional", "amount": price, "currency": "RUB"}})
        rows.append({"id": f"synthetic:article:{index}", "kind": "article",
                     "title": f"{topic}: с чего начать", "description": "Вымышленный вводный материал для демонстрации рекомендаций.",
                     "origin": "synthetic", "source_url": None, "source_id": None,
                     "observed_at": None, "publication": "fictional", "access": "fictional",
                     "offer": "fictional", "topics": [topic], "price": {"status": "fictional_free"}})
    report = {"public": dict(stats), "public_by_kind": dict(kinds), "synthetic": len(TOPICS) * 2,
              "total": len(rows), "public_sha256": hashlib.sha256(Path(public_path).read_bytes()).hexdigest(),
              "historical_sha256": hashlib.sha256(Path(old_path).read_bytes()).hexdigest(),
              "duplicate_title_groups": sum(n > 1 for n in titles.values()),
              "duplicate_source_id_groups": sum(n > 1 for n in source_ids.values()),
              "limitations": "Public snapshot is incomplete; current publication, offers, prices and user access are unverified. Exact historical ID matches are candidates, not proof of current identity. Synthetic records are fictional."}
    return {"version": 1, "items": rows, "audit": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", required=True, type=Path)
    parser.add_argument("--historical", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    catalog = build(args.public, args.historical)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(catalog, stream, ensure_ascii=False)
    print(json.dumps(catalog["audit"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
