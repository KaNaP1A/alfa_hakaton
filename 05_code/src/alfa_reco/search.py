"""Reusable search engine: load artifacts once, preserve the user's query."""

import json
import threading

from .suggestions import SuggestionIndex, validate_query
from .text import tokens


class SearchEngine:
    def __init__(self, output, semantic=False):
        # Import here to keep CLI compatibility without circular initialization.
        from .cli import load_bundle, model, sha256

        self.path, self.manifest, self.catalog = load_bundle(output)
        self.generation = self.path.name
        self.suggestions = None
        spec = self.manifest.get("suggestions")
        if spec:
            path = self.path / "suggestions.json"
            if sha256(path) != spec["sha256"]:
                raise ValueError("Suggestion index hash mismatch")
            data = json.loads(path.read_text())
            if data["catalog_sha256"] != self.manifest["catalog_sha256"]:
                raise ValueError("Suggestion index belongs to another catalog")
            self.suggestions = SuggestionIndex(data, self.catalog, self.generation)
        from .retrieval import FieldRetriever

        self.retriever = FieldRetriever(self.catalog)
        self.units = None
        self.ranker = None
        self.encoder = None
        self.vectors = None
        self.encoder_lock = threading.Lock()
        self.vocabulary = set().union(*self.retriever.term_sets)
        if semantic:
            import numpy as np

            sem = self.manifest.get("semantic")
            if not sem or sem["catalog_sha256"] != self.manifest["catalog_sha256"]:
                raise ValueError("Build embeddings for this catalog first")
            if sha256(self.path / "vectors.npy") != sem["vectors_sha256"]:
                raise ValueError("Vector hash mismatch")
            self.vectors = np.load(self.path / "vectors.npy", allow_pickle=False)
            expected = sem.get("unit_count", len(self.catalog))
            if self.vectors.shape != (expected, sem["dimensions"]):
                raise ValueError("Vector dimensions mismatch")
            if "unit_count" in sem:
                unit_path = self.path / "units.json"
                if sha256(unit_path) != sem["units_sha256"]:
                    raise ValueError("Units hash mismatch")
                self.units = json.loads(unit_path.read_text())
                if len(self.units) != expected:
                    raise ValueError("Unit count mismatch")
                index = {item["entity_key"]: i for i, item in enumerate(self.catalog)}
                self.unit_indices = np.array([index[unit["entity_key"]] for unit in self.units])
                self.unit_masks = {
                    source: np.array([unit["source"] == source for unit in self.units])
                    for source in ("card", "body", "lesson")
                }
            self.encoder = model(sem["local_path"])

    def dense_signals(self, query):
        import numpy as np

        if self.encoder is None:
            raise ValueError("Engine started without embeddings")
        with self.encoder_lock:
            vector = self.encoder.encode([query], normalize_embeddings=True)
        raw = self.vectors @ vector[0]
        result = {
            source: np.zeros(len(self.catalog), dtype=np.float32)
            for source in ("card", "body", "lesson")
        }
        if self.units is None:
            result["card"] = raw
        else:
            for source, mask in self.unit_masks.items():
                np.maximum.at(result[source], self.unit_indices[mask], raw[mask])
        return {key: values.tolist() for key, values in result.items()}

    def suggest(self, query, limit=6):
        if not self.suggestions:
            raise ValueError("Build the suggestion index first")
        return self.suggestions.suggest(query, limit)

    def search(
        self,
        query,
        mode="hybrid",
        top=5,
        kind=None,
        selection_id=None,
        selection_generation=None,
    ):
        from .cli import KINDS

        validate_query(query)
        if not query.strip():
            raise ValueError("Enter a non-empty query")
        if mode not in {"bm25", "hybrid", "catboost"}:
            raise ValueError("Unsupported search mode")
        if not 1 <= top <= 50:
            raise ValueError("top must be between 1 and 50")
        if kind is not None and kind not in KINDS.values():
            raise ValueError("Unsupported material kind")
        if bool(selection_id) != bool(selection_generation):
            raise ValueError("selection_id and selection_generation must be supplied together")
        selection = None
        if selection_id:
            if self.suggestions is None:
                raise ValueError("Build the suggestion index first")
            selection = self.suggestions.resolve(selection_id, selection_generation)
        allowed = {i for i, item in enumerate(self.catalog) if kind is None or item["kind"] == kind}
        from .retrieval import RankingConfig

        config = RankingConfig()
        config_path = self.path / "ranking_config.json"
        if config_path.exists():
            config = RankingConfig(**json.loads(config_path.read_text())["parameters"])
        semantic = mode in {"hybrid", "catboost"}
        dense_by_source = self.dense_signals(query) if semantic else None
        selected_keys = set(selection["entity_keys"]) if selection else set()
        signals = self.retriever.signals(query, dense_by_source, selected_keys)
        ranked, lexical, dense_values, fused, ranks = self.retriever.rank(
            signals, config, allowed, semantic
        )
        dense = dense_values if semantic else None
        if mode == "catboost":
            from .cli import sha256

            model_path = self.path / "catboost.cbm"
            meta_path = self.path / "catboost_meta.json"
            if not meta_path.exists() or not model_path.exists():
                raise ValueError("Experimental CatBoost model is unavailable for this catalog")
            meta = json.loads(meta_path.read_text())
            if meta.get("catalog_sha256") != self.manifest["catalog_sha256"] or sha256(
                model_path
            ) != meta.get("model_sha256"):
                raise ValueError("CatBoost artifact does not match catalog or is corrupt")
            try:
                from catboost import CatBoostRanker
            except ImportError as error:
                raise ValueError("Install CatBoost to use this experimental mode") from error
            with self.encoder_lock:
                if self.ranker is None:
                    self.ranker = CatBoostRanker()
                    self.ranker.load_model(str(model_path))
                predictions = (
                    self.ranker.predict([signals["features"][i] for i in ranked]) if ranked else []
                )
            ranked = [i for _, i in sorted(zip(-predictions, ranked, strict=True))]
            if selection:
                model_rank = {i: rank + 1 for rank, i in enumerate(ranked)}
                ranked.sort(
                    key=lambda i: (
                        -(1 / (config.rrf_k + model_rank[i]))
                        * (
                            1
                            + config.selection_boost
                            * signals["features"][i][10]
                            * signals["features"][i][12]
                        ),
                        self.catalog[i]["entity_key"],
                    )
                )
        ranked = ranked[:60]
        results = []
        query_terms = set(tokens(query))
        for i in ranked[:top]:
            item = self.catalog[i]
            matched_lessons = [
                {
                    "lesson_id": lesson["lesson_id"],
                    "title": lesson["title"],
                    "direct_access_verified": False,
                }
                for lesson in item.get("lessons", [])
                if query_terms & set(tokens(lesson["title"] + " " + lesson["description"]))
            ][:3]
            results.append(
                {
                    **{
                        key: item[key]
                        for key in [
                            "entity_key",
                            "kind",
                            "title",
                            "description",
                            "topics",
                            "tags",
                            "industries",
                            "access_type",
                            "source_url",
                            "canonical_url",
                            "data_quality_flags",
                        ]
                    },
                    "scores": {
                        "bm25": round(lexical[i], 5),
                        "cosine": round(dense[i], 5) if dense is not None else None,
                        "rrf": round(fused[i], 6),
                    },
                    "matched_words": sorted(query_terms & self.retriever.term_sets[i]),
                    "source_ranks": {
                        channel: rank[i] for channel, rank in ranks.items() if i in rank
                    },
                    "selection_match": item["entity_key"] in selected_keys,
                    "matched_lessons": matched_lessons,
                }
            )
        return {
            "query": query,
            "generation": self.generation,
            "mode": "catboost_experimental"
            if mode == "catboost"
            else "hybrid_rrf"
            if mode == "hybrid"
            else "bm25_rrf"
            if selection
            else "bm25",
            "catalog_count": len(self.catalog),
            "model_trained": mode == "catboost",
            "selection": {"id": selection_id, "label": selection["label"]} if selection else None,
            "unmatched_query_terms": sorted(query_terms - self.vocabulary),
            "coverage": "unknown" if results else "none",
            "notice": "Candidate search; weights and relevance thresholds are not validated.",
            "results": results,
        }
