"""Reusable search engine: load artifacts once, preserve the user's query."""

import json
import threading

from .retrieval import COVERAGE_COLUMN, SELECTION_COLUMN, RankingConfig
from .suggestions import SuggestionIndex, validate_query
from .text import tokens


class SearchEngine:
    def __init__(self, output, semantic=False, llm_enabled=False):
        from .bundle import load_bundle, model, sha256

        self.path, self.manifest, self.catalog = load_bundle(output)
        from .verified_links import apply_verified_links

        apply_verified_links(self.catalog)
        self.generation = self.path.name
        from .clarifications import ClarificationTokens

        self.clarifications = ClarificationTokens(self.generation, self.catalog)
        from .query_interpreter import OllamaInterpreter

        self.interpreter = OllamaInterpreter() if llm_enabled else None
        self.suggestions = None
        spec = self.manifest.get("suggestions")
        if spec:
            path = self.path / "suggestions.json"
            if sha256(path) != spec["sha256"]:
                raise ValueError("Suggestion index hash mismatch")
            data = json.loads(path.read_text())
            if data["catalog_sha256"] != self.manifest["catalog_sha256"]:
                raise ValueError("Suggestion index belongs to another catalog")
            eligible = {item["entity_key"] for item in self.catalog if item["kind"] != "glossary"}
            entries = [
                {**entry, "entity_keys": [key for key in entry["entity_keys"] if key in eligible]}
                for entry in data["entries"]
            ]
            data = {**data, "entries": [entry for entry in entries if entry["entity_keys"]]}
            self.suggestions = SuggestionIndex(data, self.catalog, self.generation)
        from .retrieval import FieldRetriever

        self.retriever = FieldRetriever(self.catalog)
        self.ranking_config = RankingConfig()
        config_path = self.path / "ranking_config.json"
        if config_path.exists():
            config_data = json.loads(config_path.read_text())
            if config_data.get("catalog_sha256") != self.manifest["catalog_sha256"]:
                raise ValueError("Ranking configuration belongs to a different catalog")
            self.ranking_config = RankingConfig(**config_data["parameters"])
        self.units = None
        self.rankers = {}
        self._relevance = None
        self.encoder = None
        self.vectors = None
        self.encoder_lock = threading.Lock()
        self.vocabulary = set().union(*self.retriever.term_sets)
        self.card_vocabulary = set().union(*self.retriever.context_terms)
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
            if sem.get("local_path") and sem.get("local_model_fingerprint"):
                from .bundle import model_fingerprint

                if model_fingerprint(sem["local_path"]) != sem["local_model_fingerprint"]:
                    raise ValueError("Embedding model files differ from the indexed model")
            self.encoder = model(sem["local_path"])

    def dense_signals(self, query):
        import numpy as np

        from .text import embedding_query

        if self.encoder is None:
            raise ValueError("Engine started without embeddings")
        with self.encoder_lock:
            vector = self.encoder.encode([embedding_query(query)], normalize_embeddings=True)
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

    def relevance_backend(self):
        if self._relevance is None:
            from .relevance import RelevanceBackend

            with self.encoder_lock:
                if self._relevance is None:
                    self._relevance = RelevanceBackend(self)
        return self._relevance

    def _model_order(self, mode, ranked, signals, config=None):
        from .bundle import sha256
        from .retrieval import FEATURE_NAMES

        if mode != "catboost":
            raise ValueError("Unsupported CatBoost mode")
        # Existing filename kept for backward-compatible artifacts; only this ranker is used.
        prefix = "catboost_small"
        model_path = self.path / (prefix + ".cbm")
        meta_path = self.path / (prefix + "_meta.json")
        if not meta_path.exists() or not model_path.exists():
            raise ValueError("Experimental CatBoost model is unavailable for this catalog")
        meta = json.loads(meta_path.read_text())
        config = config or self.ranking_config
        trained_config = RankingConfig(**meta.get("retrieval_parameters", {}))
        if (config.bm25_k1, config.bm25_b) != (trained_config.bm25_k1, trained_config.bm25_b):
            raise ValueError("CatBoost BM25 features changed; retrain the model first")
        if (
            meta.get("catalog_sha256") != self.manifest["catalog_sha256"]
            or meta.get("vectors_sha256") != self.manifest.get("semantic", {}).get("vectors_sha256")
            or not meta.get("vectors_sha256")
            or sha256(model_path) != meta.get("model_sha256")
        ):
            raise ValueError("CatBoost artifact does not match catalog/embeddings or is corrupt")
        try:
            from catboost import CatBoostRanker
        except ImportError as error:
            raise ValueError("Install CatBoost to use this experimental mode") from error
        feature_names = meta.get("feature_names", FEATURE_NAMES)
        if len(set(feature_names)) != len(feature_names) or any(
            name not in FEATURE_NAMES for name in feature_names
        ):
            raise ValueError("Unsupported CatBoost feature schema")
        feature_columns = [FEATURE_NAMES.index(name) for name in feature_names]
        with self.encoder_lock:
            if prefix not in self.rankers:
                ranker = CatBoostRanker()
                ranker.load_model(str(model_path))
                if ranker.feature_names_ != feature_names:
                    raise ValueError("CatBoost model feature names do not match metadata")
                self.rankers[prefix] = ranker
            predictions = (
                self.rankers[prefix].predict(
                    [[signals["features"][i][column] for column in feature_columns] for i in ranked]
                )
                if ranked
                else []
            )
        model_scores = {i: float(score) for i, score in zip(ranked, predictions, strict=True)}
        ranked = sorted(ranked, key=lambda i: (-model_scores[i], self.catalog[i]["entity_key"]))
        return ranked, model_scores

    def component_rankings(self, query, signals, allowed, config):
        """Run all components over a shared candidate calculation."""
        # Apply a selected topic exactly once after fusion, not inside a component.
        neutral = signals
        if any(row[SELECTION_COLUMN] for row in signals["features"]):
            neutral = {
                **signals,
                "features": [
                    row[:SELECTION_COLUMN] + [0.0] + row[SELECTION_COLUMN + 1 :]
                    for row in signals["features"]
                ],
            }
        hybrid, lexical, dense, fused, ranks = self.retriever.rank(neutral, config, allowed, True)
        bm25, *_ = self.retriever.rank(neutral, config, allowed, False)
        catboost, model_scores = self._model_order("catboost", list(hybrid), neutral, config)
        lists = {
            "bm25": bm25[:60],
            "hybrid": hybrid[:60],
            "catboost": catboost[:60],
        }
        return lists, lexical, dense, fused, ranks, model_scores

    def _ensemble_weights(self, config=None):
        from .bundle import sha256
        from .ensemble import validate_weights
        from .retrieval import RankingConfig

        path = self.path / "ensemble_config.json"
        if not path.exists():
            raise ValueError("Ensemble weights are unavailable for this catalog; run calibration")
        data = json.loads(path.read_text())
        if data.get("catalog_sha256") != self.manifest["catalog_sha256"] or data.get(
            "vectors_sha256"
        ) != self.manifest.get("semantic", {}).get("vectors_sha256"):
            raise ValueError("Ensemble weights do not match catalog or vectors")
        if RankingConfig(**data["retrieval_parameters"]) != (config or self.ranking_config):
            raise ValueError("Ensemble weights do not match the retrieval configuration")
        if data.get("rrf_k", 60) != 60 or data.get("top_per_method", 60) != 60:
            raise ValueError("Unsupported ensemble fusion configuration; recalibrate first")
        if data.get("model_sha256") != sha256(self.path / "catboost_small.cbm"):
            raise ValueError("Ensemble weights do not match the trained model")
        validate_weights(data["weights"])
        bonus = data.get("llm_boost", 0.0)
        if not isinstance(bonus, (int, float)) or not 0 <= bonus <= 0.2:
            raise ValueError("Invalid LLM boost")
        return data

    def search(
        self,
        query,
        mode="relevance",
        top=5,
        kind=None,
        selection_id=None,
        selection_generation=None,
        clarification_token=None,
        clarification_text=None,
        *,
        ranking_config=None,
    ):
        from .eligibility import USER_KINDS, candidate_support
        from .pricing import price_fact

        validate_query(query)
        if not query.strip():
            raise ValueError("Enter a non-empty query")
        if mode not in {"hybrid", "catboost", "ensemble", "relevance"}:
            raise ValueError("Unsupported search mode")
        if type(top) is not int or not 1 <= top <= 50:
            raise ValueError("top must be between 1 and 50")
        if kind is not None and (kind not in USER_KINDS):
            raise ValueError("Unsupported material kind")
        if bool(selection_id) != bool(selection_generation):
            raise ValueError("selection_id and selection_generation must be supplied together")
        if clarification_token and clarification_text:
            raise ValueError("Choose either a clarification option or text")
        if (clarification_token or clarification_text) and selection_id:
            raise ValueError("Choose either a suggestion or clarification")
        if clarification_text is not None:
            validate_query(clarification_text)
            if not clarification_text.strip() or len(clarification_text) > 100:
                raise ValueError("Clarification must contain 1 to 100 characters")
        focus = (
            self.clarifications.resolve(query, clarification_token) if clarification_token else None
        )
        selection = None
        if selection_id:
            if self.suggestions is None:
                raise ValueError("Build the suggestion index first")
            selection = self.suggestions.resolve(selection_id, selection_generation)
            if selection["kind"] == "title":
                chosen = next(
                    (
                        item
                        for item in self.catalog
                        if item["entity_key"] in selection["entity_keys"]
                        and item["title"] == selection["label"]
                        and item["kind"] != "glossary"
                    ),
                    None,
                )
                if chosen:
                    focus = {
                        "kind": "material",
                        "entity_key": chosen["entity_key"],
                        "label": chosen["title"],
                    }
        from .query_rules import (
            MONEY,
            PEOPLE_CONTEXT,
            exclusion_multiplier,
            intent_multiplier,
            plan_query,
        )
        from .request_understanding import (
            OPPOSITES,
            actions,
            ambiguous_contrast_reference,
            analyze_request,
            opposite_title_intent,
            weak_intent_support,
        )

        original_plan = plan_query(query)
        understanding = analyze_request(query)
        selected_material = bool(focus and focus["kind"] == "material")
        requested_kind = understanding["format"]
        format_conflict = bool(requested_kind and (
            (kind and requested_kind != kind)
            or (selected_material and self.catalog[next(
                i for i, item in enumerate(self.catalog) if item["entity_key"] == focus["entity_key"]
            )]["kind"] != requested_kind)
        ))
        inferred_kind = requested_kind if not kind and not selected_material else None
        applied_kind = kind or inferred_kind
        # Explicitly chosen material changes focus; the original constraints stay visible.
        base_query = understanding["search_query"] if inferred_kind or (requested_kind and kind == requested_kind) else query
        effective_query = (
            focus["label"]
            if selected_material
            else " ".join(
                part for part in [base_query, focus["label"] if focus else clarification_text] if part
            )
        )
        plan = plan_query(effective_query)
        retrieval_query = plan.retrieval_query
        unresolved_reference = ambiguous_contrast_reference(plan) or (
            selected_material and ambiguous_contrast_reference(original_plan)
        )
        supported_actions = actions(plan.positive_query)
        action_kinds = {row["kind"] for row in supported_actions}
        ambiguous_intent = any(OPPOSITES[name] in action_kinds for name in action_kinds)
        # Do not infer the scope of complex negations or override a chosen material.
        active_actions = supported_actions if not (
            ambiguous_intent or unresolved_reference or plan.unresolved_negation
            or original_plan.unresolved_negation or selected_material
        ) else []
        extra_constraints = set(understanding["unsupported_constraints"])
        if format_conflict:
            extra_constraints.add("format")
        if ambiguous_intent:
            extra_constraints.add("intent")

        allowed = {
            i
            for i, item in enumerate(self.catalog)
            if item["kind"] in USER_KINDS and (applied_kind is None or item["kind"] == applied_kind)
        }
        if unresolved_reference and not selected_material:
            allowed.clear()
        focus_index = next(
            (
                i
                for i in allowed
                if focus and focus.get("entity_key") == self.catalog[i]["entity_key"]
            ),
            None,
        )
        if focus and focus["kind"] == "material" and focus_index is None:
            raise ValueError(
                "Выбранный материал не соответствует фильтру типа. Уберите фильтр и повторите поиск."
            )
        # Explicit override is for offline experiments; HTTP never accepts ranking parameters.
        config = self.ranking_config if ranking_config is None else ranking_config
        if not isinstance(config, RankingConfig):
            raise ValueError("ranking_config must be a RankingConfig")
        semantic = mode in {"hybrid", "catboost", "ensemble"}
        dense_by_source = self.dense_signals(retrieval_query) if semantic else None
        selected_keys = set(selection["entity_keys"]) if selection else set()
        relevance = None
        if mode == "relevance":
            backend = self.relevance_backend()
            if config != backend.config:
                raise ValueError("Relevance model does not match ranking parameters")
            relevance = backend.result(effective_query, allowed, selected_keys)
            dense_by_source = relevance["dense"]
            signals = relevance["signals"]
        else:
            signals = self.retriever.signals(
                retrieval_query, dense_by_source, selected_keys, config=config
            )
        ranked = []
        lexical = dense = fused = ranks = None
        if mode == "relevance":
            ranked = relevance["ranked"]
            lexical = relevance["lexical"]
            dense = dense_by_source["card"]
            fused, ranks = relevance["fused"], relevance["ranks"]
        elif mode != "ensemble":
            ranked, lexical, dense_values, fused, ranks = self.retriever.rank(
                signals, config, allowed, semantic
            )
            dense = dense_values if semantic else None
        model_scores = relevance["model_scores"] if relevance is not None else {}
        ensemble_scores = {}
        contribution_by_item = {}
        component_ranks = {}
        interpretation = {
            "status": "disabled",
            "route": "disabled",
            "goal": "",
            "object": "",
            "constraints": [],
            "negation_present": False,
            "discarded": 0,
        }
        llm_applied = False
        llm_bonus_by_item = {}
        if mode == "ensemble":
            from .ensemble import fuse

            ensemble_config = self._ensemble_weights(config)
            weights = ensemble_config["weights"]
            if self.interpreter is not None and not (focus and focus["kind"] == "material"):
                interpretation = self.interpreter.analyze(effective_query)
            lists, lexical, dense_values, fused, ranks, model_scores = self.component_rankings(
                retrieval_query, signals, allowed, config
            )
            dense = dense_values
            ensemble_scores, contribution_by_item = fuse(lists, weights)
            component_ranks = {
                name: {i: rank + 1 for rank, i in enumerate(items)} for name, items in lists.items()
            }
            from .query_interpreter import grounded_match

            boost = ensemble_config.get("llm_boost", 0.0)
            expected_digest = ensemble_config.get("llm_digest")
            model_matches = bool(
                boost
                and expected_digest
                and interpretation.get("status") == "ok"
                and not interpretation.get("negation_present")
                and self.interpreter is not None
                and self.interpreter.model == ensemble_config.get("llm_model")
                and self.interpreter.model_digest() == expected_digest
            )
            for i in ensemble_scores:
                score = (
                    grounded_match(interpretation, self.retriever.context_terms[i])
                    if model_matches
                    else 0.0
                )
                llm_bonus_by_item[i] = score
                llm_applied = llm_applied or bool(score)
                ensemble_scores[i] *= 1 + boost * score
                ensemble_scores[i] *= (
                    1
                    + config.selection_boost
                    * signals["features"][i][COVERAGE_COLUMN]
                    * signals["features"][i][SELECTION_COLUMN]
                )
                ensemble_scores[i] *= exclusion_multiplier(
                    self.retriever.title_terms[i], plan.excluded_terms
                )
                ensemble_scores[i] *= intent_multiplier(self.catalog[i]["title"], plan)
            ranked = sorted(
                ensemble_scores, key=lambda i: (-ensemble_scores[i], self.catalog[i]["entity_key"])
            )
        elif mode == "catboost":
            ranked, model_scores = self._model_order(mode, ranked, signals, config)
        if mode in {"catboost", "relevance"} and selection:
            model_rank = {i: rank + 1 for rank, i in enumerate(ranked)}
            ranked.sort(
                key=lambda i: (
                    -(1 / (config.rrf_k + model_rank[i]))
                    * (
                        1
                        + config.selection_boost
                        * signals["features"][i][COVERAGE_COLUMN]
                        * signals["features"][i][SELECTION_COLUMN]
                    ),
                    self.catalog[i]["entity_key"],
                )
            )
        ranking_scores = dict(
            ensemble_scores
            if mode == "ensemble"
            else model_scores
            if mode in {"catboost", "relevance"}
            else fused
        )
        if mode in {"catboost", "relevance"} and selection:
            ranking_scores = {
                i: (1 / (config.rrf_k + model_rank[i]))
                * (
                    1
                    + config.selection_boost
                    * signals["features"][i][COVERAGE_COLUMN]
                    * signals["features"][i][SELECTION_COLUMN]
                )
                for i in ranked
            }
        if mode != "ensemble" and (
            plan.excluded_terms or plan.retention_expansion or plan.debt_expansion
        ):
            prior = {i: rank + 1 for rank, i in enumerate(ranked)}
            ranking_scores = {
                i: exclusion_multiplier(self.retriever.title_terms[i], plan.excluded_terms)
                * intent_multiplier(self.catalog[i]["title"], plan)
                / (config.rrf_k + prior[i])
                for i in ranked
            }
            ranked.sort(key=lambda i: (-ranking_scores[i], self.catalog[i]["entity_key"]))
        exact_indices = [
            i
            for i in allowed
            if tokens(plan.positive_query)
            and tokens(plan.positive_query) == tokens(self.catalog[i]["title"].rstrip(" ,.;!?"))
        ]
        priority = ([focus_index] if focus_index is not None else []) + sorted(
            exact_indices, key=lambda i: self.catalog[i]["entity_key"]
        )
        ranked = list(dict.fromkeys(priority + ranked))[:60]
        candidates = []
        from .evidence import coverage_signal, evidence_for

        query_terms = set(tokens(plan.positive_query))
        from .promotions import promotion_for

        admitted_count = baseline_admitted_count = alternative_count = rejected_count = conflict_count = 0
        for i in ranked:
            item = self.catalog[i]
            conflict = (exclusion_multiplier(self.retriever.title_terms[i], plan.excluded_terms) < 1
                        or intent_multiplier(item["title"], plan) < 1
                        or opposite_title_intent(active_actions, item["title"]))
            if ({row["kind"] for row in active_actions} == {"retain_employees"}
                    and MONEY.search(item["title"]) and not PEOPLE_CONTEXT.search(item["title"])):
                conflict = True
            conflict_count += bool(conflict)
            support = (
                self.relevance_backend().support(
                    relevance,
                    i,
                    selected=i == focus_index,
                    conflict=conflict,
                )
                if relevance is not None
                else candidate_support(
                    plan.retrieval_query,
                    item,
                    dense_by_source["card"][i] if dense_by_source else None,
                    dense_by_source["lesson"][i] if dense_by_source else None,
                    selected=i == focus_index,
                    conflict=conflict,
                )
            )
            if relevance is not None:
                # Keep the model's expanded-query features; expose the user's
                # unexpanded terms separately for diagnosis and weak matching.
                original_terms = set(tokens(plan.positive_query))
                original_overlap = original_terms & self.retriever.context_terms[i]
                support["unexpanded_card_coverage"] = round(
                    len(original_overlap) / max(len(original_terms), 1), 4
                )
                cosine = relevance["dense"]["card"][i]
                weak_evidence = (weak_intent_support(active_actions, item, cosine, conflict=conflict)
                                 if not support["admitted"] and cosine < backend.policy["semantic_min"]
                                 else None)
                support["weak_intent_match"] = bool(weak_evidence)
                support["weak_intent_evidence"] = weak_evidence
                if weak_evidence:
                    support.update(admitted=True, alternative=False)
            if not support["admitted"] and not support["alternative"]:
                rejected_count += 1
                continue
            if support["admitted"]:
                if not support.get("weak_intent_match"):
                    if baseline_admitted_count >= top:
                        continue
                    baseline_admitted_count += 1
                admitted_count += 1
            else:
                if alternative_count >= min(top, 3):
                    continue
                alternative_count += 1
            source_ranks = {channel: rank[i] for channel, rank in ranks.items() if i in rank}
            matched_lessons = [
                {
                    "lesson_id": lesson["lesson_id"],
                    "title": lesson["title"],
                    "direct_access_verified": False,
                }
                for lesson in item.get("lessons", [])
                if query_terms & set(tokens(lesson["title"] + " " + lesson["description"]))
            ][:3]
            candidates.append(
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
                    "promotion": promotion_for(item),
                    "price": price_fact(item),
                    "target_audience": item.get("target_audience", ""),
                    "support": support,
                    "scores": {
                        "bm25": round(lexical[i], 5),
                        "cosine": round(dense[i], 5) if dense is not None else None,
                        "rrf": round(fused.get(i, 0.0), 6),
                        "catboost": round(model_scores[i], 6) if i in model_scores else None,
                        "final_score": round(ranking_scores.get(i, 0.0), 8),
                    },
                    "ranking_override": "explicit_selection"
                    if i == focus_index
                    else "exact_title"
                    if i in exact_indices
                    else None,
                    "matched_words": sorted(query_terms & self.retriever.term_sets[i]),
                    "source_ranks": source_ranks,
                    "ensemble_ranks": {
                        name: ranks[i] for name, ranks in component_ranks.items() if i in ranks
                    },
                    "ensemble_contributions": {
                        name: round(value, 6)
                        for name, value in contribution_by_item.get(i, {}).items()
                    },
                    "llm_grounded_match": round(llm_bonus_by_item.get(i, 0.0), 6)
                    if mode == "ensemble"
                    else None,
                    "selection_multiplier": round(
                        1
                        + config.selection_boost
                        * signals["features"][i][COVERAGE_COLUMN]
                        * signals["features"][i][SELECTION_COLUMN],
                        6,
                    )
                    if mode == "ensemble"
                    else None,
                    "selection_match": item["entity_key"] in selected_keys,
                    "matched_lessons": matched_lessons,
                    "evidence": evidence_for(
                        item, plan.positive_query, source_ranks, item["entity_key"] in selected_keys
                    ),
                }
            )
        from .personalization import clarification

        results = [item for item in candidates if item["support"]["admitted"]][:top]
        if any(item["support"].get("weak_intent_match") for item in candidates):
            results = [item for item in candidates if item["support"]["admitted"]]
            # Explicit topic words are evidence, not a learned relevance score.
            results.sort(key=lambda item: (
                0 if item["support"].get("exact_title") or item["support"].get("explicit_selection")
                else 1 if item["support"].get("weak_intent_evidence") == "title"
                else 2 if not item["support"].get("weak_intent_match") else 3,
            ))
            results = results[:top]
        alternatives = [item for item in candidates if item["support"]["alternative"]][
            : min(top, 3)
        ]
        coverage = coverage_signal(plan.positive_query, self.card_vocabulary) if results else "none"
        from .confidence import assess_results

        confidence = assess_results(results, (plan, original_plan))
        if unresolved_reference:
            confidence.update(status="uncertain", reason="unresolved_negation")
        all_unsupported = sorted(
            set(plan.unsupported_constraints) | set(original_plan.unsupported_constraints) | extra_constraints
        )
        if all_unsupported and confidence.get("reason") != "unresolved_negation":
            confidence.update(status="uncertain", reason="unverified_constraint")
        if any(item["support"].get("weak_intent_match") for item in results) and not confidence.get("reason"):
            confidence.update(status="uncertain", reason="weak_intent_match")
        if relevance is not None:
            confidence.update(policy="e5_relevance_v1", **backend.policy)
        choices = ([*results, *alternatives] if active_actions else [
            {**self.catalog[i], "matched_words": sorted(query_terms & self.retriever.term_sets[i])}
            for i in ranked[:10]
        ])
        question = (
            clarification(
                plan.positive_query,
                choices,
                needs_context=not results
                or all(item["support"]["card_coverage"] < 0.85 for item in results),
            )
            if not (focus or selection or clarification_text)
            and not any(item["support"]["exact_title"] for item in results)
            else None
        )
        if (unresolved_reference or ambiguous_intent or format_conflict or "format" in extra_constraints) and not (
            focus or selection or clarification_text
        ):
            question = {
                "question": ("Уточните, кого или что вы хотите удержать или изменить."
                             if unresolved_reference
                             else "Уточните, какое действие и какой формат материала вам нужны."),
                "options": [],
                "allow_text": True,
            }
        if not question and not results and not alternatives and not (focus or selection or clarification_text):
            question = {"question": "Не удалось подобрать материал. Уточните, что именно вам нужно.",
                        "options": [], "allow_text": True}
        if question:
            question = {
                **question,
                "options": [
                    {
                        "label": option["label"],
                        "kind": option["kind"],
                        "token": self.clarifications.issue(query, option),
                    }
                    for option in question["options"]
                ],
            }
        return {
            "query": query,
            "generation": self.generation,
            "focus": focus
            or ({"kind": "text", "label": clarification_text} if clarification_text else None),
            "mode": mode + "_experimental"
            if mode in {"ensemble", "catboost", "relevance"}
            else "hybrid_rrf",
            "catalog_count": len(self.catalog),
            "model_trained": mode in {"ensemble", "catboost", "relevance"},
            "relevance_profile": {
                "normalization": relevance["view"]["normalization"],
                "canonicalized": relevance["view"]["canonicalized"],
                "encoder": "intfloat/multilingual-e5-small",
                "independent_human_validation": False,
            }
            if relevance is not None
            else None,
            "ensemble_weights": weights if mode == "ensemble" else None,
            "query_interpretation": interpretation,
            "retrieval_diagnostics": {
                "retrieved_candidates": len(relevance["ranked"]) if relevance is not None else len(ranked),
                "considered_candidates": len(ranked),
                "rejected_candidates": rejected_count,
                "title_conflicts": conflict_count,
                "shown_results": len(results),
                "shown_alternatives": len(alternatives),
            },
            "request_understanding": {
                "format": requested_kind,
                "format_text": understanding["format_text"],
                "applied_format": applied_kind,
                "format_conflict": format_conflict,
                "actions": actions(original_plan.positive_query),
                "actions_applied": bool(active_actions),
                "audience_text": understanding["audience_text"],
                "audience_verified": False,
                "model_query": effective_query,
                "method": "narrow_rules_v1",
            },
            "query_rules": {
                "contrast_applied": plan.contrast_applied,
                "excluded_terms": list(plan.excluded_terms),
                "retention_expansion": plan.retention_expansion,
                "unresolved_negation": plan.unresolved_negation or original_plan.unresolved_negation or unresolved_reference,
                "debt_expansion": plan.debt_expansion,
                "debt_unspecified": plan.debt_unspecified,
                "synonym_rules": list(plan.synonym_rules),
                "unsupported_constraints": all_unsupported,
            },
            "llm_ranking_applied": llm_applied,
            "selection": {"id": selection_id, "label": selection["label"]} if selection else None,
            "unmatched_query_terms": sorted(query_terms - self.vocabulary),
            "coverage": coverage,
            "confidence": confidence,
            "clarification": question,
            "alternatives": alternatives,
            "notice": "Candidate search; weights and relevance thresholds are not validated.",
            "results": results,
        }
