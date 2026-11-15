import ast
import unittest
from pathlib import Path


class ArchitectureTests(unittest.TestCase):
    def test_dependencies_point_inward(self):
        root = Path(__file__).resolve().parents[1]
        adapters = {"api", "fastapi", "sqlalchemy", "repositories", "infrastructure", "httpx"}
        boundaries = {
            "domain": adapters | {"services", "schemas", "config"},
            "services": adapters | {"schemas", "config"},
            "api": {"sqlalchemy", "repositories", "infrastructure"},
        }
        for layer, forbidden in boundaries.items():
            for path in (root / layer).glob("*.py"):
                for node in ast.walk(ast.parse(path.read_text())):
                    modules = []
                    if isinstance(node, ast.ImportFrom) and node.module:
                        modules = [node.module]
                    elif isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    for module in modules:
                        with self.subTest(path=path.name, dependency=module):
                            self.assertNotIn(module.split(".")[0], forbidden, str(path))
