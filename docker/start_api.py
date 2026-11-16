"""Prepare the immutable model cache and start the real in-process recommender."""

import os
import sys
from pathlib import Path

from scripts import run_project as launcher

launcher.PYTHON = Path(sys.executable)
launcher.RUNTIME = Path("/data/runtime")
launcher.UNIFIED = Path("/data/unified")

environment = launcher.api_environment(dict(os.environ), "preparing")
launcher.prepare_model(environment)
generation, catalogue = launcher.prepare_unified(environment)
environment = launcher.api_environment(dict(os.environ), generation, catalogue)
os.execvpe(
    sys.executable,
    [
        sys.executable,
        "-m",
        "uvicorn",
        "app:create_app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--workers",
        "1",
        "--no-access-log",
        "--no-proxy-headers",
    ],
    environment,
)
