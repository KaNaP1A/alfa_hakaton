"""Inventory project Markdown and check local links; generated artifacts are excluded."""

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from alfa_reco.bundle import atomic_json, sha256


def inspect(root):
    documents, broken = [], []
    for path in sorted(root.rglob("*.md")):
        if any(
            part in {"artifacts", ".venv", ".git", "node_modules"}
            for part in path.relative_to(root).parts
        ):
            continue
        text = path.read_text(encoding="utf-8")
        documents.append(
            {
                "path": str(path.relative_to(root)),
                "lines": len(text.splitlines()),
                "sha256": sha256(path),
            }
        )
        # Code examples do not define document links.
        prose = re.sub(r"```.*?```", "", text, flags=re.S)
        for match in re.finditer(r"\[[^\]\n]*\]\(([^)\n]+)\)", prose):
            target = match.group(1).strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = Path(unquote(parsed.path))
            if not destination.is_absolute():
                destination = path.parent / destination
            if not destination.exists():
                broken.append({"document": str(path.relative_to(root)), "target": target})
    return {
        "documents": documents,
        "count": len(documents),
        "broken_local_links": broken,
        "scope": "Project Markdown only; generated artifact reviews, dependencies, remote URLs and anchors are not validated.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.root)
    atomic_json(args.output, report)
    print(f"{report['count']} documents; {len(report['broken_local_links'])} broken local links")
    for link in report["broken_local_links"]:
        print(link)
    if report["broken_local_links"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
