"""SPR-04 TK6 (FR5.1, FR5.2, SC1): `doctor --profile opcos` reports BG1 (description > 350 chars) and the `budget` block.

Run: python -X utf8 -m unittest tests.test_budget -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402

C = _engine.const
doctor = _engine.doctor
validate = _engine.validate


def write_skill(root: Path, name: str, desc_lines: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_bytes(("---\nname: %s\ndescription: %s\n---\n\n# Title\n\nShort body.\n" % (name, desc_lines)).encode("utf-8"))
    return folder


def codes(folder: Path, profile: str) -> list:
    return [f["code"] for f in validate.validate_skill(folder, profile=profile)]


LONG = "Checks a toy example. Use when testing the budget. " + "x" * 320  # 370 chars


class BudgetTests(unittest.TestCase):
    def test_bg1_over_350_opcos_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = write_skill(Path(tmp), "long-one", LONG)
            short = write_skill(Path(tmp), "short-one", "Checks a toy. Use when testing the budget.")
            self.assertIn("BG1", codes(skill, "opcos"))
            self.assertNotIn("BG1", codes(skill, "portable"))
            self.assertNotIn("BG1", codes(short, "opcos"))
            level = next(f["level"] for f in validate.validate_skill(skill, profile="opcos") if f["code"] == "BG1")
            self.assertEqual(level, "WARN")

    def test_bg1_block_scalar_joined(self):
        # Lines of a block scalar are joined by one space, as get_field of measure-skill-budget.py does: 3 x 117 chars + 2 spaces = 353.
        part = "a" * 110 + " Use when"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "blocky"
            folder.mkdir()
            text = "---\nname: blocky\ndescription: |\n  %s\n  %s\n  %s\n---\n\n# T\n\nBody.\n" % (part, part, part)
            (folder / "SKILL.md").write_bytes(text.encode("utf-8"))
            meta, _f, _e = _engine.fs.parse_frontmatter(text, folder / "SKILL.md")
            self.assertEqual(validate.desc_chars_like_budget(meta), 3 * len(part) + 2)
            self.assertIn("BG1", codes(folder, "opcos"))

    def test_budget_total_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(60):
                write_skill(root, "skill-%02d" % i, LONG)
            report = doctor.doctor_run([root], "opcos", "portable", False, None)
            self.assertEqual(report["budget"]["limit"], 20000)
            self.assertEqual(report["budget"]["desc_bytes_total"], 60 * len(LONG))
            self.assertTrue(report["budget"]["over"])
            small = Path(tmp) / "small"
            write_skill(small, "tiny", "Checks. Use when testing.")
            under = doctor.doctor_run([small], "opcos", "portable", False, None)
            self.assertFalse(under["budget"]["over"])
            self.assertEqual(under["budget"]["desc_bytes_total"], len("Checks. Use when testing."))

    def test_budget_absent_portable(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(Path(tmp), "one", LONG)
            report = doctor.doctor_run([Path(tmp)], "portable", "portable", False, None)
            self.assertNotIn("budget", report)


if __name__ == "__main__":
    unittest.main()
