import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CodeQualityContracts(unittest.TestCase):
    def test_pipeline_subprocess_calls_have_timeouts(self):
        paths = [
            PROJECT_ROOT / "scripts" / "s01_input.py",
            PROJECT_ROOT / "scripts" / "s02_demix.py",
            PROJECT_ROOT / "scripts" / "s04_align.py",
            PROJECT_ROOT / "scripts" / "s07_output.py",
            PROJECT_ROOT / "scripts" / "test_pipeline.py",
            PROJECT_ROOT / "scripts" / "pipeline_runner.py",
        ]
        missing = []

        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "run"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "subprocess"
                ):
                    if not any(keyword.arg == "timeout" for keyword in node.keywords):
                        missing.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

        self.assertEqual(missing, [])

    def test_server_no_longer_defines_legacy_run_stage(self):
        server_path = PROJECT_ROOT / "server.py"
        tree = ast.parse(server_path.read_text(encoding="utf-8"), filename=str(server_path))
        functions = [
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        self.assertNotIn("_run_stage", functions)

    def test_json_write_text_calls_pin_utf8_encoding(self):
        paths = [PROJECT_ROOT / "server.py", *sorted((PROJECT_ROOT / "scripts").glob("*.py"))]
        missing = []

        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not (isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"):
                    continue
                if not node.args:
                    continue
                payload = node.args[0]
                if not (
                    isinstance(payload, ast.Call)
                    and isinstance(payload.func, ast.Attribute)
                    and isinstance(payload.func.value, ast.Name)
                    and payload.func.value.id == "json"
                    and payload.func.attr == "dumps"
                ):
                    continue
                if not any(keyword.arg == "encoding" for keyword in node.keywords):
                    missing.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
