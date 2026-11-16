"""Fetch a checked Git LFS object when the checkout only contains its pointer."""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

MODEL_URL = (
    "https://media.githubusercontent.com/media/KaNaP1A/alfa_hakaton/"
    "2204ea2e028b5da69f98d1a8fa00acf66b020dca/"
    "models/recommender/encoder/model.safetensors"
)


def ensure_model(bundle: Path, opener=urlopen) -> None:
    model = bundle / "encoder" / "model.safetensors"
    expected = json.loads((bundle / "handoff_manifest.json").read_text())[
        "files_sha256"
    ]["encoder/model.safetensors"]
    if not model.exists() or model.stat().st_size < 1024:
        print("Downloading the published model weights (Git LFS)...", flush=True)
        with opener(MODEL_URL, timeout=120) as response, model.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
    digest = hashlib.sha256()
    with model.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError("Model weights do not match the checked bundle manifest")


if __name__ == "__main__":
    ensure_model(Path("/app/models/recommender"))
