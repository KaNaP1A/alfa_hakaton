"""Versioned artifact I/O and optional encoder loading, independent of CLI commands."""

import hashlib
import json
import os
from pathlib import Path

MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1048576), b""):
            h.update(b)
    return h.hexdigest()


def model_fingerprint(directory):
    """Fingerprint local encoder files that affect embeddings and tokenization."""
    directory = Path(directory)
    relative_paths = [
        "model.safetensors",
        "config.json",
        "modules.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "1_Pooling/config.json",
    ]
    digest = hashlib.sha256()
    for relative in relative_paths:
        path = directory / relative
        if not path.is_file():
            raise ValueError("Cannot fingerprint local embedding model: " + relative)
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(sha256(path).encode("ascii") + b"\0")
    return digest.hexdigest()


def atomic_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_bundle(output):
    root = Path(output)
    generation = json.loads((root / "CURRENT.json").read_text())["generation"]
    if "/" in generation or generation.startswith("."):
        raise ValueError("Invalid generation")
    path = root / generation
    manifest = json.loads((path / "manifest.json").read_text())
    if sha256(path / "catalog.json") != manifest["catalog_sha256"]:
        raise ValueError("Catalog hash mismatch")
    return path, manifest, json.loads((path / "catalog.json").read_text())


def model(local_path=None):
    from sentence_transformers import SentenceTransformer

    if local_path:
        return SentenceTransformer(str(local_path), device="cpu", local_files_only=True)
    return SentenceTransformer(MODEL_ID, revision=MODEL_REVISION, device="cpu")
