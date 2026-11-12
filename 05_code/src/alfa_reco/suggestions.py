"""Catalog-grounded autocomplete and related facets, without online LLM calls."""

import hashlib
import math
import re
from bisect import bisect_left
from collections import defaultdict

from .text import STOP, tokens, words

SCHEMA_VERSION = 1
MAX_QUERY_LENGTH = 300
# Only conversational/task scaffolding; this is not a domain synonym dictionary.
INTENT_WORDS = {
    "открыть",
    "начать",
    "создать",
    "повысить",
    "улучшить",
    "узнать",
    "изучить",
}
FACETS = ("topics", "tags", "industries")


def validate_query(query):
    if not isinstance(query, str) or len(query) > MAX_QUERY_LENGTH:
        raise ValueError("query must be a string of at most 300 characters")
    if any(ord(char) < 32 for char in query):
        raise ValueError("query must not contain control characters")


def entry_id(kind, label):
    value = kind + "\0" + " ".join(words(label))
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def phrase_candidates(text):
    """Yield short source spans, never generated or reordered text.

    Only repeated spans are admitted to the index; complete titles and taxonomy
    labels remain the primary source. This avoids emitting arbitrary n-grams.
    """
    for segment in re.split(r"[.!?;:\n,()—–]", text):
        spans = list(re.finditer(r"[\w+#]+", segment))
        for width in (1, 2, 3):
            for start in range(len(spans) - width + 1):
                block = spans[start : start + width]
                label = segment[block[0].start() : block[-1].end()]
                terms = words(label)
                if (
                    terms[0] not in STOP
                    and terms[-1] not in STOP
                    and all(len(term) >= 3 or term in STOP for term in terms)
                    and any(len(term) >= 4 for term in terms)
                ):
                    yield label


