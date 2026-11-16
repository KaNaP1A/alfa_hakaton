"""Create controlled wording probes without inventing new relevance judgments."""

import argparse
import json
from pathlib import Path

from prepare_persona_corpus import normalize

from alfa_reco.bundle import atomic_json, sha256

PREFIXES = {
    "original": "",
    "polite": "Подскажите, пожалуйста: ",
    "beginner": "Я новичок в бизнесе. ",
}


def build(rows):
    result = []
    seen = set()
    for row in rows:
        if not row.get("known_targets") or row.get("human_verified") is not False:
            raise ValueError("Need explicitly provisional known targets")
        for style, prefix in PREFIXES.items():
            query = prefix + row["query"]
            normalized = normalize(query)
            if normalized in seen:
                raise ValueError("Duplicate augmented query")
            seen.add(normalized)
            result.append(
                {
                    **row,
                    "id": row["id"] + ":" + style,
                    "base_id": row["id"],
                    "style": style,
                    "query": query,
                    "source": "controlled_style_from_assistant_query",
                }
            )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise ValueError("Output already exists")
    data = json.loads(a.source.read_text())
    rows = build(data["queries"])
    atomic_json(
        a.output,
        {
            "schema_version": 1,
            "catalog_sha256": data["catalog_sha256"],
            "source_queries_sha256": sha256(a.source),
            "queries": rows,
            "limitations": "Controlled prefixes on assistant-authored queries; not new independent topics, human judgments or real-user data. Known targets are partial.",
        },
    )
    print(f"Created {len(rows)} controlled queries from {len(data['queries'])} base queries")


if __name__ == "__main__":
    main()
