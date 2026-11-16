"""Expose versioned public metadata alongside the checked database catalog."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from domain.commands import CatalogImport
from domain.entities import Material
from domain.errors import AppError
from domain.ports import CatalogRepository


@dataclass(frozen=True)
class Listing:
    key: str
    kind: str
    origin: str
    identity: str
    title: str
    description: str
    topics: list[str]
    source_url: str | None
    price_rub: int | None
    cost_rub: int | None


def safe_source_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme == "https"
            and url.hostname == "kurs.alfabank.ru"
            and not url.username
            and not url.password
            and url.port in (None, 443)
        ):
            return value
    except ValueError:
        pass
    return None


class UnifiedCatalog:
    def __init__(self, root: Path) -> None:
        root = root.expanduser().absolute()
        generation = json.loads((root / "CURRENT.json").read_text())["generation"]
        if (
            not isinstance(generation, str)
            or not generation
            or Path(generation).name != generation
            or generation.startswith(".")
        ):
            raise ValueError("Invalid unified catalog generation")
        path = root / generation
        manifest = json.loads((path / "manifest.json").read_text())
        content = (path / "catalog.json").read_bytes()
        if hashlib.sha256(content).hexdigest() != manifest["catalog_sha256"]:
            raise ValueError("Unified catalog checksum mismatch")
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError("Unified catalog must be a list")
        self.generation = generation
        compatible = manifest.get("profile_compatible_generations", [])
        if not isinstance(compatible, list) or any(not isinstance(x, str) for x in compatible):
            raise ValueError("Invalid compatible generation list")
        self.compatible_generations = tuple(compatible)
        self.listings: dict[str, Listing] = {}
        for item in data:
            display = item.get("supplement_display")
            if display is None:
                continue
            key, kind = item.get("entity_key"), item.get("kind")
            if (
                not isinstance(key, str)
                or not isinstance(kind, str)
                or not key.startswith(kind + ":")
                or key in self.listings
                or not isinstance(display, dict)
                or display.get("origin")
                not in {"synthetic", "public_snapshot", "historical_backup"}
            ):
                raise ValueError("Invalid unified listing")
            title, description, topics = (
                display.get("title"),
                display.get("description"),
                display.get("topics"),
            )
            if (
                not isinstance(title, str)
                or not title.strip()
                or len(title) > 500
                or not isinstance(description, str)
                or len(description) > 50000
                or not isinstance(topics, list)
                or any(not isinstance(x, str) for x in topics)
            ):
                raise ValueError("Invalid unified listing metadata")
            identity = display.get("identity", "snapshot_only")
            if identity not in {
                "title_candidate_unverified",
                "synthetic",
                "source_id",
                "snapshot_only",
            }:
                raise ValueError("Invalid unified listing identity")
            offer = item.get("conditional_offer")
            price = cost = None
            if offer is not None:
                if (
                    not isinstance(offer, dict)
                    or offer.get("kind") != "fictional_simulation"
                    or type(offer.get("price_rub")) is not int
                    or type(offer.get("cost_rub")) is not int
                    or not 0 <= offer["cost_rub"] <= offer["price_rub"] <= 10000000
                    or offer["price_rub"] <= 0
                ):
                    raise ValueError("Invalid conditional offer")
                price, cost = offer["price_rub"], offer["cost_rub"]
            self.listings[key] = Listing(
                key,
                kind,
                display["origin"],
                identity,
                title.strip(),
                description,
                topics,
                safe_source_url(display.get("source_url")),
                price,
                cost,
            )


class UnifiedCatalogRepository:
    def __init__(self, base: CatalogRepository, catalog: UnifiedCatalog) -> None:
        self.base = base
        self.catalog = catalog

    def generation(self) -> str:
        current = self.base.generation()
        if current != self.catalog.generation:
            raise AppError(503, "Catalog generation differs from the search index")
        return current

    def import_catalog(self, data: CatalogImport) -> None:
        self.base.import_catalog(data)

    def visible_materials(self, user_id: str, current: str) -> dict[str, Material]:
        if current != self.catalog.generation:
            raise AppError(409, "Catalog generation changed")
        materials = self.base.visible_materials(user_id, current)
        for key, item in self.catalog.listings.items():
            if item.identity == "title_candidate_unverified":
                # A title match is not an ID match. Keep the independently authorized
                # backup material, but do not attach or expose another record under its ID.
                continue
            if key in materials:
                materials[key] = replace(
                    materials[key],
                    source_url=item.source_url,
                    topics=materials[key].topics or item.topics,
                    conditional_price_rub=item.price_rub,
                    conditional_cost_rub=item.cost_rub,
                )
            elif item.origin == "synthetic" or (
                item.origin == "public_snapshot" and item.source_url is not None
            ):
                # Only title/description are supplied. No underlying access, purchase or
                # publication entitlement is asserted for a snapshot or synthetic entry.
                materials[key] = Material(
                    entity_key=key,
                    generation=current,
                    kind=item.kind,
                    title=item.title,
                    description=item.description,
                    topics=item.topics,
                    published=False,
                    access="unknown",
                    canonical_url=None,
                    price_amount=None,
                    price_currency=None,
                    access_verified=False,
                    source_url=item.source_url,
                    conditional_price_rub=item.price_rub,
                    conditional_cost_rub=item.cost_rub,
                )
        return materials
