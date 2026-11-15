"""Regression: a symlinked venv Python must retain its environment and this checkout."""

import os
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest.mock import patch

from scripts import model_runtime


class ModelRuntimeTests(unittest.TestCase):
    def test_venv_and_checkout_are_used_for_every_subprocess(self):
        run = subprocess.run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            environment = root / "env"
            venv.EnvBuilder(symlinks=True).create(environment)
            python = environment / "bin" / "python"
            bundle = root / "bundle"
            bundle.mkdir()
            (bundle / "sentinel").write_text("original")
            runtime = root / "runtime"
            code = Path(model_runtime.__file__).resolve().parents[2] / "05_code"

            def probe(command, **kwargs):
                result = run(
                    [
                        command[0],
                        "-c",
                        "import sys, alfa_reco; print(sys.prefix); print(alfa_reco.__file__)",
                    ],
                    env=kwargs["env"],
                    check=True,
                    text=True,
                    capture_output=True,
                    cwd=root,
                )
                prefix, module = result.stdout.strip().splitlines()
                self.assertEqual(Path(prefix), environment)
                self.assertEqual(Path(module).parent, code / "src" / "alfa_reco")
                self.assertEqual(kwargs["env"]["HF_HUB_OFFLINE"], "1")
                return result

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "model_runtime",
                        "--bundle",
                        str(bundle),
                        "--runtime",
                        str(runtime),
                        "--python",
                        str(python),
                        "--port",
                        "18000",
                    ],
                ),
                patch.dict(os.environ, {"PYTHONPATH": "", "HF_HUB_OFFLINE": "0"}),
                patch.object(model_runtime.subprocess, "run", side_effect=probe) as child,
            ):
                model_runtime.main()
            self.assertEqual(child.call_count, 3)
            self.assertEqual((runtime / "sentinel").read_text(), "original")
            self.assertEqual((bundle / "sentinel").read_text(), "original")
