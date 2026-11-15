import time

from sqlalchemy import delete, or_, select

from .database import Activity, CatalogState, Grant, Material


class CatalogUnavailable(Exception):
    pass


def generation(db):
    state = db.get(CatalogState, 1)
    if state is None:
        raise CatalogUnavailable("Import the trusted catalog before using recommendations")
    return state.generation


def import_catalog(db, data):
    # A full replacement is atomic. Missing materials become unavailable immediately.
    db.execute(delete(Material))
    for item in data.materials:
        db.add(Material(generation=data.generation, **item.model_dump()))
    state = db.get(CatalogState, 1)
    if state is None:
        db.add(CatalogState(id=1, generation=data.generation))
    else:
        state.generation = data.generation
    db.commit()


def visible_query(user_id, current):
    grants = select(Grant.entity_key).where(
        Grant.user_id == user_id,
        or_(Grant.expires_at.is_(None), Grant.expires_at > time.time()),
    )
    return select(Material).where(
        Material.generation == current,
        Material.published.is_(True),
        or_(Material.access == "public", Material.entity_key.in_(grants)),
    )


def visible_materials(db, user_id, current):
    return {item.entity_key: item for item in db.scalars(visible_query(user_id, current))}


def card(material):
    # Only trusted database fields are public. Never copy arbitrary upstream dictionaries.
    return {
        "entity_key": material.entity_key,
        "generation": material.generation,
        "kind": material.kind,
        "title": material.title,
        "description": material.description,
        "topics": material.topics,
        "canonical_url": material.canonical_url,
        "access_type": material.access,
        "access_verified": True,
        "price": {
            "status": "known" if material.price_amount is not None else "unknown",
            "amount": material.price_amount,
            "currency": material.price_currency,
        },
    }


def history(db, user_id, current, allowed):
    # Ignore history from old catalog versions; preserve it in storage for auditing.
    rows = db.scalars(
        select(Activity)
        .where(Activity.user_id == user_id, Activity.generation == current)
        .order_by(Activity.id.desc())
        .limit(1000)
    )
    viewed, completed, seen = [], [], set()
    for row in rows:
        if row.entity_key not in allowed or row.entity_key in seen:
            continue
        if row.action in {"viewed", "interested", "started", "completed"}:
            seen.add(row.entity_key)
            viewed.append(row.entity_key)
        if len(seen) == 50:
            break
    # Completion remains meaningful after a more recent view event.
    if seen:
        completed = list(
            db.scalars(
                select(Activity.entity_key)
                .where(
                    Activity.user_id == user_id,
                    Activity.generation == current,
                    Activity.entity_key.in_(seen),
                    Activity.action == "completed",
                )
                .distinct()
            )
        )
    return list(reversed(viewed)), completed
