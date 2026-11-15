"""Verify a handoff bundle, relocate a private runtime copy and serve the model."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "models" / "recommender",
        help="Model bundle (default: models/recommender)",
    )
    parser.add_argument(
        "--runtime", type=Path, required=True, help="New private destination outside the bundle"
    )
    parser.add_argument(
        "--python",
        type=Path,
        required=True,
        help="Python with requirements-relevance.txt installed",
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    source = args.bundle.resolve()
    runtime = args.runtime.resolve()
    python = str(args.python.resolve())
    code = Path(__file__).resolve().parents[2] / "05_code"
    prepare = str(code / "scripts" / "prepare_backend_bundle.py")
    if runtime == source or runtime.is_relative_to(source):
        parser.error("runtime must be outside the source bundle")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    subprocess.run([python, prepare, "--verify", str(source)], check=True)
    # Refuse to reuse or overwrite another runtime; the source remains unchanged.
    shutil.copytree(source, runtime)
    subprocess.run([python, prepare, "--relocate", str(runtime)], check=True)
    subprocess.run(
        [
            python,
            "-m",
            "alfa_reco",
            "serve",
            "--output",
            str(runtime / "catalog"),
            "--relevance",
            "--no-llm",
            "--port",
            str(args.port),
        ],
        check=True,
        env={**os.environ, "HF_HUB_OFFLINE": "1"},
        cwd=code,
    )


if __name__ == "__main__":
    main()
