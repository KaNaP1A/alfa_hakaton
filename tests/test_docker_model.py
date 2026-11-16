import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from docker.ensure_model import ensure_model


class ModelDownloadTests(unittest.TestCase):
    def bundle(self, root: Path, contents: bytes) -> Path:
        (root / "encoder").mkdir()
        (root / "handoff_manifest.json").write_text(
            json.dumps(
                {
                    "files_sha256": {
                        "encoder/model.safetensors": hashlib.sha256(
                            contents
                        ).hexdigest()
                    }
                }
            )
        )
        return root / "encoder" / "model.safetensors"

    def test_pointer_is_replaced_by_verified_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            weights = b"test-model" * 200
            model = self.bundle(bundle, weights)
            model.write_text("version https://git-lfs.github.com/spec/v1\n")
            ensure_model(bundle, opener=lambda _url, timeout: io.BytesIO(weights))
            self.assertEqual(model.read_bytes(), weights)

    def test_incorrect_weights_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            model = self.bundle(bundle, b"expected" * 200)
            model.write_bytes(b"incorrect" * 200)
            with self.assertRaisesRegex(ValueError, "do not match"):
                ensure_model(bundle)


if __name__ == "__main__":
    unittest.main()
