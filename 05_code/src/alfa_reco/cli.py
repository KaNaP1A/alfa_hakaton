"""Import PostgreSQL custom dumps as data, normalize a catalog, search locally.
Never executes SQL or JavaScript stored in source records.
"""

import argparse
import html
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

from .bundle import MODEL_ID as MODEL_ID
from .bundle import MODEL_REVISION as MODEL_REVISION
from .bundle import atomic_json as atomic_json
from .bundle import load_bundle as load_bundle
from .bundle import model as model
from .bundle import model_fingerprint as model_fingerprint
from .bundle import sha256 as sha256
from .lessons import attach_lessons, parse_as_of

KINDS = {
    "Articles": "article",
    "Courses": "course",
    "Documents": "document",
    "Webinars": "webinar",
    "Podcasts": "podcast",
    "Glossary": "glossary",
    "Calculators": "calculator",
}
PUBLIC_STATUS = "Опубликовано"


def quote(s):
    return '"' + s.replace('"', '""') + '"'


def decode_copy(s):
    if s == r"\N":
        return None
    escapes = {
        b"b": b"\b",
        b"f": b"\f",
        b"n": b"\n",
        b"r": b"\r",
        b"t": b"\t",
        b"v": b"\v",
        b"\\": b"\\",
    }

    def sub(m):
        x = m.group(1)
        if re.fullmatch(rb"[0-7]{1,3}", x):
            return bytes([int(x, 8)])
        if re.fullmatch(rb"x[0-9a-fA-F]{1,2}", x):
            return bytes([int(x[1:], 16)])
        return escapes.get(x, x)

    return re.sub(rb"\\([0-7]{1,3}|x[0-9a-fA-F]{1,2}|.)", sub, s.encode("utf-8")).decode("utf-8")


def import_copy(lines, conn):
    counts = {}
    for line in lines:
        m = re.match(r'^COPY public\."([^"\n]+)" \((.*)\) FROM stdin;\s*$', line)
        if not m:
            continue
        name = m.group(1)
        cols = re.findall(r'"((?:[^" ]|"")+)"', m.group(2))
        if not cols:
            raise ValueError("Unsupported COPY column declaration")
        conn.execute(f"CREATE TABLE {quote(name)} ({', '.join(quote(c) + ' TEXT' for c in cols)})")
        # Identifiers are quoted; values are bound via executemany, never interpolated.
        insert = f"INSERT INTO {quote(name)} VALUES ({','.join('?' for _ in cols)})"  # noqa: S608
        batch = []
        n = 0
        terminated = False
        for line in lines:
            if line.rstrip("\r\n") == r"\.":
                terminated = True
                break
            row = line.rstrip("\n").rstrip("\r").split("\t")
            if len(row) != len(cols):
                raise ValueError(f"COPY width mismatch: {name}, row {n + 1}")
            batch.append(tuple(decode_copy(v) for v in row))
            n += 1
            if len(batch) >= 1000:
                conn.executemany(insert, batch)
                batch = []
        if not terminated:
            raise ValueError(f"Unterminated COPY: {name}")
        if batch:
            conn.executemany(insert, batch)
        counts[name] = n
    if not counts:
        raise ValueError("No COPY tables found")
    return counts


