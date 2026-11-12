"""Report what is confirmed by the local snapshot; does not make network claims."""

import json
from collections import Counter
from pathlib import Path

from alfa_reco.cli import atomic_json, load_bundle


def main():
    path, manifest, catalog = load_bundle("artifacts/catalog")
    report = {
        "generation": path.name,
        "catalog_sha256": manifest["catalog_sha256"],
        "materials": len(catalog),
        "publication_status_snapshot": dict(
            Counter(x.get("publication_status") or "unknown" for x in catalog)
        ),
        "access_metadata": dict(Counter(x.get("access_type") or "unknown" for x in catalog)),
        "absolute_urls": sum(bool(x.get("canonical_url")) for x in catalog),
        "source_slugs_or_urls": sum(bool(x.get("source_url")) for x in catalog),
        "price_values": sum(x.get("price_raw") is not None for x in catalog),
        "caveat": "Snapshot metadata only: no current publication, price, URL, entitlement or live site status has been verified.",
    }
    atomic_json(Path("evaluation/catalog_audit.json"), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
