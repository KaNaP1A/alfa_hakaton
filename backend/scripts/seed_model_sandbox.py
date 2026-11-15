"""Create a NEW SQLite test database from model metadata with artificial public access.

Only for local integration checks. Snapshot metadata cannot establish real user rights,
publication, current URLs or prices. Never import this fixture into a production database.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from infrastructure.database import connect, initialize
from infrastructure.uow import SqlAlchemyUnitOfWork
from schemas.requests import CatalogImport


def seed(catalog: Path, database: Path) -> CatalogImport:
    generation = json.loads((catalog / "CURRENT.json").read_text(encoding="utf-8"))["generation"]
    if (
        not isinstance(generation, str)
        or not generation
        or Path(generation).name != generation
        or generation.startswith(".")
    ):
        raise ValueError("Invalid catalog generation")
    source = json.loads((catalog / generation / "catalog.json").read_text(encoding="utf-8"))
    if isinstance(source, dict):
        source = source["materials"]
    data = CatalogImport.model_validate(
        {
            "generation": generation,
            "materials": [
                {
                    "entity_key": item["entity_key"],
                    "kind": item["kind"],
                    "title": item["title"],
                    "description": item.get("description", ""),
                    "topics": item.get("topics", []),
                    # Deliberate test policy, not inferred permissions from the snapshot.
                    "published": True,
                    "access": "public",
                }
                for item in source
                if item["kind"] != "glossary"
            ],
        }
    )
    database = database.absolute()
    if database.suffix != ".sqlite3":
        raise ValueError("Use a new .sqlite3 file dedicated to the model sandbox")
    database.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing a real database, including on repeated runs.
    with database.open("xb"):
        pass
    engine, sessions = connect("sqlite:///" + str(database))
    try:
        initialize(engine)
        with SqlAlchemyUnitOfWork(sessions) as uow:
            uow.repository.import_catalog(data)
            uow.commit()
    finally:
        engine.dispose()
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, required=True, help="Verified runtime catalog directory"
    )
    parser.add_argument("--database", type=Path, required=True, help="NEW sandbox .sqlite3 file")
    args = parser.parse_args()
    data = seed(args.catalog, args.database)
    print(f"TEST FIXTURE ONLY: {len(data.materials)} materials, generation={data.generation}")
    print(
        "Access/publication are artificial; URLs and prices remain unknown. Bind API to loopback."
    )


if __name__ == "__main__":
    main()
