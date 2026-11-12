"""Local E5 retrieval and pairwise ML ranking with an independent, versioned bundle.

Legacy MiniLM/CatBoost artifacts are never reused with these features. Embeddings
and trained trees are local. No remote inference or text-generation API is used.
"""

import json
import math
import threading
from dataclasses import asdict
from pathlib import Path

from .bundle import atomic_json, model_fingerprint, sha256
from .eligibility import USER_KINDS
from .query_rules import exclusion_multiplier, intent_multiplier
from .relevance_text import VERSION, Morphology
from .retrieval import FEATURE_NAMES, FIELDS, FieldRetriever, RankingConfig, field_text
from .text import tokens

EXTRA_FEATURES = [
    "e5_title",
    "e5_facets",
    "idf_card_coverage",
    "idf_title_coverage",
    "subject_coverage",
    "subject_matches",
    "query_length",
    "card_length",
    "topic_count",
    "tag_count",
    "industry_count",
]
FEATURES = FEATURE_NAMES + EXTRA_FEATURES
CODE_FILES = ("relevance.py", "relevance_text.py", "query_rules.py", "query_synonyms.py", "text.py")
DEFAULT_POLICY = {"semantic_min": 0.78, "strong_semantic_min": 0.88, "lexical_min": 0.75}


def code_hashes():
    return {name: sha256(Path(__file__).with_name(name)) for name in CODE_FILES}


def card_text(item):
    # Subjects are separate features, not a replacement for public descriptions.
    return item["title"] + ". " + item.get("description", "")


def build_index(engine, encoder_path, output, threads=2):
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(threads)
    morph = Morphology()
    normalized = []
    for item in engine.catalog:
        row = {**item}
        for field in FIELDS:
            if field != "lessons":
                row[field] = morph.text(field_text(item, field))
        row["lessons"] = [
            {
                **lesson,
                **{
                    key: morph.text(lesson.get(key, "")) for key in ("title", "description", "body")
                },
            }
            for lesson in item.get("lessons", [])
        ]
        normalized.append(row)
    atomic_json(output / "normalized_catalog.json", normalized)
    encoder = SentenceTransformer(str(encoder_path), device="cpu", local_files_only=True)
    encoder.max_seq_length = 384
    arrays = {}
    sources = {
        "card": [card_text(i) for i in engine.catalog],
        "title": [i["title"] for i in engine.catalog],
        "facets": [
            " ".join(i.get("topics", []) + i.get("tags", []) + i.get("industries", []))
            for i in engine.catalog
        ],
        "lesson": [field_text(i, "lessons")[:10000] for i in engine.catalog],
    }
    for name, texts in sources.items():
        active = [i for i, text in enumerate(texts) if text.strip()]
        matrix = np.zeros(
            (len(texts), encoder.get_sentence_embedding_dimension()), dtype=np.float32
        )
        if active:
            matrix[active] = encoder.encode(
                ["passage: " + texts[i] for i in active],
                normalize_embeddings=True,
                batch_size=32,
                show_progress_bar=False,
            )
        arrays[name] = matrix
        print("Indexed E5 source", name, len(active), flush=True)
    np.savez_compressed(output / "vectors.npz", **arrays)
    revision_path = Path(encoder_path) / "revision.json"
    revision = json.loads(revision_path.read_text()) if revision_path.exists() else {}
    manifest = {
        "schema_version": 1,
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "encoder_path": str(Path(encoder_path).resolve()),
        "encoder_revision": revision,
        "encoder_fingerprint": model_fingerprint(encoder_path),
        "max_seq_length": 384,
        "normalizer_version": VERSION,
        "features": FEATURES,
        "source_hashes": code_hashes(),
        "ranking_parameters": asdict(engine.ranking_config),
        "policy": DEFAULT_POLICY,
        "canonical": True,
        "index_sha256": sha256(output / "vectors.npz"),
        "normalized_catalog_sha256": sha256(output / "normalized_catalog.json"),
        "catalog_count": len(engine.catalog),
        "experimental": True,
    }
    atomic_json(output / "manifest.json", manifest)
    return manifest


