"""One local CPU training job, with optional loopback-only query augmentation."""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path


def run(arguments, environment):
    print("Running", " ".join(arguments), flush=True)
    subprocess.run([sys.executable, *arguments], env=environment, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--generate", action="store_true", help="Use local Ollama if running")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install the experimental profile, preserving the old default",
    )
    args = parser.parse_args()
    output = args.output or Path("artifacts/relevance_runs") / ("run-" + uuid.uuid4().hex[:12])
    output.mkdir(parents=True, exist_ok=False)
    environment = {
        **os.environ,
        "PYTHONPATH": "src",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
    }
    # Downloads public weights only if missing. Training itself stays offline.
    run(["scripts/download_relevance_encoder.py"], environment)
    environment["HF_HUB_OFFLINE"] = "1"
    generated = None
    if args.generate:
        try:
            transport = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with transport.open("http://127.0.0.1:11434/api/tags", timeout=2) as response:
                payload = json.loads(response.read(65536))
                if not any(row.get("name") == "gemma3:1b" for row in payload.get("models", [])):
                    raise OSError("Local generator model is not installed")
        except OSError:
            print(
                "Local Ollama unavailable; continuing with source-derived weak queries", flush=True
            )
        else:
            run(
                [
                    "scripts/generate_local_relevance_queries.py",
                    "--output",
                    str(output / "queries"),
                    "--limit",
                    "120",
                ],
                environment,
            )
            generated = output / "queries" / "queries.jsonl"
    arguments = [
        "scripts/train_relevance.py",
        "--output",
        str(output / "training"),
        "--index",
        str(output / "index"),
        "--synthetic-limit",
        "800",
    ]
    if generated:
        arguments += ["--local-queries", str(generated)]
    if args.install:
        arguments.append("--install")
    run(arguments, environment)
    print("Finished. Report:", output / "training" / "report.json", flush=True)


if __name__ == "__main__":
    main()
