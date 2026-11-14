"""Activate a rebuilt catalog only after verifying its compatible relevance bundle."""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from alfa_reco.bundle import atomic_json, load_bundle, sha256
from alfa_reco.search import SearchEngine
from alfa_reco.storage import output_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active", default="artifacts/catalog")
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    root = Path(args.active)
    candidate_path, candidate_manifest, new = load_bundle(args.candidate)
    old_path, old_manifest, old = load_bundle(root)
    if candidate_manifest.get("source_generation") != old_path.name:
        raise ValueError("The active catalog changed since the rebuild")
    if old_manifest["source_sqlite_sha256"] != candidate_manifest["source_sqlite_sha256"]:
        raise ValueError("The rebuilt catalog uses another source snapshot")
    old_items = {item["entity_key"]: item for item in old}
    new_items = {item["entity_key"]: item for item in new}
    if len(new_items) != len(new) or any(
        new_items.get(key) != item for key, item in old_items.items()
    ):
        raise ValueError("Profile migration requires all existing materials to remain unchanged")
    if any(
        lesson.get("is_trial") is not True for item in new for lesson in item.get("lessons", [])
    ):
        raise ValueError("Candidate contains a non-trial lesson")
    candidate_manifest["profile_compatible_generations"] = [old_path.name]
    atomic_json(candidate_path / "manifest.json", candidate_manifest)
    engine = SearchEngine(args.candidate)
    backend = engine.relevance_backend()
    probe = next(item for item in new if item["kind"] == "article")
    result = engine.search(probe["title"], mode="relevance")
    if not result["results"] or result["results"][0]["entity_key"] != probe["entity_key"]:
        raise ValueError("Candidate relevance smoke test failed")
    if result["results"][0]["price"]["status"] != "free":
        raise ValueError("Article price fact was not returned")
    course = next(item for item in new if item["kind"] == "course" and item["price_raw"] is None)
    course_result = engine.search(course["title"], mode="relevance")
    if not course_result["results"] or course_result["results"][0]["price"]["status"] != "free":
        raise ValueError("Course price fact was not returned")
    pointer = json.loads((candidate_path / "relevance" / "CURRENT.json").read_text())
    model_dir = candidate_path / "relevance" / pointer["generation"]
    if backend.manifest["catalog_sha256"] != candidate_manifest["catalog_sha256"]:
        raise ValueError("Candidate ranker belongs to another catalog")
    expected = {
        "catalog.json": candidate_manifest["catalog_sha256"],
        "suggestions.json": candidate_manifest["suggestions"]["sha256"],
        "source.sqlite": candidate_manifest["source_sqlite_sha256"],
        "relevance/" + pointer["generation"] + "/ranker.cbm": sha256(model_dir / "ranker.cbm"),
        "relevance/" + pointer["generation"] + "/vectors.npz": sha256(model_dir / "vectors.npz"),
        "relevance/" + pointer["generation"] + "/normalized_catalog.json": sha256(
            model_dir / "normalized_catalog.json"
        ),
    }
    with output_lock(root):
        current_path, _, _ = load_bundle(root)
        if current_path != old_path:
            raise ValueError("The active catalog changed during verification")
        destination = root / candidate_path.name
        if destination.exists():
            raise ValueError("Generation already exists; refusing to overwrite")
        with tempfile.TemporaryDirectory(dir=root) as directory:
            staged = Path(directory) / candidate_path.name
            shutil.copytree(candidate_path, staged)
            for name, digest in expected.items():
                if sha256(staged / name) != digest:
                    raise ValueError("Copied artifact checksum mismatch: " + name)
            os.replace(staged, destination)
        atomic_json(root / "CURRENT.json", {"generation": destination.name})
    print(
        json.dumps(
            {
                "previous_generation": old_path.name,
                "active_generation": destination.name,
                "search_smoke_results": len(result["results"]),
                "profile_compatible": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
