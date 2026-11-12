"""Freeze 1000 diverse scenarios and a fully judged fictional retrieval corpus before evaluation."""

import argparse
import hashlib
import json
import os
import secrets
from collections import Counter
from pathlib import Path

from alfa_reco.bundle import atomic_json, load_bundle, sha256
from alfa_reco.suggestions import build_index

# Domain, infinitive task, equivalent task, contrasting task, audience.
TASKS = [
    ("Общепит", "открыть кофейню", "запустить кофейню", "закрыть кофейню", "предпринимателя"),
    ("Общепит", "открыть пекарню", "запустить пекарню", "закрыть пекарню", "владельца бизнеса"),
    (
        "Общепит",
        "рассчитать себестоимость блюда",
        "посчитать себестоимость блюда",
        "назначить цену блюда",
        "ресторатора",
    ),
    (
        "Общепит",
        "организовать доставку еды",
        "наладить доставку еды",
        "отменить доставку еды",
        "ресторатора",
    ),
    (
        "Общепит",
        "выбрать помещение ресторана",
        "подобрать помещение ресторана",
        "продать помещение ресторана",
        "предпринимателя",
    ),
    (
        "Команда",
        "нанять сотрудника",
        "принять сотрудника на работу",
        "уволить сотрудника",
        "работодателя",
    ),
    (
        "Команда",
        "мотивировать сотрудников",
        "повысить мотивацию сотрудников",
        "наказать сотрудников",
        "руководителя",
    ),
    (
        "Команда",
        "снизить текучесть кадров",
        "уменьшить текучесть кадров",
        "увеличить текучесть кадров",
        "руководителя",
    ),
    (
        "Команда",
        "оформить отпуск работника",
        "подготовить документы на отпуск работника",
        "отменить отпуск работника",
        "работодателя",
    ),
    (
        "Команда",
        "организовать адаптацию новичков",
        "наладить адаптацию новичков",
        "уволить новичков",
        "руководителя",
    ),
    (
        "Финансы",
        "составить платежный календарь",
        "подготовить платежный календарь",
        "проверить платежный календарь",
        "финансового директора",
    ),
    (
        "Финансы",
        "предотвратить кассовый разрыв",
        "избежать кассового разрыва",
        "зафиксировать кассовый разрыв",
        "предпринимателя",
    ),
    (
        "Финансы",
        "погасить задолженность",
        "выплатить задолженность",
        "взыскать задолженность",
        "должника",
    ),
    (
        "Финансы",
        "взыскать задолженность",
        "добиться возврата задолженности",
        "погасить задолженность",
        "кредитора",
    ),
    (
        "Финансы",
        "рассчитать рентабельность проекта",
        "посчитать рентабельность проекта",
        "повысить рентабельность проекта",
        "аналитика",
    ),
    (
        "Продажи",
        "привлечь покупателей",
        "найти новых покупателей",
        "удержать покупателей",
        "владельца магазина",
    ),
    (
        "Продажи",
        "удержать клиентов",
        "сохранить существующих клиентов",
        "привлечь новых клиентов",
        "менеджера",
    ),
    (
        "Продажи",
        "оценить эффективность рекламы",
        "измерить эффективность рекламы",
        "запустить рекламу",
        "маркетолога",
    ),
    ("Продажи", "выбрать поставщика", "подобрать поставщика", "сменить поставщика", "закупщика"),
    (
        "Продажи",
        "обработать возврат товара",
        "оформить возврат товара",
        "отменить заказ товара",
        "продавца",
    ),
    (
        "Документы",
        "составить договор аренды",
        "подготовить договор аренды",
        "расторгнуть договор аренды",
        "арендатора",
    ),
    (
        "Документы",
        "зарегистрировать товарный знак",
        "оформить регистрацию товарного знака",
        "аннулировать товарный знак",
        "владельца бренда",
    ),
    (
        "Документы",
        "внести изменения в устав",
        "изменить устав организации",
        "утвердить первоначальный устав",
        "учредителя",
    ),
    (
        "Документы",
        "составить доверенность",
        "подготовить доверенность",
        "отозвать доверенность",
        "директора",
    ),
    (
        "Документы",
        "закрыть ИП",
        "прекратить деятельность ИП",
        "зарегистрировать ИП",
        "предпринимателя",
    ),
    (
        "Технологии",
        "защитить персональные данные",
        "обеспечить защиту персональных данных",
        "собрать персональные данные",
        "администратора",
    ),
    (
        "Технологии",
        "настроить резервное копирование",
        "организовать резервное копирование",
        "удалить резервные копии",
        "администратора",
    ),
    (
        "Технологии",
        "проанализировать продажи",
        "провести анализ продаж",
        "спланировать продажи",
        "аналитика",
    ),
    (
        "Технологии",
        "автоматизировать обработку заявок",
        "настроить автоматическую обработку заявок",
        "обрабатывать заявки вручную",
        "руководителя",
    ),
    (
        "Технологии",
        "обучить классификатор текстов",
        "натренировать классификатор текстов",
        "оценить классификатор текстов",
        "разработчика",
    ),
    (
        "Естественные науки",
        "измерить кислотность воды",
        "определить кислотность воды",
        "изменить кислотность воды",
        "лаборанта",
    ),
    (
        "Естественные науки",
        "вырастить кристаллы соли",
        "получить кристаллы соли",
        "растворить кристаллы соли",
        "студента",
    ),
    (
        "Естественные науки",
        "наблюдать движение планет",
        "изучить движение планет",
        "рассчитать массу планет",
        "астронома",
    ),
    (
        "Естественные науки",
        "измерить электрическое сопротивление",
        "определить электрическое сопротивление",
        "изменить электрическое сопротивление",
        "студента",
    ),
    (
        "Естественные науки",
        "сравнить виды почвы",
        "сопоставить виды почвы",
        "улучшить плодородие почвы",
        "агронома",
    ),
    (
        "Творчество",
        "освоить акварельную живопись",
        "научиться рисовать акварелью",
        "реставрировать акварель",
        "начинающего художника",
    ),
    (
        "Творчество",
        "настроить освещение портрета",
        "подобрать освещение портрета",
        "отретушировать портрет",
        "фотографа",
    ),
    (
        "Творчество",
        "написать сценарий подкаста",
        "подготовить сценарий подкаста",
        "смонтировать подкаст",
        "автора",
    ),
    ("Творчество", "сделать макет афиши", "создать макет афиши", "напечатать афишу", "дизайнера"),
    (
        "Творчество",
        "настроить акустическую гитару",
        "отрегулировать строй акустической гитары",
        "записать звук акустической гитары",
        "музыканта",
    ),
]
KINDS = ["article", "course", "webinar", "document", "podcast"]


