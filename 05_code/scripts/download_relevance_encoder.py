"""Download pinned public E5 weights; no user/catalog text or inference is sent remotely."""

import argparse
import json
from pathlib import Path

MODEL = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/models/multilingual-e5-small")
    )
    args = parser.parse_args()
    revision_file = args.output / "revision.json"
    if revision_file.exists() and json.loads(revision_file.read_text()).get("revision") == REVISION:
        required = [
            "model.safetensors",
            "config.json",
            "tokenizer.json",
            "modules.json",
            "1_Pooling/config.json",
        ]
        if all((args.output / name).is_file() for name in required):
            print("Pinned E5 weights already available locally", flush=True)
            return
    from huggingface_hub import snapshot_download

    args.output.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        MODEL,
        revision=REVISION,
        local_dir=args.output,
        allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors", "1_Pooling/*"],
        ignore_patterns=["onnx/*", "openvino/*"],
    )
    revision_file.write_text(json.dumps({"id": MODEL, "revision": REVISION}) + "\n")
    print("Downloaded pinned E5 weights", flush=True)


if __name__ == "__main__":
    main()
