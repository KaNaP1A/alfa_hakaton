"""Create and relocate a minimal, private runtime bundle without source.sqlite."""

import argparse
import json
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from alfa_reco.bundle import load_bundle, model_fingerprint, sha256
from alfa_reco.search import SearchEngine

PACKAGES = (
    "numpy",
    "sentence-transformers",
    "transformers",
    "torch",
    "catboost",
    "pymorphy3",
    "pymorphy3-dicts-ru",
    "dawg2-python",
)


def pointer(path):
    name = json.loads(path.read_text(encoding="utf-8"))["generation"]
    if not isinstance(name, str) or not name or Path(name).name != name or name.startswith("."):
        raise ValueError(f"Invalid generation in {path}")
    return name


def checksums(root):
    return {
        str(p.relative_to(root)): sha256(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "handoff_manifest.json"
    }


def manifest_write(root, metadata):
    metadata["files_sha256"] = checksums(root)
    (root / "handoff_manifest.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def verify(root):
    root = Path(root).resolve()
    metadata = json.loads((root / "handoff_manifest.json").read_text(encoding="utf-8"))
    expected = metadata["files_sha256"]
    if expected != checksums(root):
        raise ValueError("Bundle files differ from handoff_manifest.json")
    if any(p.suffix.lower() in {".sqlite", ".backup", ".sql"} for p in root.rglob("*")):
        raise ValueError("Raw database or backup must not be included")
    path, catalog_manifest, _ = load_bundle(root / "catalog")
    model = path / "relevance" / pointer(path / "relevance" / "CURRENT.json")
    model_manifest = json.loads((model / "manifest.json").read_text(encoding="utf-8"))
    if model_manifest["catalog_sha256"] != catalog_manifest["catalog_sha256"]:
        raise ValueError("Ranker and catalog do not match")
    if model_fingerprint(root / "encoder") != model_manifest["encoder_fingerprint"]:
        raise ValueError("Encoder fingerprint mismatch")
    for name, key in (
        ("vectors.npz", "index_sha256"),
        ("normalized_catalog.json", "normalized_catalog_sha256"),
        ("ranker.cbm", "ranker_sha256"),
    ):
        if sha256(model / name) != model_manifest[key]:
            raise ValueError(f"Artifact mismatch: {name}")
    if sha256(path / "suggestions.json") != catalog_manifest["suggestions"]["sha256"]:
        raise ValueError("Suggestions mismatch")
    return metadata, model / "manifest.json"


def relocate(root):
    root = Path(root).resolve()
    metadata, path = verify(root)
    model = json.loads(path.read_text(encoding="utf-8"))
    model["encoder_path"] = str(root / "encoder")
    path.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_write(root, metadata)
    verify(root)


def create(catalog_root, output):
    engine = SearchEngine(catalog_root)
    backend = engine.relevance_backend()  # validates files, preprocessing and model compatibility
    source, manifest, _ = load_bundle(catalog_root)
    generation = source.name
    model_name = pointer(source / "relevance" / "CURRENT.json")
    model_dir = source / "relevance" / model_name
    encoder = Path(backend.manifest["encoder_path"])
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        dest = output / "catalog" / generation
        dest.mkdir(parents=True)
        shutil.copy2(Path(catalog_root) / "CURRENT.json", output / "catalog" / "CURRENT.json")
        for name in ("catalog.json", "manifest.json", "suggestions.json"):
            shutil.copy2(source / name, dest / name)
        dest_model = dest / "relevance" / model_name
        dest_model.mkdir(parents=True)
        shutil.copy2(source / "relevance" / "CURRENT.json", dest_model.parent / "CURRENT.json")
        for name in ("manifest.json", "ranker.cbm", "vectors.npz", "normalized_catalog.json"):
            shutil.copy2(model_dir / name, dest_model / name)
        shutil.copytree(
            encoder, output / "encoder", ignore=shutil.ignore_patterns(".cache", "__pycache__")
        )
        metadata = {
            "generation": generation,
            "model_generation": model_name,
            "python": sys.version.split()[0],
            "encoder_revision": backend.manifest.get("encoder_revision"),
            "catalog_sha256": manifest["catalog_sha256"],
            "note": "Private derived content; no source database. Checksums are integrity checks, not signatures.",
        }
        metadata["installed_versions"] = {}
        for package in PACKAGES:
            try:
                metadata["installed_versions"][package] = version(package)
            except PackageNotFoundError:
                metadata["installed_versions"][package] = None
        model_meta = json.loads((dest_model / "manifest.json").read_text(encoding="utf-8"))
        model_meta["encoder_path"] = str(output / "encoder")
        (dest_model / "manifest.json").write_text(
            json.dumps(model_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        manifest_write(output, metadata)
        verify(output)
    except BaseException:
        shutil.rmtree(output)
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--output", type=Path, help="Create a new minimal bundle; path must not exist"
    )
    group.add_argument("--verify", type=Path)
    group.add_argument("--relocate", type=Path)
    parser.add_argument("--catalog", default="artifacts/catalog")
    args = parser.parse_args()
    if args.output:
        print("Created", create(args.catalog, args.output))
    elif args.verify:
        metadata, _ = verify(args.verify)
        print("Verified", metadata["generation"])
    else:
        relocate(args.relocate)
        print("Relocated and verified", args.relocate.resolve())


if __name__ == "__main__":
    main()
