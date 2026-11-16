"""Build a private, explicitly fictional/public local demo catalogue and reconciliation audit."""

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

TOPICS = [
    (
        "Финансы",
        "Денежный поток: от плана к действию",
        "Составьте учебный план управления поступлениями и расходами.",
        2990,
    ),
    (
        "Маркетинг",
        "Продвижение продукта: практикум",
        "Разберите гипотетический план продвижения продукта.",
        2490,
    ),
    (
        "Команда",
        "Управление командой: учебный маршрут",
        "Разберите примеры постановки задач и обратной связи.",
        1990,
    ),
    (
        "Бизнес",
        "Запуск проекта: первые шаги",
        "Учебный пример выбора идеи и составления плана запуска.",
        3490,
    ),
    (
        "Продажи",
        "Работа с клиентами: практикум",
        "Учебные упражнения по общению с клиентами.",
        2790,
    ),
    (
        "Технологии",
        "Данные для малого бизнеса",
        "Учебный пример работы с показателями бизнеса.",
        2290,
    ),
]


def normalize_title(title):
    quoted = re.search(r"«([^»]+)»", title)
    if quoted and title.lstrip().startswith("Курс «"):
        suffix = re.split(r"\s+—\s+", title[quoted.end() :], maxsplit=1)[0].strip(" ,")
        title = " ".join(part for part in (quoted.group(1), suffix) if part)
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", title).casefold()))


PRICE_BANDS = {
    "course": (2990, 3990, 5490, 9900, 14990, 19900, 29900, 54900),
    "webinar": (990, 1490, 1990, 2990, 3990),
    "lesson": (490, 790, 990, 1490, 1990),
    "podcast": (390, 590, 790, 990, 1490),
    "calculator": (390, 590, 790, 990, 1490),
}


def simulated_offer(item, observations):
    """Attach fictional price/cost without changing snapshot price or entitlement."""
    if item["kind"] not in PRICE_BANDS:
        return None
    digest = hashlib.sha256(item["id"].encode("utf-8")).digest()
    choices = PRICE_BANDS[item["kind"]]
    price = choices[int.from_bytes(digest[:4], "big") % len(choices)]
    reference = (
        observations.get(normalize_title(item["title"]))
        if item["kind"] == "course"
        else None
    )
    if reference:
        price = reference["observed_price_rub"]
    ratio = (25, 35, 45, 55, 65)[digest[4] % 5]
    cost = int(round(price * ratio / 100 / 10) * 10)
    return {
        "price_rub": price,
        "cost_rub": cost,
        "kind": "fictional_simulation",
        "source": "historical_title_match_unverified" if reference else "generated",
        "reference": reference,
    }


