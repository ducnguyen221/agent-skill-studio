"""Offline deterministic CSV QA tests, not LLM/Skill activation tests."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "data-quality-audit" / "scripts" / "validate_csv.py"
SPEC = importlib.util.spec_from_file_location("csvqa", SCRIPT)
csvqa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(csvqa)


class CSVQATests(unittest.TestCase):
    def test_clean_fixture(self):
        path = ROOT / "evals" / "data-quality-audit" / "fixtures" / "clean.csv"
        result = csvqa.check_file(path, ["id", "amount"], ["id"], ["amount"])
        self.assertEqual("pass", result["status"])
        self.assertEqual(3, result["rows_checked"])

    def test_duplicate_blank_fixture(self):
        path = ROOT / "evals" / "data-quality-audit" / "fixtures" / "duplicates.csv"
        result = csvqa.check_file(path, ["id", "amount"], ["id"], ["amount"])
        kinds = {x["type"] for x in result["issues"]}
        self.assertIn("duplicate-key", kinds)
        self.assertIn("blank-required", kinds)

    def test_invalid_numeric_fixture(self):
        path = ROOT / "evals" / "data-quality-audit" / "fixtures" / "invalid_numeric.csv"
        result = csvqa.check_file(path, ["id", "amount"], ["id"], ["amount"])
        self.assertTrue(any(x["type"] == "invalid-numeric" and x["row"] == 3 for x in result["issues"]))

    def test_missing_file_is_actionable_error(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError, "CSV input not found"):
                csvqa.check_file(Path(t) / "missing.csv", [], [], [])


if __name__ == "__main__":
    unittest.main()
