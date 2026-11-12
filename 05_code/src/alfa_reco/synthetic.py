"""Reproducible catalog-derived probes; source links are not relevance judgments."""

import hashlib
import itertools
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from .synthetic_scenarios import COMPLEX_FAMILIES
from .text import STOP, tokens

VERSION = "1.1.0"
SPLITS = ("train", "validation", "test")
WORD = re.compile(r"[^\W_]+|[+#]+", re.UNICODE)
TRAILING_WORDS = STOP | {
    "за",
    "под",
    "или",
    "от",
    "при",
    "до",
    "без",
    "между",
    "но",
    "чтобы",
    "уже",
    "который",
    "которая",
    "которое",
    "которые",
}
KIND_LABELS = {
    "article": "статью",
    "course": "курс",
    "document": "документ",
    "glossary": "термин",
    "podcast": "подкаст",
    "webinar": "вебинар",
    "calculator": "калькулятор",
}


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    return " ".join(WORD.findall(text))


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def protected_from_files(paths):
    ids, titles, queries = set(), set(), set()
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for row in data["queries"]:
            queries.add(normalize(row["query"]))
            for judgment in row["judgments"]:
                ids.add(judgment["entity_key"])
                if judgment.get("title"):
                    titles.add(normalize(judgment["title"]))
    return ids, titles, queries


def split_for(group, seed):
    n = int(digest(f"{seed}:split:{group}")[:12], 16) % 100
    return "train" if n < 70 else "validation" if n < 85 else "test"


def typo(text, seed):
    candidates = [m for m in re.finditer(r"[а-яА-ЯёЁa-zA-Z]{6,}", text)]
    for match in candidates:
        word = match.group()
        start = int(digest(f"{seed}:{text}:{word}")[:8], 16) % (len(word) - 1)
        for offset in range(len(word) - 1):
            at = (start + offset) % (len(word) - 1)
            if word[at].casefold() != word[at + 1].casefold():
                misspelled = word[:at] + word[at + 1] + word[at] + word[at + 2 :]
                if word[0].isupper() and word[1:].islower():
                    misspelled = misspelled[0].upper() + misspelled[1:].lower()
                return text[: match.start()] + misspelled + text[match.end() :]
    return None


def trim_trailing_stop(text):
    while text:
        parts = list(WORD.finditer(text))
        if not parts or normalize(parts[-1].group()) not in TRAILING_WORDS:
            break
        text = text[: parts[-1].start()].rstrip(" ,;:-")
    return text