def build(public_path, old_path, calculators_path=None, observations_path=None):
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
        if (
            parsed.scheme != "https"
            or parsed.hostname != "kurs.alfabank.ru"
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Unexpected source URL")
        if url in seen_urls:
            raise ValueError("Duplicate source URL")
        seen_urls.add(url)
        if data.get("source_noindex_raw") is True:
            stats["excluded_noindex"] += 1
            continue
        kind, title, description = (
            data.get("kind"),
            data.get("title"),
            data.get("description"),
        )
        if (
            kind
            not in {"article", "course", "document", "podcast", "webinar", "calculator"}
            or not isinstance(title, str)
            or not title.strip()
        ):
            stats["excluded_invalid"] += 1
            continue
        source_id = data.get("source_id")
        key = data.get("entity_key")
        if key and key != f"{kind}:{source_id}":
            raise ValueError("Inconsistent source identifier")
        identity_match = bool(
            key and key in historical and historical[key].get("kind") == kind
        )
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
        rows.append(
            {
                "id": demo_id,
                "kind": kind,
                "title": title.strip(),
                "description": description or "",
                "origin": "public_snapshot",
                "source_url": url,
                "source_id": source_id,
                "historical_id_match": identity_match,
                "observed_at": data.get("observed_at"),
                "price": {"status": "unknown"},
                "publication": "unknown",
                "access": "unknown",
                "offer": "unknown",
                "subscription_price": "unknown",
                "purchase_price": "unknown",
                "user_access": "unknown",
                "parent_course": "unknown",
                "topics": [],
                "provenance": {
                    "source": url,
                    "observed_at": data.get("observed_at"),
                    "source_type": "public_page_html",
                    "title_source": data.get("title_source"),
                    "fields": ["title", "description"],
                },
            }
        )
        kinds[kind] += 1
    # The public page crawl covered neither webinars nor calculators. Restore the
    # calculators from the embedded public list and webinars from the backup.
    restored = Counter()
    seen_entity_keys = {
        f"{x['kind']}:{x['source_id']}" for x in rows if x.get("source_id")
    }
    if calculators_path:
        for line in Path(calculators_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            key = item.get("entity_key")
            if item.get("kind") != "calculator" or not key or key in seen_entity_keys:
                continue
            source_url = item.get("source_page", "")
            if (
                urlsplit(source_url).scheme != "https"
                or urlsplit(source_url).hostname != "kurs.alfabank.ru"
            ):
                raise ValueError("Unexpected calculator source")
            seen_entity_keys.add(key)
            rows.append(
                {
                    "id": "public-calculator:"
                    + hashlib.sha256(key.encode()).hexdigest()[:24],
                    "kind": "calculator",
                    "title": item["title"],
                    "description": item.get("description") or "",
                    "origin": "public_snapshot",
                    "source_url": source_url,
                    "source_id": item.get("source_id"),
                    "historical_id_match": key in historical,
                    "historical_entity_key": key if key in historical else None,
                    "observed_at": item.get("observed_at"),
                    "publication": "unknown",
                    "access": "unknown",
                    "offer": "unknown",
                    "topics": [],
                    "price": {"status": "unknown"},
                    "provenance": {
                        "source": source_url,
                        "source_type": "public_embedded_list",
                        "observed_at": item.get("observed_at"),
                    },
                }
            )
            restored["public_calculators"] += 1
    public_courses = {}
    for row in rows:
        if row["kind"] == "course":
            public_courses.setdefault(normalize_title(row["title"]), []).append(row)
    historical_course_titles = Counter(
        normalize_title(item["title"])
        for item in old
        if item.get("kind") == "course" and item.get("title")
    )
    for item in old:
        kind, key = item.get("kind"), item.get("entity_key")
        if (
            kind not in {"course", "webinar", "calculator"}
            or not key
            or key in seen_entity_keys
        ):
            continue
        if not item.get("title"):
            continue
        if kind == "course":
            title_key = normalize_title(item["title"])
            matches = public_courses.get(title_key, [])
            if matches:
                if len(matches) == 1 and historical_course_titles[title_key] == 1:
                    matches[0]["historical_title_candidate"] = key
                    restored["course_title_candidates_unverified"] += 1
                else:
                    restored["ambiguous_backup_courses_excluded"] += 1
                seen_entity_keys.add(key)
                continue
        seen_entity_keys.add(key)
        rows.append(
            {
                "id": "historical:" + key,
                "kind": kind,
                "title": item["title"],
                "description": item.get("description") or "",
                "origin": "historical_backup",
                "source_url": None,
                "source_id": item.get("source_id"),
                "historical_id_match": True,
                "historical_entity_key": key,
                "observed_at": None,
                "publication": "unknown",
                "access": "unknown",
                "offer": "unknown",
                "topics": item.get("topics") or [],
                "price": {"status": "unknown"},
                "provenance": {"source_type": "historical_backup"},
            }
        )
        restored["backup_" + kind] += 1
    for index, (topic, title, description, price) in enumerate(TOPICS, 1):
        rows.append(
            {
                "id": f"synthetic:course:{index}",
                "kind": "course",
                "title": title,
                "description": description,
                "origin": "synthetic",
                "source_url": None,
                "source_id": None,
                "observed_at": None,
                "publication": "fictional",
                "access": "fictional",
                "offer": "fictional",
                "topics": [topic],
                "price": {"status": "fictional", "amount": price, "currency": "RUB"},
            }
        )
        rows.append(
            {
                "id": f"synthetic:article:{index}",
                "kind": "article",
                "title": f"{topic}: с чего начать",
                "description": "Вымышленный вводный материал для демонстрации рекомендаций.",
                "origin": "synthetic",
                "source_url": None,
                "source_id": None,
                "observed_at": None,
                "publication": "fictional",
                "access": "fictional",
                "offer": "fictional",
                "topics": [topic],
                "price": {"status": "fictional_free"},
            }
        )
        for sub, suffix in enumerate(
            ("практический интенсив", "разбор кейсов", "план развития"), 1
        ):
            rows.append(
                {
                    "id": f"synthetic:course:{index}-{sub}",
                    "kind": "course",
                    "title": f"{topic}: {suffix}",
                    "description": f"Учебный платный пример по теме «{topic}».",
                    "origin": "synthetic",
                    "source_url": None,
                    "source_id": None,
                    "observed_at": None,
                    "publication": "fictional",
                    "access": "fictional",
                    "offer": "fictional",
                    "topics": [topic],
                    "price": {
                        "status": "fictional",
                        "amount": (3990, 7990, 14990)[sub - 1],
                        "currency": "RUB",
                    },
                }
            )
        rows.append(
            {
                "id": f"synthetic:webinar:{index}",
                "kind": "webinar",
                "title": f"{topic}: вебинар с разбором примеров",
                "description": f"Вымышленный вебинар по теме «{topic}».",
                "origin": "synthetic",
                "source_url": None,
                "source_id": None,
                "observed_at": None,
                "publication": "fictional",
                "access": "fictional",
                "offer": "fictional",
                "topics": [topic],
                "price": {"status": "fictional", "amount": 1490, "currency": "RUB"},
            }
        )
        for sub in (1, 2):
            rows.append(
                {
                    "id": f"synthetic:lesson:{index}-{sub}",
                    "kind": "lesson",
                    "title": f"{topic}: практический урок {sub}",
                    "description": f"Вымышленный отдельный урок по теме «{topic}».",
                    "origin": "synthetic",
                    "source_url": None,
                    "source_id": None,
                    "observed_at": None,
                    "publication": "fictional",
                    "access": "fictional",
                    "offer": "fictional",
                    "topics": [topic],
                    "price": {
                        "status": "fictional",
                        "amount": 790 if sub == 1 else 990,
                        "currency": "RUB",
                    },
                }
            )
    observations = {}
    if observations_path:
        source = json.loads(Path(observations_path).read_text(encoding="utf-8"))
        parsed_source = urlsplit(source["source"])
        if (
            parsed_source.scheme != "https"
            or parsed_source.hostname != "kurs.alfabank.ru"
        ):
            raise ValueError("Unexpected price observation source")
        for value in source["courses"]:
            key = normalize_title(value["title"])
            if key in observations:
                raise ValueError("Ambiguous observed price title")
            if (
                type(value["observed_price_rub"]) is not int
                or not 0 < value["observed_price_rub"] <= 10000000
            ):
                raise ValueError("Invalid historical price")
            observations[key] = {
                "observed_price_rub": value["observed_price_rub"],
                "source_url": source["source"],
                "observed_at": source["observed_at"],
                "match_status": "title_match_not_verified",
            }
    for item in rows:
        if (
            item.get("historical_id_match")
            and item.get("source_id")
            and not item.get("historical_entity_key")
        ):
            item["historical_entity_key"] = f"{item['kind']}:{item['source_id']}"
        if item["kind"] in PRICE_BANDS:
            offer = simulated_offer(item, observations)
            if item["origin"] == "synthetic":
                offer["price_rub"] = item["price"]["amount"]
                offer["cost_rub"] = int(round(offer["price_rub"] * 0.4 / 10) * 10)
                offer["source"], offer["reference"] = "generated", None
            item["demo_offer"] = offer
    report = {
        "public": dict(stats),
        "public_by_kind": dict(kinds),
        "restored": dict(restored),
        "synthetic": sum(x["origin"] == "synthetic" for x in rows),
        "simulated_offers": sum(bool(x.get("demo_offer")) for x in rows),
        "reference_price_candidates": sum(
            bool(x.get("demo_offer", {}).get("reference")) for x in rows
        ),
        "total": len(rows),
        "public_sha256": hashlib.sha256(Path(public_path).read_bytes()).hexdigest(),
        "historical_sha256": hashlib.sha256(Path(old_path).read_bytes()).hexdigest(),
        "duplicate_title_groups": sum(n > 1 for n in titles.values()),
        "duplicate_source_id_groups": sum(n > 1 for n in source_ids.values()),
        "limitations": "Public snapshot is incomplete; current publication, offers, prices and user access are unverified. Exact historical ID matches are candidates, not proof of current identity. Synthetic records are fictional.",
    }
    return {"version": 1, "items": rows, "audit": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", required=True, type=Path)
    parser.add_argument("--historical", required=True, type=Path)
    parser.add_argument(
        "--calculators",
        type=Path,
        default=Path("data/public/calculators/materials.jsonl"),
    )
    parser.add_argument(
        "--observations",
        type=Path,
        default=Path("05_code/experiments/alfa_public_courses.json"),
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    catalog = build(args.public, args.historical, args.calculators, args.observations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(catalog, stream, ensure_ascii=False)
    print(json.dumps(catalog["audit"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
