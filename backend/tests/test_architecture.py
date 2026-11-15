import ast
import unittest
from pathlib import Path


class ArchitectureTests(unittest.TestCase):
    def test_services_do_not_depend_on_transport_or_storage(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = {"api", "fastapi", "sqlalchemy", "repositories", "infrastructure", "httpx"}
        for path in (root / "services").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                modules = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                elif isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                for module in modules:
                    self.assertNotIn(module.split(".")[0], forbidden, str(path))