def title_candidates(title, kind, seed):
    """Each transformation preserves a provenance link, not necessarily relevance."""
    yield "title_exact", "search", title
    yield "title_framed", "search", f"Интересует: {title}"
    if kind in KIND_LABELS:
        yield "explicit_format", "search", f"Найти {KIND_LABELS[kind]}: {title}"
    words = list(WORD.finditer(title))
    if len(words) > 3:
        end = words[min(3, len(words) - 1)].end()
        fragment = trim_trailing_stop(title[:end])
        if len(set(tokens(fragment))) >= 2:
            yield "short_fragment", "search", fragment
    misspelled = typo(title, seed)
    if misspelled:
        yield "typo_transposition", "search", misspelled
    if len(title) >= 12:
        length = max(4, len(title) // 2)
        yield "autocomplete_prefix", "autocomplete", title[:length].rstrip()


def description_candidate(item):
    description = " ".join(str(item.get("description") or "").split())
    if "http" in description.casefold() or len(description) > 1500:
        return None
    description = re.sub(
        r"^(?:расскажем|рассказываем|разбираемся|узнайте|объясняем)[,:]?\s+",
        "",
        description,
        flags=re.I,
    )
    words = list(WORD.finditer(description))
    if len(words) < 5:
        return None
    end = words[min(9, len(words) - 1)].end()
    fragment = trim_trailing_stop(description[:end].strip(" .,:;!?—-"))
    relevant = set(tokens(fragment))
    if len(relevant) < 3 or len(relevant - set(tokens(item.get("title", "")))) < 2:
        return None
    return f"Интересует: {fragment}"


def title_groups(catalog):
    """Conservatively group high-overlap titles, with bounded common-word postings."""
    keys = sorted({normalize(str(item.get("title") or "")) for item in catalog} - {""})
    terms = [set(key.split()) for key in keys]
    parent = list(range(len(keys)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    postings = defaultdict(list)
    for i, values in enumerate(terms):
        if len(values) >= 3:
            for term in values:
                postings[term].append(i)
    overlap = Counter()
    for indices in postings.values():
        if len(indices) <= 200:
            overlap.update(itertools.combinations(indices, 2))
    for (a, b), shared in overlap.items():
        if shared >= 3 and len(terms[a] & terms[b]) / len(terms[a] | terms[b]) >= 0.8:
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[max(root_a, root_b)] = min(root_a, root_b)
    return {key: "title:" + digest(keys[find(i)])[:24] for i, key in enumerate(keys)}


def sufficiently_distinct_topics(left, right):
    first, second = set(tokens(left)), set(tokens(right))
    if not first or not second or not first.isdisjoint(second):
        return False
    return not any(len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5] for a in first for b in second)


def build_dataset(catalog, seed=42, protected_ids=(), protected_titles=(), protected_queries=()):
    protected_ids, protected_titles, protected_queries = (
        set(protected_ids),
        set(protected_titles),
        set(protected_queries),
    )
    # Protect duplicate-title records even when a judgment omitted its title.
    protected_titles.update(
        normalize(str(item.get("title") or ""))
        for item in catalog
        if item.get("entity_key") in protected_ids
    )
    rows = []
    seen_queries = set(protected_queries)
    reasons = Counter()
    topics = set()
    grouped_titles = title_groups(catalog)

    def add(query, group, scenario, task, source_id=None, kind=None, field=None):
        query = " ".join(query.split())
        key = normalize(query)
        if not key or len(query) < 2 or len(query) > 300:
            reasons["invalid_length"] += 1
            return
        if key in seen_queries:
            reasons["duplicate_or_protected_query"] += 1
            return
        seen_queries.add(key)
        rows.append(
            {
                "query_id": digest(f"{VERSION}:{seed}:{group}:{scenario}:{key}")[:24],
                "query": query,
                "split": split_for(group, seed),
                "group_id": group,
                "scenario": scenario,
                "task": task,
                "source_id": source_id,
                "kind": kind,
                "label_status": "weak_source_reference" if source_id else "unjudged",
                "relevance": None,
                "provenance": {"field": field, "generator_version": VERSION},
            }
        )

    for item in sorted(catalog, key=lambda row: row["entity_key"]):
        source_id = item["entity_key"]
        title = " ".join(str(item.get("title") or "").split())
        title_key = normalize(title)
        if source_id in protected_ids or title_key in protected_titles:
            reasons["protected_source_skipped"] += 1
            continue
        if not title_key or len(title) < 3 or len(title) > 220 or "http" in title.casefold():
            reasons["invalid_title_skipped"] += 1
            continue
        kind = item.get("kind")
        group = grouped_titles[title_key]
        for scenario, task, query in title_candidates(title, kind, seed):
            add(query, group, scenario, task, source_id, kind, "title")
        description = description_candidate(item)
        if description:
            add(
                description, group, "description_fragment", "search", source_id, kind, "description"
            )
        for name in ("topics", "tags"):
            for topic in item.get(name) or []:
                if isinstance(topic, str) and 3 <= len(topic) <= 70 and normalize(topic):
                    topics.add(" ".join(topic.split()))

    # These deliberately have no target and no relevance labels. Contrast is a probe,
    # not proof that any catalog item should be included or excluded.
    ordered_topics = sorted(topics, key=lambda value: (normalize(value), value))
    unique_topics = []
    seen_topics = set()
    for topic in ordered_topics:
        key = normalize(topic)
        if key not in seen_topics:
            unique_topics.append(topic)
            seen_topics.add(key)
    for i, topic in enumerate(unique_topics):
        group = "facet:" + digest(normalize(topic))[:24]
        add(f"Материалы по теме {topic}", group, "topic_open", "search", field="facet")
        for query in (
            f"Хочу разобраться в теме «{topic}»: с чего начать?",
            f"Объясните простыми словами тему «{topic}»",
            f"Какие частые ошибки бывают по теме «{topic}»?",
            f"Подскажите, что изучить по теме «{topic}», если у меня пока мало опыта",
        ):
            add(query, group, "topic_situation_unjudged", "search", field="facet")
        if len(unique_topics) > 1:
            added = 0
            for offset in range(1, len(unique_topics)):
                other = unique_topics[(i + offset) % len(unique_topics)]
                if sufficiently_distinct_topics(topic, other):
                    add(
                        f"Хочу разобраться в теме {topic}, а не {other}",
                        group,
                        "topic_contrast",
                        "search",
                        field="facet_pair",
                    )
                    added += 1
                    if added == 2:
                        break
    # Out-of-domain candidates remain unjudged: coverage must be checked by a person.
    for query in (
        "как настроить музыкальный синтезатор",
        "как выращивать орхидеи дома",
        "курс по астрофотографии для начинающих",
        "как починить велосипедную цепь",
        "хочу научиться играть на пианино",
        "фывпролджэ",
    ):
        group = "out_of_domain:" + digest(normalize(query))[:24]
        add(query, group, "out_of_domain_unjudged", "search", field="curated_probe")
    for family, queries in sorted(COMPLEX_FAMILIES.items()):
        group = "complex:" + digest(family)[:24]
        for query in queries:
            for prefix in (
                "",
                "У меня мало опыта. ",
                "У меня ограниченное время на изучение. ",
                "Помогите понять основные риски и первый шаг. ",
            ):
                add(
                    prefix + query,
                    group,
                    "complex_situation_unjudged",
                    "search",
                    field="authored_scenario",
                )
    rows.sort(key=lambda row: (row["split"], row["group_id"], row["scenario"], row["query_id"]))
    summary = {
        "version": VERSION,
        "seed": seed,
        "rows": len(rows),
        "counts_by_split": dict(sorted(Counter(row["split"] for row in rows).items())),
        "counts_by_scenario": dict(sorted(Counter(row["scenario"] for row in rows).items())),
        "counts_by_task": dict(sorted(Counter(row["task"] for row in rows).items())),
        "counts_by_kind": dict(sorted(Counter(row["kind"] or "none" for row in rows).items())),
        "unique_sources": len({row["source_id"] for row in rows if row["source_id"]}),
        "skipped": dict(sorted(reasons.items())),
        "limitations": [
            "Catalog-derived probes are not real user queries or independent judgments.",
            "Source references are unverified, other documents are not negative labels.",
            "Exact/group separation cannot prevent semantic or topic leakage.",
            "No user history, purchase, revenue, entitlement, relevance grades or negative labels are generated.",
        ],
    }
    return rows, summary


def review_sample(rows, seed=42, limit=120):
    buckets = defaultdict(list)
    for row in rows:
        key = (row["scenario"], row["split"], row["kind"] or "none")
        buckets[key].append(row)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: digest(f"{seed}:review:{row['query_id']}"))
    selected = []
    while buckets and len(selected) < limit:
        for key in sorted(list(buckets)):
            if len(selected) >= limit:
                break
            row = buckets[key].pop()
            selected.append({**row, "human_review": None, "human_comment": ""})
            if not buckets[key]:
                del buckets[key]
    return selected
