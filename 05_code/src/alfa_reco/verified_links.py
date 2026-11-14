"""Individual public routes checked against the platform, never inferred from slugs."""

# Each pair was matched to the corresponding public page. Unknown paths remain unset.
VERIFIED = {
    ("article", "pervyj-sotrudnik-podgotovka-k-najmu"): "https://kurs.alfabank.ru/articles/pervyj-sotrudnik-podgotovka-k-najmu/",
    ("course", "kak-upravlyat-komandoi"): "https://kurs.alfabank.ru/courses/kak-upravlyat-komandoi/",
    ("calculator", "ndfl"): "https://kurs.alfabank.ru/calculators/ndfl/",
}


def apply_verified_links(catalog):
    for item in catalog:
        verified = VERIFIED.get((item.get("kind"), item.get("source_url")))
        if verified and not item.get("canonical_url"):
            item["canonical_url"] = verified
            item["data_quality_flags"] = [
                flag for flag in item.get("data_quality_flags", []) if flag != "url_unverified"
            ]
            item.setdefault("provenance", {})["canonical_url"] = "manual_public_page_2026-11-12"
