import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_project as launcher


class LauncherTests(unittest.TestCase):
    def settings(self):
        return {
            "ALFA_DATABASE_URL": "postgresql+psycopg://alfa:fixture@127.0.0.1:55432/alfa_snapshot",
            "POSTGRES_PASSWORD": "fixture",
        }

    def test_missing_migration_never_installs_dependencies_or_runs_ddl(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(launcher, "STATE", Path(temporary)),
            patch.object(launcher, "load_env", return_value=self.settings()),
            patch.object(launcher.shutil, "which", return_value="/mock/tool"),
            patch.object(Path, "is_file", return_value=True),
            patch.object(launcher, "run"),
            patch.object(launcher, "compose", side_effect=["", "f"]) as compose,
            patch.object(launcher, "check_port"),
            patch.object(launcher, "prepare_python") as dependencies,
            patch.object(launcher, "serve") as serve,
            patch("sys.argv", ["run_project.py"]),
        ):
            with self.assertRaisesRegex(RuntimeError, "--migrate"):
                launcher.main()
            self.assertFalse(
                any("migrate" in call.args for call in compose.call_args_list)
            )
            dependencies.assert_not_called()
            serve.assert_not_called()

    def test_remote_database_is_rejected_before_compose_or_migration(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(launcher, "STATE", Path(temporary)),
            patch.object(
                launcher,
                "load_env",
                return_value={
                    "ALFA_DATABASE_URL": "postgresql+psycopg://alfa@remote.example/alfa_snapshot",
                },
            ),
            patch.object(launcher, "run"),
            patch.object(launcher.shutil, "which", return_value="/mock/tool"),
            patch.object(Path, "is_file", return_value=True),
            patch.object(launcher, "compose") as compose,
            patch("sys.argv", ["run_project.py", "--migrate"]),
        ):
            with self.assertRaisesRegex(RuntimeError, "локальную"):
                launcher.main()
            compose.assert_not_called()

    def test_model_settings_override_lexical_env_without_enabling_auto_ddl(self):
        env = launcher.api_environment(
            {"ALFA_RECO_MODE": "demo", "ALFA_AUTO_CREATE_TABLES": "true"}, "index-v1"
        )
        self.assertEqual(env["ALFA_RECO_MODE"], "python")
        self.assertEqual(env["ALFA_AUTO_CREATE_TABLES"], "false")
        self.assertEqual(env["ALFA_CATALOG_SOURCE"], "postgres")
        self.assertEqual(env["ALFA_CATALOG_GENERATION"], "index-v1")

    def test_api_and_model_use_the_same_unified_catalog(self):
        catalog = Path("/tmp/unified-catalog")
        env = launcher.api_environment(
            {"ALFA_UNIFIED_CATALOG": "/stale"}, "index-v2", catalog
        )
        self.assertEqual(env["ALFA_RECO_CATALOG"], str(catalog))
        self.assertEqual(env["ALFA_UNIFIED_CATALOG"], str(catalog))
        self.assertEqual(env["ALFA_CATALOG_GENERATION"], "index-v2")

    def test_changed_model_is_rolled_back_if_relocation_fails(self):
        def make_bundle(root, ranker, encoder_path):
            model = root / "catalog" / "generation-one" / "relevance" / "model-one"
            model.mkdir(parents=True)
            (root / "catalog" / "CURRENT.json").write_text(
                '{"generation":"generation-one"}'
            )
            (model.parent / "CURRENT.json").write_text('{"generation":"model-one"}')
            (model.parent.parent / "manifest.json").write_text(
                '{"catalog_sha256":"same"}'
            )
            (model / "manifest.json").write_text(
                json.dumps({"ranker_sha256": ranker, "encoder_path": encoder_path})
            )
            (root / "encoder").mkdir()
            (root / "encoder" / "model.safetensors").write_bytes(b"x" * 1024)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, runtime = (
                root / "models" / "recommender",
                root / "models" / "runtime",
            )
            make_bundle(source, "new", "/source")
            make_bundle(runtime, "old", "/runtime")

            def execute(args, **kwargs):
                if "--relocate" in args:
                    raise RuntimeError("relocation failed")
                return ""

            with (
                patch.object(launcher, "ROOT", root),
                patch.object(launcher, "RUNTIME", runtime),
                patch.object(launcher, "run", side_effect=execute),
            ):
                with self.assertRaisesRegex(RuntimeError, "relocation failed"):
                    launcher.prepare_model({})
            self.assertEqual(
                launcher.bundle_identity(runtime)[2]["ranker_sha256"], "old"
            )

    def test_env_is_read_as_data_without_shell_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "env"
            path.write_text('KEY="$(echo not-executed)"\nEMPTY=\n# comment\n')
            self.assertEqual(
                launcher.load_env(path), {"KEY": "$(echo not-executed)", "EMPTY": ""}
            )