def item(key, title, description, topic, **extra):
    return {
        "entity_key": key,
        "source_id": key.split(":")[-1],
        "kind": key.split(":")[0],
        "title": title,
        "description": description,
        "topics": [topic],
        "tags": [],
        "industries": [],
        "search_text": title + " " + description,
        "access_type": "open",
        "source_url": None,
        "canonical_url": None,
        "data_quality_flags": ["fictional_benchmark"],
        "body": "",
        **extra,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    salt = secrets.token_hex(16)
    private = set(
        sorted(range(40), key=lambda i: hashlib.sha256(f"{salt}:{i}".encode()).hexdigest())[:8]
    )
    catalog = []
    cases = []

    def add(category, family, split, **data):
        cases.append(
            {
                "id": f"{category}-{family}-{len(cases):04d}",
                "type": category,
                "family": family,
                "split": split,
                **data,
            }
        )

    for f, (domain, goal, alias, contrast, audience) in enumerate(TASKS):
        family = f"task-{f:02d}"
        split = "test" if f in private else "dev"
        for k in KINDS:
            catalog.append(
                item(
                    f"{k}:synthetic-{f:02d}-{k}",
                    f"{goal.capitalize()} · {k}",
                    f"Учебный пример для {audience}. Цель: {goal}. Другая формулировка той же цели: {alias}. Разбирается именно эта задача; контрастная задача «{contrast}» в программу не входит.",
                    domain,
                    oracle_family=family,
                    oracle_goal="primary",
                    oracle_audience="primary",
                )
            )
        catalog.append(
            item(
                f"article:synthetic-{f:02d}-contrast",
                contrast.capitalize(),
                f"Учебный пример для {audience}: {contrast}.",
                domain,
                oracle_family=family,
                oracle_goal="contrast",
                oracle_audience="primary",
            )
        )
        catalog.append(
            item(
                f"course:synthetic-{f:02d}-audience",
                goal.capitalize() + " для другой аудитории",
                f"Цель: {goal}. Это материал только для преподавателя, который обучает других, а не для {audience}.",
                domain,
                oracle_family=family,
                oracle_goal="primary",
                oracle_audience="other",
            )
        )
        queries = [
            f"Как {goal} для {audience}",
            f"Как {alias} для {audience}",
            f"Нужен материал: {goal}, для {audience}",
            f"Для {audience}: как {goal}",
            f"Хочу разобраться, как {goal} для {audience}",
            f"Нужен курс: {goal}, для {audience}",
            f"Ищу вебинар: {goal}, для {audience}",
            f"Нужен документ: {goal}, для {audience}",
        ]
        for n, q in enumerate(queries):
            add(
                "retrieval",
                family,
                split,
                query=q,
                kind={5: "course", 6: "webinar", 7: "document"}.get(n),
                target_family=family,
                target_goal="primary",
                target_audience="primary",
            )
        pairs = [
            (f"как {goal} для {audience}", f"для {audience} как {goal}"),
            (f"как {goal} для {audience}", f"Как {goal} для {audience}."),
            (f"как {goal} для {audience}", f"КАК {goal.upper()} ДЛЯ {audience.upper()}"),
            (f"как {goal} для {audience}", f"как {alias} для {audience}"),
        ]
        for n, pair in enumerate(pairs):
            add(
                "equivalence",
                family,
                split,
                queries=pair,
                relation="synonym" if n == 3 else "word_order" if n == 0 else "formatting",
            )
        add(
            "contrast",
            family,
            split,
            query=f"Как {contrast} для {audience}",
            target_family=family,
            target_goal="contrast",
            target_audience="primary",
        )
        add(
            "contrast",
            family,
            split,
            query=f"Как {goal} для преподавателя, который обучает других",
            target_family=family,
            target_goal="primary",
            target_audience="other",
        )
        add(
            "no_answer",
            family,
            split,
            query=f"Как построить межзвездный телепорт: задача для {audience}",
        )
    # 200 trajectories: both controlled evidence and real course/webinar/podcast histories.
    _, actual_manifest, actual = load_bundle("artifacts/catalog")
    real = [i for i in actual if i["kind"] != "glossary"]
    sources = []
    for kind in KINDS:
        group = [i for i in real if i["kind"] == kind]
        sources.extend(group[:20])
    sources = (sources + [i for i in real if i not in sources])[:100]
    for n, source in enumerate(sources):
        split = "test" if n % 5 == 0 else "dev"
        fam = f"profile-real-{n // 5}"
        add(
            "recommendation_real",
            fam,
            split,
            viewed=[source["entity_key"]],
            categories=[],
            source_kind=source["kind"],
        )
        add(
            "recommendation_real",
            fam,
            split,
            viewed=[source["entity_key"]] * 3,
            categories=[],
            source_kind=source["kind"],
            check="deduplicate",
        )
    # 100 exact-material identity tests grouped by five.
    for n, source in enumerate(sources):
        add(
            "real_identity",
            f"identity-{n // 5}",
            "test" if n % 5 == 0 else "dev",
            query=source["title"][:300],
            target=source["entity_key"],
            kind=source["kind"],
        )
    # 100 diverse validation/boundary contracts, including deterministic synthetic profiles.
    for n in range(100):
        add("contract", f"contract-{n // 5}", "test" if n % 5 == 0 else "dev", variant=n)
    assert len(cases) == 1000, len(cases)
    # Family split consistency is mandatory; five-member groups assigned together.
    for group in ["profile-real-", "identity-", "contract-"]:
        fams = sorted({r["family"] for r in cases if r["family"].startswith(group)})
        closed = set(
            sorted(fams, key=lambda f: hashlib.sha256((salt + f).encode()).hexdigest())[
                : len(fams) // 5
            ]
        )
        for r in cases:
            if r["family"].startswith(group):
                r["split"] = "test" if r["family"] in closed else "dev"
    catalog.sort(key=lambda i: i["entity_key"])
    path = a.output / "catalog" / "generation-synthetic"
    path.mkdir(parents=True)
    atomic_json(path / "catalog.json", catalog)
    digest = sha256(path / "catalog.json")
    atomic_json(path / "suggestions.json", build_index(catalog, digest))
    atomic_json(
        path / "manifest.json",
        {
            "catalog_sha256": digest,
            "semantic": None,
            "suggestions": {"sha256": sha256(path / "suggestions.json")},
            "fictional": True,
        },
    )
    atomic_json(path.parent / "CURRENT.json", {"generation": path.name})
    for split in ["dev", "test"]:
        rows = [c for c in cases if c["split"] == split]
        f = a.output / (split + ".jsonl")
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        os.chmod(f, 0o600)
    # Fully specified oracle scores for EVERY document, including near negatives.
    oracle = []
    for case in cases:
        if case["type"] in {"retrieval", "contrast"}:
            labels = {}
            for doc in catalog:
                grade = 0
                if (
                    doc["oracle_family"] == case["target_family"]
                    and doc["oracle_goal"] == case["target_goal"]
                ):
                    grade = 3 if doc["oracle_audience"] == case["target_audience"] else 1
                if case.get("kind") and doc["kind"] != case["kind"]:
                    grade = 0
                labels[doc["entity_key"]] = grade
            oracle.append(
                {
                    "id": case["id"],
                    "labels": labels,
                    "assessor": "structured_synthetic_oracle",
                    "human_verified": False,
                }
            )
    split_by_id = {r["id"]: r["split"] for r in cases}
    for split in ("dev", "test"):
        target = a.output / ("oracle_" + split + ".jsonl")
        target.write_text(
            "".join(
                json.dumps(r, ensure_ascii=False) + "\n"
                for r in oracle
                if split_by_id[r["id"]] == split
            )
        )
        os.chmod(target, 0o600)
    manifest = {
        "cases": 1000,
        "split_counts": dict(Counter(c["split"] for c in cases)),
        "types": dict(Counter(c["type"] for c in cases)),
        "families": len({c["family"] for c in cases}),
        "fictional_documents": len(catalog),
        "fully_judged_queries": len(oracle),
        "complete_pair_labels": len(oracle) * len(catalog),
        "actual_catalog_sha256": actual_manifest["catalog_sha256"],
        "frozen_model": json.loads(
            Path("artifacts/relevance_v1/training/manifest.json").read_text()
        )["ranker_sha256"],
        "hashes": {
            n: sha256(a.output / n)
            for n in ["dev.jsonl", "test.jsonl", "oracle_dev.jsonl", "oracle_test.jsonl"]
        },
        "test_status": "sealed_not_evaluated",
        "protocol": "Families split before evaluation. No training on this corpus. Test is synthetic operational holdout, not independent human gold. 1000 scenarios are not 1000 independent user intents.",
    }
    atomic_json(a.output / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