def build_index(catalog, catalog_sha256):
    entries = {}
    phrases = defaultdict(lambda: {"labels": set(), "evidence": set()})

    def add(kind, label, entity_key, source):
        if not label or len(label) > 180 or not tokens(label):
            return
        key = entry_id(kind, label)
        item = entries.setdefault(
            key,
            {
                "id": key,
                "kind": kind,
                "label": label,
                "entity_keys": set(),
                "sources": set(),
            },
        )
        item["label"] = min(item["label"], label)
        item["entity_keys"].add(entity_key)
        item["sources"].add(source)

    for item in catalog:
        key = item["entity_key"]
        for facet in FACETS:
            for label in item[facet]:
                add(facet, label, key, facet)
        source_texts = [("title", item["title"]), ("description", item["description"])]
        add("title", item["title"], key, "title")
        for lesson in item.get("lessons", []):
            add("lesson", lesson["title"], key, "lesson:" + lesson["lesson_id"])
            source_texts.append(("lesson", lesson["title"]))
        for source, text in source_texts:
            for label in phrase_candidates(text):
                normalized = " ".join(words(label))
                phrases[normalized]["labels"].add(label)
                phrases[normalized]["evidence"].add((key, source))
    for value in phrases.values():
        # Two distinct materials, not two mentions in the same material.
        if len({key for key, _ in value["evidence"]}) < 2 or not any(
            source in {"title", "lesson"} for _, source in value["evidence"]
        ):
            continue
        label = min(value["labels"])
        for key, source in value["evidence"]:
            add("phrase", label, key, source)
    result = []
    for key in sorted(entries):
        item = entries[key]
        result.append(
            {
                **item,
                "entity_keys": sorted(item["entity_keys"]),
                "sources": sorted(item["sources"]),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_sha256": catalog_sha256,
        "entries": result,
    }


def one_edit(left, right):
    """At most one insertion/deletion/substitution or adjacent transposition."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        different = [i for i, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
        return len(different) == 1 or (
            len(different) == 2
            and different[1] == different[0] + 1
            and left[different[0]] == right[different[1]]
            and left[different[1]] == right[different[0]]
        )
    if len(left) > len(right):
        left, right = right, left
    for i, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return left[i:] == right[i + 1 :]
    return True


class SuggestionIndex:
    def __init__(self, data, catalog, generation):
        if data["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Unsupported suggestion index version")
        self.generation = generation
        self.entries = {row["id"]: row for row in data["entries"]}
        self.catalog = {row["entity_key"]: row for row in catalog}
        self.postings = defaultdict(set)
        self.entry_terms = {}
        for item in data["entries"]:
            if not set(item["entity_keys"]) <= self.catalog.keys():
                raise ValueError("Suggestion references missing material")
            terms = set(words(item["label"])) | set(tokens(item["label"]))
            self.entry_terms[item["id"]] = terms
            for term in terms:
                self.postings[term].add(item["id"])
        self.vocabulary = sorted(self.postings)
        self.by_length = defaultdict(list)
        for term in self.vocabulary:
            self.by_length[len(term)].append(term)
        self.document_terms = {
            key: set(words(item["search_text"])) | set(tokens(item["search_text"]))
            for key, item in self.catalog.items()
        }
        self.facet_ids = [key for key, item in self.entries.items() if item["kind"] in FACETS]

    def matching_terms(self, word, partial):
        forms = {word, *tokens(word)}
        exact = forms & self.postings.keys()
        prefixes = set()
        if partial and len(word) >= 2:
            start = bisect_left(self.vocabulary, word)
            for term in self.vocabulary[start:]:
                if not term.startswith(word):
                    break
                prefixes.add(term)
        matches = exact | prefixes
        if matches or len(word) < 4 or len(word) > 40:
            return matches, False
        fuzzy = set()
        for form in forms:
            if len(form) < 4:
                continue
            for length in (len(form) - 1, len(form), len(form) + 1):
                fuzzy.update(term for term in self.by_length[length] if one_edit(form, term))
        return fuzzy, bool(fuzzy)

    def resolve(self, selection_id, generation):
        if generation != self.generation:
            raise ValueError("Stale selection generation; request suggestions again")
        if selection_id not in self.entries:
            raise ValueError("Unknown selection_id")
        return self.entries[selection_id]

    def suggest(self, query, limit=6):
        validate_query(query)
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("limit must be between 1 and 10")
        response = {
            "query": query,
            "generation": self.generation,
            "completions": [],
            "related_topics": [],
            "status": "no_match",
            "typo_tolerant_match": False,
        }
        raw = words(query)
        meaningful = [word for word in raw if word not in STOP and word not in INTENT_WORDS]
        if not meaningful or len("".join(meaningful)) < 2:
            response["status"] = "insufficient_input"
            return response
        match_groups = []
        for i, word in enumerate(meaningful):
            partial = i == len(meaningful) - 1 and not query.endswith(" ")
            terms, fuzzy = self.matching_terms(word, partial)
            response["typo_tolerant_match"] |= fuzzy
            if not terms:
                return response
            match_groups.append(terms)
        candidates = None
        for terms in match_groups:
            ids = set().union(*(self.postings[term] for term in terms))
            candidates = ids if candidates is None else candidates & ids
        # Context must match within a material, including all substantive words.
        supporting = {
            key
            for key, terms in self.document_terms.items()
            if all(terms & group for group in match_groups)
        }

        def result(item):
            return {
                "id": item["id"],
                "label": item["label"],
                "kind": item["kind"],
                "support_count": len(item["entity_keys"]),
                "evidence_entity_keys": item["entity_keys"][:3],
                "selection": {"id": item["id"], "generation": self.generation},
            }

        def score(key):
            item = self.entries[key]
            exact_phrase = " ".join(raw) in " ".join(words(item["label"]))
            context = len(set(tokens(query)) & set(tokens(item["label"])))
            source = (
                2 if item["kind"] in FACETS else 1 if item["kind"] in {"title", "lesson"} else 0
            )
            return (
                -int(exact_phrase),
                -context,
                -source,
                -math.log1p(len(item["entity_keys"])),
                len(item["label"]),
                item["label"],
                key,
            )

        seen = set()
        for key in sorted(candidates or [], key=score):
            item = self.entries[key]
            label = " ".join(words(item["label"]))
            if label in seen:
                continue
            seen.add(label)
            response["completions"].append(result(item))
            if len(response["completions"]) == limit:
                break
        related = []
        for key in self.facet_ids:
            item = self.entries[key]
            overlap = supporting & set(item["entity_keys"])
            if overlap and " ".join(words(item["label"])) not in seen:
                related.append((len(overlap) / math.sqrt(len(item["entity_keys"])), key, overlap))
        for _, key, overlap in sorted(related, key=lambda row: (-row[0], row[1])):
            item = self.entries[key]
            label = " ".join(words(item["label"]))
            if label in seen:
                continue
            seen.add(label)
            response["related_topics"].append(
                {
                    **result(item),
                    "evidence_entity_keys": sorted(overlap)[:3],
                    "context_support_count": len(overlap),
                }
            )
            if len(response["related_topics"]) == limit:
                break
        if response["completions"] or response["related_topics"]:
            response["status"] = "matched"
        return response