def import_backup(backup, pg_restore, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as temp:
        temp = Path(temp)
        db = temp / "source.sqlite"
        err = temp / "restore.log"
        with closing(sqlite3.connect(db)) as conn, err.open("w+") as log:
            # Executable is trusted local CLI configuration, never HTTP/user-query input.
            process = subprocess.Popen(  # noqa: S603
                [
                    pg_restore,
                    "--file=-",
                    "--data-only",
                    "--no-owner",
                    "--no-privileges",
                    str(Path(backup).resolve()),
                ],
                shell=False,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                encoding="utf-8",
            )
            try:
                counts = import_copy(iter(process.stdout), conn)
                status = process.wait()
                if status:
                    raise RuntimeError(
                        f"pg_restore failed with status {status}; check tool compatibility"
                    )
                conn.commit()
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("SQLite integrity failure")
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait()
                raise
            finally:
                process.stdout.close()
        os.replace(db, dest)
    return counts


def rows(conn, table):
    # quote() escapes the identifier; tables come from the importer schema.
    return [dict(r) for r in conn.execute(f"SELECT * FROM {quote(table)}")]  # noqa: S608


def clean(text):
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def safe_url(value):
    """Do not guess a URL path from slugs of unknown semantics."""
    if not value:
        return None
    p = urlparse(value)
    if (
        p.scheme == "https"
        and p.hostname == "kurs.alfabank.ru"
        and not p.username
        and not p.password
    ):
        return value
    return None


def normalize(conn):
    statuses = {r["Id"]: r["Title"] for r in rows(conn, "Statuses")}
    access_types = {r["Id"]: r["Title"] for r in rows(conn, "CourseTypes")}
    settings = {r["EntityId"]: r for r in rows(conn, "ContentSettings")}
    mappings = {}
    for dimension, table, field in [
        ("topics", "Topics", "TopicId"),
        ("tags", "Tags", "TagId"),
        ("industries", "Industries", "IndustryId"),
    ]:
        lookup = {
            r["Id"]: clean(r["Title"])
            for r in rows(conn, table)
            if r.get("IsDeleted") != "t" and r.get("IsPublic") != "f"
        }
        mapping = defaultdict(list)
        for r in rows(conn, "ContentSettings" + table):
            if r.get("IsDeleted") != "t" and r[field] in lookup:
                mapping[r["ContentSettingsId"]].append(lookup[r[field]])
        mappings[dimension] = mapping
    catalog = []
    exclusions = Counter()
    # Calculator publication lives in CalculatorPages, linked by the shared ID.
    # Ambiguous or deleted page records fail closed.
    calculator_pages = defaultdict(list)
    if "Calculators" in KINDS:
        for page in rows(conn, "CalculatorPages"):
            calculator_pages[page["Id"]].append(page)
    for table, kind in KINDS.items():
        for r in rows(conn, table):
            if kind == "calculator":
                pages = calculator_pages.get(r["Id"], [])
                page = pages[0] if len(pages) == 1 else {}
                status = statuses.get(page.get("StatusId"), "unknown")
                if page.get("IsDeleted") != "f":
                    status = "unknown"
            else:
                status = statuses.get(r.get("StatusId"), "unknown")
            if r.get("IsDeleted") == "t":
                exclusions[f"{kind}:deleted"] += 1
                continue
            if status != PUBLIC_STATUS:
                exclusions[f"{kind}:publication_unknown_or_not_published"] += 1
                continue
            if r.get("IsClosed") == "t":
                exclusions[f"{kind}:closed"] += 1
                continue
            # Use only summaries/metadata. No ArticleEmbedItems or paid lesson content.
            s = settings.get(r["Id"], {})
            title = clean(r.get("Title"))
            description = clean(r.get("Description"))
            if not title:
                exclusions[f"{kind}:empty_title"] += 1
                continue
            # Article payment type is Articles.TypeId, not ContentSettings.TypeId.
            type_id = r.get("TypeId") if kind == "article" else r.get("TypeId") or s.get("TypeId")
            raw_access = access_types.get(type_id)
            access = {
                "Открытый": "open",
                "Платный": "paid",
                "По подписке": "subscription",
                "Закрытый": "closed",
            }.get(raw_access, "unknown")
            if access == "closed":
                exclusions[f"{kind}:closed_type"] += 1
                continue
            item = {
                "entity_key": kind + ":" + r["Id"],
                "kind": kind,
                "source_table": table,
                "source_id": r["Id"],
                "title": title,
                "description": description,
                "publication_status": status,
                "access_type": access,
                "price_raw": r.get("Cost"),
                "price_currency": None,
                "course_cost_available": kind == "course" and "Cost" in r,
                "article_type_available": kind == "article" and type_id in access_types,
                "target_audience": clean(r.get("Target")) if kind == "course" else "",
                "duration_raw": r.get("Duration"),
                "source_url": r.get("Url"),
                "canonical_url": safe_url(r.get("Url")),
                "content_public_flag": r.get("IsPublic"),
                "data_quality_flags": [],
                "provenance": {
                    "title": table + ".Title",
                    "description": table + ".Description",
                },
            }
            for dimension, mapping in mappings.items():
                item[dimension] = sorted(set(mapping.get(s.get("Id"), [])))
            if not item["canonical_url"]:
                item["data_quality_flags"].append("url_unverified")
            if access == "unknown":
                item["data_quality_flags"].append("access_unknown")
            item["search_text"] = " ".join(
                [
                    title,
                    title,
                    description,
                    *item["topics"],
                    *item["tags"],
                    *item["industries"],
                ]
            )
            catalog.append(item)
    catalog.sort(key=lambda r: r["entity_key"])
    return catalog, dict(exclusions)


def build(args):
    from .storage import output_lock

    with output_lock(args.output):
        return build_locked(args)


def build_locked(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    backup = Path(args.backup)
    # Entire generation built privately; READY manifest is written last.
    backup_hash = sha256(backup)
    with tempfile.TemporaryDirectory(dir=out) as temp:
        stage = Path(temp)
        counts = import_backup(backup, args.pg_restore, stage / "source.sqlite")
        with closing(sqlite3.connect(stage / "source.sqlite")) as conn:
            conn.row_factory = sqlite3.Row
            catalog, exclusions = normalize(conn)
            lesson_report = attach_lessons(
                catalog,
                rows(conn, "Lessons"),
                rows(conn, "CourseLessonBindings"),
                clean,
                parse_as_of(args.as_of),
            )
            from .content import enrich_content

            content_report = enrich_content(
                catalog,
                rows(conn, "ArticleEmbedItems"),
                rows(conn, "LessonEmbedItems"),
                rows(conn, "DocumentEmbedItems"),
            )
        atomic_json(stage / "catalog.json", catalog)
        from .suggestions import build_index

        atomic_json(
            stage / "suggestions.json",
            build_index(catalog, sha256(stage / "catalog.json")),
        )
        manifest = {
            "schema_version": 3,
            "content_report": content_report,
            "lesson_policy": {"as_of": args.as_of, "counts": lesson_report},
            "backup_sha256": backup_hash,
            "tables": counts,
            "row_total": sum(counts.values()),
            "catalog_count": len(catalog),
            "catalog_counts": dict(Counter(x["kind"] for x in catalog)),
            "exclusions": exclusions,
            "catalog_sha256": sha256(stage / "catalog.json"),
            "source_sqlite_sha256": sha256(stage / "source.sqlite"),
            "suggestions": {"sha256": sha256(stage / "suggestions.json")},
            "contains_private_data": True,
            "ranking": "bm25; optional dense RRF",
            "semantic": None,
        }
        generation = (
            "generation-"
            + backup_hash[:12]
            + "-"
            + manifest["catalog_sha256"][:12]
            + "-"
            + manifest["suggestions"]["sha256"][:12]
        )
        target = out / generation
        if target.exists():
            for name in ["catalog.json", "source.sqlite", "suggestions.json"]:
                if sha256(target / name) != sha256(stage / name):
                    raise ValueError("Existing generation differs; use another output directory")
        else:
            os.replace(stage, target)
        if (target / "manifest.json").exists():
            previous = json.loads((target / "manifest.json").read_text())
            if previous.get("catalog_sha256") == manifest["catalog_sha256"]:
                manifest["semantic"] = previous.get("semantic")
        atomic_json(target / "manifest.json", manifest)
        atomic_json(out / "CURRENT.json", {"generation": generation})
    print(
        json.dumps(
            {
                "tables": len(counts),
                "rows": sum(counts.values()),
                "catalog": len(catalog),
                "lesson_report": lesson_report,
                "catalog_counts": manifest["catalog_counts"],
                "exclusions": exclusions,
                "output": str(target),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def embed(args):
    from .storage import output_lock

    with output_lock(args.output):
        return embed_locked(args)


def embed_locked(args):
    import numpy as np

    path, manifest, catalog = load_bundle(args.output)
    encoder = model(args.model_path)
    from .content import make_units

    window = min(96, encoder.max_seq_length - 2)
    units = make_units(catalog, encoder.tokenizer, window=window, overlap=16)
    atomic_json(path / "units.json", units)
    vectors = encoder.encode(
        [unit["text"] for unit in units],
        normalize_embeddings=True,
        batch_size=64,
        show_progress_bar=True,
    )
    temp = path / "vectors.tmp.npy"
    np.save(temp, vectors)
    os.replace(temp, path / "vectors.npy")
    manifest["semantic"] = {
        "model_id": MODEL_ID if not args.model_path else "local",
        "revision": MODEL_REVISION if not args.model_path else None,
        "local_path": str(Path(args.model_path).resolve()) if args.model_path else None,
        "local_model_fingerprint": model_fingerprint(args.model_path) if args.model_path else None,
        "unit_count": len(units),
        "units_sha256": sha256(path / "units.json"),
        "window_tokens": window,
        "overlap_tokens": 16,
        "dimensions": int(vectors.shape[1]),
        "vectors_sha256": sha256(path / "vectors.npy"),
        "catalog_sha256": manifest["catalog_sha256"],
    }
    atomic_json(path / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "embedded_cards": len(catalog),
                "embedded_units": len(units),
                "dimensions": int(vectors.shape[1]),
            }
        )
    )


def bm25(query, catalog):
    """Compatibility wrapper using the same BM25 implementation as retrieval."""
    from .retrieval import BM25Index

    return BM25Index([item["search_text"] for item in catalog]).score(query)


def search(args):
    from .search import SearchEngine

    if args.free_only:
        raise ValueError("Verified free-only filtering is not implemented")
    engine = SearchEngine(
        args.output,
        semantic=args.mode in {"hybrid", "catboost", "ensemble"},
        llm_enabled=args.mode == "ensemble" and not args.no_llm,
    )
    payload = engine.search(
        args.query,
        args.mode,
        args.top,
        args.kind,
        args.selection_id,
        args.selection_generation,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def suggest(args):
    from .search import SearchEngine

    payload = SearchEngine(args.output).suggest(args.query, args.limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--backup", required=True)
    b.add_argument("--pg-restore", default="pg_restore")
    b.add_argument("--output", default="artifacts/catalog")
    b.add_argument(
        "--as-of",
        help="ISO timestamp with timezone; without it all scheduled lessons are withheld",
    )
    b.set_defaults(func=build)
    e = sub.add_parser("embed")
    e.add_argument("--output", default="artifacts/catalog")
    e.add_argument("--model-path")
    e.set_defaults(func=embed)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--output", default="artifacts/catalog")
    s.add_argument(
        "--mode",
        choices=["hybrid", "catboost", "ensemble", "relevance"],
        default="relevance",
    )
    s.add_argument("--top", type=int, default=5)
    s.add_argument("--kind", choices=sorted(KINDS.values()))
    s.add_argument("--free-only", action="store_true")
    s.add_argument("--no-llm", action="store_true")
    s.add_argument("--selection-id")
    s.add_argument("--selection-generation")
    s.set_defaults(func=search)
    a = sub.add_parser("suggest")
    a.add_argument("query")
    a.add_argument("--limit", type=int, default=6)
    a.add_argument("--output", default="artifacts/catalog")
    a.set_defaults(func=suggest)
    from .server import serve

    v = sub.add_parser("serve")
    v.add_argument("--output", default="artifacts/catalog")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument(
        "--host",
        choices=["127.0.0.1", "0.0.0.0"],  # noqa: S104 - explicit isolated-container option
        default="127.0.0.1",
        help="Bind address; 0.0.0.0 is intended for an isolated container",
    )
    v.add_argument("--hybrid", action="store_true")
    v.add_argument(
        "--relevance",
        action="store_true",
        help="Use the locally trained experimental relevance model",
    )
    v.add_argument("--open-browser", action="store_true")
    v.add_argument("--start-page", choices=["/", "/lab"], default="/")
    v.add_argument("--no-llm", action="store_true")
    v.set_defaults(func=serve)
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        parser.exit(2, f"Error: {e}\n")
