import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alfa_reco.bundle import sha256
from scripts.prepare_backend_bundle import manifest_write, relocate, verify


class HandoffBundleTests(unittest.TestCase):
    def test_relocation_preserves_integrity_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog" / "g1"
            model = catalog / "relevance" / "m1"
            model.mkdir(parents=True)
            (root / "encoder").mkdir()
            (root / "encoder" / "file").write_text("encoder")
            (root / "catalog" / "CURRENT.json").write_text('{"generation":"g1"}')
            (catalog / "relevance" / "CURRENT.json").write_text('{"generation":"m1"}')
            (catalog / "catalog.json").write_text("[]")
            (catalog / "suggestions.json").write_text("{}")
            catalog_hash = sha256(catalog / "catalog.json")
            (catalog / "manifest.json").write_text(
                json.dumps(
                    {
                        "catalog_sha256": catalog_hash,
                        "suggestions": {"sha256": sha256(catalog / "suggestions.json")},
                    }
                )
            )
            for name in ("vectors.npz", "normalized_catalog.json", "ranker.cbm"):
                (model / name).write_text(name)
            (model / "manifest.json").write_text(
                json.dumps(
                    {
                        "catalog_sha256": catalog_hash,
                        "encoder_path": "/old/path",
                        "encoder_fingerprint": "expected",
                        "index_sha256": sha256(model / "vectors.npz"),
                        "normalized_catalog_sha256": sha256(model / "normalized_catalog.json"),
                        "ranker_sha256": sha256(model / "ranker.cbm"),
                    }
                )
            )
            manifest_write(root, {"generation": "g1"})
            with patch("scripts.prepare_backend_bundle.model_fingerprint", return_value="expected"):
                verify(root)
                relocate(root)
                self.assertEqual(
                    json.loads((model / "manifest.json").read_text())["encoder_path"],
                    str((root / "encoder").resolve()),
                )
                (model / "vectors.npz").write_text("tampered")
                with self.assertRaisesRegex(ValueError, "differ"):
                    verify(root)


if __name__ == "__main__":
    unittest.main()
