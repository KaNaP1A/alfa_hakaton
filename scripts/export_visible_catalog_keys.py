"""Export locally visible catalog IDs for a synthetic experiment, without DB writes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from repositories.production_catalog import ProductionCatalogRepository
from repositories.unified_catalog import UnifiedCatalog, UnifiedCatalogRepository
from scripts.run_project import ROOT, load_env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "models/unified/simulation-allowed-keys.json",
    )
    args = parser.parse_args()
    values = load_env(ROOT / "backend/.env.snapshot")
    database = values["ALFA_DATABASE_URL"]
    if not database.startswith("postgresql+psycopg:"):
        raise ValueError(
            "The experiment requires the local snapshot PostgreSQL database"
        )
    parsed = urlsplit(database.replace("postgresql+psycopg:", "postgresql:", 1))
    if (
        parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.path != "/alfa_snapshot"
        or parsed.username != "alfa"
        or parsed.port != int(values.get("POSTGRES_PORT", "55432"))
        or unquote(parsed.password or "") != values.get("POSTGRES_PASSWORD")
    ):
        raise ValueError("The configured database is not the local snapshot")
    root = ROOT / "models/unified"
    state = json.loads((root / "ACTIVE.json").read_text())
    name = state["catalog"]
    if not isinstance(name, str) or Path(name).name != name or name.startswith("."):
        raise ValueError("Invalid unified catalog directory")
    catalog = UnifiedCatalog(root / name)
    if state["generation"] != catalog.generation:
        raise ValueError("Active generation differs from the catalog")
    indexed = json.loads(
        (root / name / catalog.generation / "catalog.json").read_text()
    )
    indexed_keys = {item["entity_key"] for item in indexed}
    engine = create_engine(database)
    try:
        with Session(engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            base = ProductionCatalogRepository(session, catalog.generation)
            repository = UnifiedCatalogRepository(base, catalog)
            visible = repository.visible_materials("simulation", catalog.generation)
            keys = sorted(indexed_keys.intersection(visible))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(keys, ensure_ascii=False) + "\n")
        print(f"Exported {len(keys)} visible indexed IDs to {args.output}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
