"""Snapshot price facts, separate from authorization and subscription tariffs."""


def price_fact(item):
    # Only an actually present Courses.Cost NULL has the expert-confirmed meaning.
    if (item.get("kind") == "course" and item.get("course_cost_available") is True
            and "price_raw" in item and item["price_raw"] is None):
        return {"status": "free", "source": "Courses.Cost=NULL", "snapshot_only": True,
                "access_verified": False}
    if item.get("kind") == "article" and item.get("article_type_available") is True:
        if item.get("access_type") == "open":
            return {"status": "free", "source": "Articles.TypeId=Public", "snapshot_only": True,
                    "access_verified": False}
        if item.get("access_type") in {"paid", "subscription"}:
            return {"status": "paid_or_subscription", "source": "Articles.TypeId",
                    "snapshot_only": True, "access_verified": False}
    return {"status": "unknown", "source": None, "snapshot_only": True,
            "access_verified": False}
