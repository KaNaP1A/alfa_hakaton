"""Rebuild an isolated catalog from a verified, already imported SQLite snapshot.

Never changes the source generation or the live catalog pointer.
"""
import argparse
import json
import shutil
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from alfa_reco.bundle import atomic_json, load_bundle, sha256
from alfa_reco.cli import clean, normalize, rows
from alfa_reco.content import enrich_content
from alfa_reco.lessons import attach_lessons, parse_as_of
from alfa_reco.suggestions import build_index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="artifacts/catalog")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path, old_manifest, old_catalog = load_bundle(args.source)
    source_db = path / "source.sqlite"
    if sha256(source_db) != old_manifest["source_sqlite_sha256"]:
        raise ValueError("Source SQLite checksum differs from its manifest")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    with closing(sqlite3.connect(source_db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        catalog, exclusions = normalize(conn)
        as_of = old_manifest.get("lesson_policy", {}).get("as_of")
        lesson_report = attach_lessons(catalog, rows(conn, "Lessons"),
                                       rows(conn, "CourseLessonBindings"), clean, parse_as_of(as_of))
        content_report = enrich_content(catalog, rows(conn, "ArticleEmbedItems"),
                                        rows(conn, "LessonEmbedItems"), rows(conn, "DocumentEmbedItems"))
    stage = output / "staging"
    stage.mkdir()
    atomic_json(stage / "catalog.json", catalog)
    digest = sha256(stage / "catalog.json")
    atomic_json(stage / "suggestions.json", build_index(catalog, digest))
    shutil.copy2(source_db, stage / "source.sqlite")
    if sha256(stage / "source.sqlite") != old_manifest["source_sqlite_sha256"]:
        raise ValueError("Source SQLite changed during copying")
    manifest = {**old_manifest, "schema_version": 4, "content_report": content_report,
                "lesson_policy": {"as_of": as_of, "counts": lesson_report},
                "catalog_count": len(catalog), "catalog_counts": dict(Counter(x["kind"] for x in catalog)),
                "exclusions": exclusions, "catalog_sha256": digest,
                "suggestions": {"sha256": sha256(stage / "suggestions.json")}, "semantic": None,
                "ranking": "bm25; relevance requires a newly trained compatible bundle",
                "source_generation": path.name,
                "profile_compatible_generations": [path.name] if
                    [x["entity_key"] for x in catalog] == [x["entity_key"] for x in old_catalog]
                    else []}
    atomic_json(stage / "manifest.json", manifest)
    name = "generation-" + manifest["backup_sha256"][:12] + "-" + digest[:12] + "-" + manifest["suggestions"]["sha256"][:12]
    stage.rename(output / name)
    atomic_json(output / "CURRENT.json", {"generation": name})
    print(json.dumps({"generation": name, "catalog": len(catalog), "lessons": lesson_report,
                      "content": content_report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
