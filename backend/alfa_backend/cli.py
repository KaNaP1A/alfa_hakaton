import argparse
import json
from pathlib import Path

from sqlalchemy import inspect, select

from .adapters.catalog import import_catalog
from .adapters.database import Grant, User, connect, initialize
from .config import Settings
from .schemas import CatalogImport

DEMO = {
    "generation": "demo-v1",
    "materials": [
        {
            "entity_key": "course:demo-coffee",
            "kind": "course",
            "title": "Открываем кофейню",
            "description": "Бизнес: идея кофейни, бюджет и первые клиенты.",
            "topics": ["Бизнес", "Финансы"],
            "published": True,
            "access": "public",
        },
        {
            "entity_key": "article:demo-budget",
            "kind": "article",
            "title": "Бюджет кофейни",
            "description": "Финансы: считаем расходы бизнеса.",
            "topics": ["Бизнес", "Финансы"],
            "published": True,
            "access": "public",
        },
        {
            "entity_key": "course:demo-team",
            "kind": "course",
            "title": "Команда кофейни",
            "description": "Команда: найм и управление сотрудниками.",
            "topics": ["Бизнес", "Команда"],
            "published": True,
            "access": "public",
        },
        {
            "entity_key": "course:demo-private",
            "kind": "course",
            "title": "Закрытый курс",
            "description": "Не должен отображаться без отдельного доступа.",
            "topics": ["Бизнес"],
            "published": True,
            "access": "restricted",
        },
    ],
}


def main():
    parser = argparse.ArgumentParser(description="Alfa API database management")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    commands.add_parser("seed-demo")
    load = commands.add_parser("import-catalog")
    load.add_argument("path", type=Path)
    grant = commands.add_parser("grant")
    grant.add_argument("username")
    grant.add_argument("entity_key")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("username")
    revoke.add_argument("entity_key")
    commands.add_parser(
        "inspect-source", help="Read-only table/column inventory; no rows or values"
    )
    args = parser.parse_args()
    settings = Settings.from_env()
    engine, sessions = connect(settings.database_url)
    try:
        if args.command == "inspect-source":
            inspector = inspect(engine)
            print(
                json.dumps(
                    {
                        table: [
                            {"name": col["name"], "type": str(col["type"])}
                            for col in inspector.get_columns(table)
                        ]
                        for table in inspector.get_table_names()
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        initialize(engine)
        with sessions() as db:
            if args.command in {"seed-demo", "import-catalog"}:
                if args.command == "seed-demo" and settings.reco_mode != "demo":
                    parser.error("seed-demo is only allowed in ALFA_RECO_MODE=demo")
                data = CatalogImport.model_validate(
                    DEMO if args.command == "seed-demo" else json.loads(args.path.read_text())
                )
                import_catalog(db, data)
                print(f"Imported {len(data.materials)} materials, generation={data.generation}")
            elif args.command in {"grant", "revoke"}:
                user = db.scalar(select(User).where(User.username == args.username.casefold()))
                if user is None:
                    parser.error("User not found; register using the API first")
                # Restrict CLI grants to existing material IDs to catch operator typos.
                from .adapters.database import Material

                if db.get(Material, args.entity_key) is None:
                    parser.error("Material not found")
                existing = db.scalar(
                    select(Grant).where(
                        Grant.user_id == user.id, Grant.entity_key == args.entity_key
                    )
                )
                if args.command == "grant" and existing is None:
                    db.add(Grant(user_id=user.id, entity_key=args.entity_key))
                elif args.command == "revoke" and existing is not None:
                    db.delete(existing)
                db.commit()
                print(f"Access updated for user {user.id}")
            else:
                print("Database initialized")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
