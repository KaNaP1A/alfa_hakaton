"""Cached field BM25 and explicit, bounded fusion parameters."""

import math
from collections import Counter
from dataclasses import asdict, dataclass

from .text import tokens

FIELDS = ("title", "description", "topics", "tags", "industries", "body", "lessons")
KINDS = ("article", "course", "document", "glossary", "podcast", "webinar", "calculator")
FEATURE_NAMES = (
    [f"bm25_{name}" for name in FIELDS]
    + [
        "cosine_card",
        "cosine_body",
        "cosine_lesson",
        "query_coverage",
        "title_coverage",
        "selection_match",
        "topic_overlap",
        "tag_overlap",
        "industry_overlap",
    ]
    + [f"kind_{kind}" for kind in KINDS]
)


@dataclass(frozen=True)
class RankingConfig:
    title: float = 2.0
    description: float = 1.0
    topics: float = 0.5
    tags: float = 0.5
    industries: float = 0.5
    body: float = 0.25
    lessons: float = 0.75
    dense_weight: float = 1.0
    selection_boost: float = 0.25
    rrf_k: int = 60
    candidate_count: int = 60

    def __post_init__(self):
        for name, value in asdict(self).items():
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid ranking parameter: {name}")
        if not 1 <= self.rrf_k <= 1000 or not 1 <= self.candidate_count <= 500:
            raise ValueError("Invalid RRF/candidate range")
        if not isinstance(self.rrf_k, int) or not isinstance(self.candidate_count, int):
            raise ValueError("RRF/candidate parameters must be integers")
        if self.selection_boost > 1:
            raise ValueError("selection_boost must not exceed 1")


class BM25Index:
    def __init__(self, texts, k1=1.5, b=0.75):
        self.docs = [Counter(tokens(text)) for text in texts]
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.df = Counter(term for doc in self.docs for term in doc)
        self.average = sum(self.lengths) / max(len(self.docs), 1) or 1
        self.k1, self.b = k1, b

    def score(self, query):
        terms = set(tokens(query))
        n = len(self.docs)
        return [
            sum(
                math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                * doc[term]
                * (self.k1 + 1)
                / (doc[term] + self.k1 * (1 - self.b + self.b * length / self.average))
                for term in terms
                if doc.get(term)
            )
            for doc, length in zip(self.docs, self.lengths, strict=True)
        ]


def field_text(item, field):
    if field == "lessons":
        return " ".join(
            " ".join([row["title"], row["description"], row.get("body", "")])
            for row in item.get("lessons", [])
        )
    value = item.get(field, "")
    return " ".join(value) if isinstance(value, list) else value


class FieldRetriever:
    def __init__(self, catalog):
        self.catalog = catalog
        self.indexes = {
            field: BM25Index([field_text(item, field) for item in catalog]) for field in FIELDS
        }
        self.term_sets = [
            set().union(*(set(tokens(field_text(item, field))) for field in FIELDS))
            for item in catalog
        ]
        self.title_terms = [set(tokens(item["title"])) for item in catalog]

    def signals(self, query, dense=None, selected_keys=()):
        terms = set(tokens(query))
        scores = {field: index.score(query) for field, index in self.indexes.items()}
        dense = dense or {
            source: [0.0] * len(self.catalog) for source in ["card", "body", "lesson"]
        }
        features = []
        for i, item in enumerate(self.catalog):
            features.append(
                [scores[field][i] for field in FIELDS]
                + [dense[source][i] for source in ["card", "body", "lesson"]]
                + [
                    len(terms & self.term_sets[i]) / max(len(terms), 1),
                    len(terms & self.title_terms[i]) / max(len(terms), 1),
                    float(item["entity_key"] in selected_keys),
                ]
                + [
                    len(terms & set(tokens(field_text(item, field)))) / max(len(terms), 1)
                    for field in ["topics", "tags", "industries"]
                ]
                + [float(item["kind"] == kind) for kind in KINDS]
            )
        return {"fields": scores, "dense": dense, "features": features}

    def rank(self, signals, config, allowed=None, semantic=True, legacy=False):
        allowed = set(range(len(self.catalog))) if allowed is None else set(allowed)
        lexical = [
            sum(getattr(config, field) * signals["fields"][field][i] for field in FIELDS)
            for i in range(len(self.catalog))
        ]
        dense = [
            max(signals["dense"][source][i] for source in ["card", "body", "lesson"])
            for i in range(len(self.catalog))
        ]

        def ordered(indices, values):
            return sorted(indices, key=lambda i: (-values[i], self.catalog[i]["entity_key"]))

        ranks = {
            "bm25": {
                i: r + 1
                for r, i in enumerate(
                    ordered([i for i in allowed if lexical[i] > 0], lexical)[
                        : config.candidate_count
                    ]
                )
            }
        }
        if semantic:
            ranks["dense"] = {
                i: r + 1 for r, i in enumerate(ordered(allowed, dense)[: config.candidate_count])
            }
        candidates = set().union(*(rank.keys() for rank in ranks.values()))
        fused = {}
        for i in candidates:
            score = sum(
                (config.dense_weight if channel == "dense" else 1) / (config.rrf_k + rank[i])
                for channel, rank in ranks.items()
                if i in rank
            )
            # Selection boosts only originally retrieved candidates, and is bounded by
            # original-query coverage; it can no longer flood recall with a broad category.
            coverage = signals["features"][i][10]
            selected = signals["features"][i][12]
            fused[i] = score * (1 + config.selection_boost * selected * coverage)
        return ordered(candidates, fused), lexical, dense, fused, ranks