class RelevanceBackend:
    def __init__(self, engine, path=None, require_model=True):
        import numpy as np
        import torch
        from sentence_transformers import SentenceTransformer

        self.engine = engine
        if path is None:
            root = engine.path / "relevance"
            name = json.loads((root / "CURRENT.json").read_text())["generation"]
            if (
                not isinstance(name, str)
                or not name
                or Path(name).name != name
                or name.startswith(".")
            ):
                raise ValueError("Invalid relevance generation")
            path = root / name
        self.path = Path(path)
        self.manifest = json.loads((self.path / "manifest.json").read_text())
        meta = self.manifest
        if meta["catalog_sha256"] != engine.manifest["catalog_sha256"]:
            raise ValueError("Relevance model belongs to another catalog")
        if meta["source_hashes"] != code_hashes() or meta["features"] != FEATURES:
            raise ValueError("Relevance preprocessing/features changed; rebuild and retrain")
        for name, key in [
            ("vectors.npz", "index_sha256"),
            ("normalized_catalog.json", "normalized_catalog_sha256"),
        ]:
            if sha256(self.path / name) != meta[key]:
                raise ValueError("Corrupt relevance artifact: " + name)
        if model_fingerprint(meta["encoder_path"]) != meta["encoder_fingerprint"]:
            raise ValueError("Relevance encoder differs from indexed weights")
        with np.load(self.path / "vectors.npz", allow_pickle=False) as archive:
            self.vectors = {name: archive[name] for name in ("card", "title", "facets", "lesson")}
        for matrix in self.vectors.values():
            if matrix.shape != (len(engine.catalog), 384) or not np.isfinite(matrix).all():
                raise ValueError("Invalid relevance vector dimensions/values")
        self.morph = Morphology()
        normalized = json.loads((self.path / "normalized_catalog.json").read_text())
        if [i["entity_key"] for i in normalized] != [i["entity_key"] for i in engine.catalog]:
            raise ValueError("Relevance catalog order mismatch")
        self.retriever = FieldRetriever(normalized)
        self.config = RankingConfig(**meta["ranking_parameters"])
        torch.set_num_threads(2)
        self.encoder = SentenceTransformer(
            meta["encoder_path"], device="cpu", local_files_only=True
        )
        self.encoder.max_seq_length = meta["max_seq_length"]
        self.lock = threading.RLock()
        self.canonical = meta.get("canonical", True)
        self.policy = dict(meta["policy"])
        self.model = None
        if require_model:
            from catboost import CatBoostRanker

            if sha256(self.path / "ranker.cbm") != meta.get("ranker_sha256"):
                raise ValueError("Corrupt relevance ranker")
            self.model = CatBoostRanker()
            self.model.load_model(str(self.path / "ranker.cbm"))
            if self.model.feature_names_ != FEATURES:
                raise ValueError("Relevance model feature schema mismatch")
        self.subject_stop = set(
            self.morph.lemmas(
                "нужен нужный материал курс статья информация способ совет найти искать узнать изучить "
                "хочу хотеть начать открыть создать выбрать подобрать повысить улучшить получить небольшой свой"
            )
        )

    def view(self, query):
        return self.morph.query_view(query, self.canonical)

    def encode_queries(self, queries, batch_size=32):
        with self.lock:
            return self.encoder.encode(
                ["query: " + self.view(q)["semantic"] for q in queries],
                normalize_embeddings=True,
                batch_size=batch_size,
                show_progress_bar=False,
            )

    def prepare(self, query, allowed=None, selected_keys=(), vector=None):
        import numpy as np

        with self.lock:
            view = self.view(query)
            if vector is None:
                vector = self.encode_queries([query])[0]
            dense = {key: (matrix @ vector).tolist() for key, matrix in self.vectors.items()}
            by_source = {
                "card": dense["card"],
                "body": [0.0] * len(self.engine.catalog),
                "lesson": dense["lesson"],
            }
            signals = self.retriever.signals(view["lexical"], by_source, selected_keys, self.config)
            terms = set(tokens(view["lexical"]))
            subjects = terms - set(tokens(" ".join(self.subject_stop)))
            subjects = subjects or terms
            weights = {
                term: math.log1p(
                    len(self.engine.catalog) / (1 + self.retriever.indexes["title"].df[term])
                )
                for term in terms
            }
            total = sum(weights.values()) or 1.0
            matrix = []
            for i, item in enumerate(self.engine.catalog):
                card = self.retriever.context_terms[i]
                title = self.retriever.title_terms[i]
                matrix.append(
                    signals["features"][i]
                    + [
                        dense["title"][i],
                        dense["facets"][i],
                        sum(weights[t] for t in terms & card) / total,
                        sum(weights[t] for t in terms & title) / total,
                        len(subjects & card) / max(len(subjects), 1),
                        len(subjects & card),
                        len(terms),
                        math.log1p(len(card)),
                        len(item.get("topics", [])),
                        len(item.get("tags", [])),
                        len(item.get("industries", [])),
                    ]
                )
            allowed = (
                {i for i, item in enumerate(self.engine.catalog) if item["kind"] in USER_KINDS}
                if allowed is None
                else set(allowed)
            )
            hybrid, lexical, _, fused, ranks = self.retriever.rank(
                signals, self.config, allowed, True
            )
            candidates = set(hybrid)
            for source in ("title", "facets"):
                candidates.update(
                    sorted(
                        allowed,
                        key=lambda i: (-dense[source][i], self.engine.catalog[i]["entity_key"]),
                    )[:60]
                )
            order = sorted(
                candidates, key=lambda i: (-fused.get(i, 0), self.engine.catalog[i]["entity_key"])
            )
            features = np.asarray(matrix, dtype=np.float32)
            return {
                "view": view,
                "signals": signals,
                "features": features,
                "candidates": order,
                "lexical": lexical,
                "dense": by_source,
                "e5": dense,
                "fused": fused,
                "ranks": ranks,
                "subjects": subjects,
            }

    def score(self, prepared):
        import numpy as np

        indices = prepared["candidates"]
        with self.lock:
            if self.model is None:
                scores = np.asarray([prepared["e5"]["card"][i] for i in indices])
            else:
                scores = self.model.predict(prepared["features"][indices]) if indices else []
        mapping = {i: float(score) for i, score in zip(indices, scores, strict=True)}
        if not all(math.isfinite(value) for value in mapping.values()):
            raise ValueError("Non-finite relevance predictions")
        return sorted(
            indices, key=lambda i: (-mapping[i], self.engine.catalog[i]["entity_key"])
        ), mapping

    def support(self, prepared, i, selected=False, conflict=False):
        item = self.engine.catalog[i]
        terms = set(tokens(prepared["view"]["lexical"]))
        card = self.retriever.context_terms[i]
        coverage = len(terms & card) / max(len(terms), 1)
        subject_match = bool(prepared["subjects"] & card)
        cosine = prepared["e5"]["card"][i]
        exact = self.morph.lemmas(prepared["view"]["plan"].positive_query) == self.morph.lemmas(
            item["title"]
        )
        permitted = item["kind"] in USER_KINDS and not conflict
        lexical = coverage >= self.policy["lexical_min"] and subject_match
        semantic = cosine >= self.policy["semantic_min"] and subject_match
        strong = cosine >= self.policy["strong_semantic_min"]
        admitted = permitted and bool(selected or exact or lexical or semantic or strong)
        return {
            "admitted": admitted,
            "alternative": permitted and not admitted and cosine >= self.policy["semantic_min"],
            "card_coverage": round(coverage, 4),
            "card_cosine": round(cosine, 4),
            "exact_title": bool(exact),
            "explicit_selection": selected,
            "policy": "e5_relevance_v1",
            "semantic_only": strong and not subject_match,
        }

    def result(self, query, allowed=None, selected_keys=()):
        prepared = self.prepare(query, allowed, selected_keys)
        ranked, scores = self.score(prepared)
        return {**prepared, "ranked": ranked, "model_scores": scores}

    def conflict(self, prepared, i):
        plan = prepared["view"]["plan"]
        return (
            exclusion_multiplier(self.engine.retriever.title_terms[i], plan.excluded_terms) < 1
            or intent_multiplier(self.engine.catalog[i]["title"], plan) < 1
        )
