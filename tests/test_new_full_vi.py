"""SPR-02 TK9 (FR9, FR10): `new --full --lang vi`, and the two workflow references in the shape `fmt` checks (`PR1`).

Labels: bắt-lỗi = red on the parent commit by exit code/assertion; tương-đương = green before and after (guard).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

ROOT = E.ROOT
SKILL_DIR = ROOT / "skills" / "skill-creator-studio"
FULL = SKILL_DIR / "assets" / "skill-template-full"
DESC = "Demo skill for full template tests. Use when testing the Vietnamese full scaffold."


def studio(*args, cwd=ROOT):
    run = subprocess.run([sys.executable, "-X", "utf8", str(E.ENGINE_PATH), *map(str, args)], cwd=str(cwd), stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, encoding="utf-8", timeout=300)
    return run.returncode, run.stdout, run.stderr


def tree(base: Path) -> list:
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())


class NewFullViTests(unittest.TestCase):
    def new(self, base: str, name: str, *extra):
        skills, evals = Path(base) / "skills", Path(base) / "evals"
        code, out, err = studio("new", name, "--description", DESC, "--output", skills, "--eval-root", evals, *extra)
        return code, out, err, skills / name

    def test_bat_loi_new_full_lang_vi_exits_0_with_a_vietnamese_skill_md(self):
        """bắt-lỗi: `new --full --lang vi` exits 0 (today: exit 2), SKILL.md has the Vietnamese body and the chosen name, and no SKILL.vi.md is left in the new skill."""
        with tempfile.TemporaryDirectory() as t:
            code, out, err, skill = self.new(t, "demo-fv", "--full", "--lang", "vi")
            self.assertEqual(0, code, out + err)
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("name: demo-fv", text)
            self.assertIn("## Mục đích và phạm vi", text)
            self.assertIn("# Demo Fv", text)
            self.assertIn("STUDIO-DRAFT", text)
            self.assertFalse((skill / "SKILL.vi.md").exists())
            en_tree = [p for p in tree(FULL) if p != "SKILL.vi.md"]
            self.assertEqual(en_tree, tree(skill))

    def test_bat_loi_new_full_lang_vi_skill_validates_with_no_error(self):
        """bắt-lỗi: the skill that `new --full --lang vi` makes passes `validate` with 0 ERROR (today: no skill is made)."""
        with tempfile.TemporaryDirectory() as t:
            code, out, err, skill = self.new(t, "demo-fv", "--full", "--lang", "vi")
            self.assertEqual(0, code, out + err)
            vcode, vout, verr = studio("validate", skill, "--json")
            report = json.loads(vout)
            errors = [f for r in report["reports"] for f in r["findings"] if f["level"] == "ERROR"]
            self.assertEqual([], errors, vout + verr)

    def test_tuong_duong_new_full_en_tree_has_no_vietnamese_file(self):
        """tương-đương: `new --full` (English) copies the same files as before and no SKILL.vi.md; its SKILL.md stays English."""
        with tempfile.TemporaryDirectory() as t:
            code, out, err, skill = self.new(t, "demo-fe", "--full")
            self.assertEqual(0, code, out + err)
            self.assertFalse((skill / "SKILL.vi.md").exists())
            self.assertIn("## Purpose and scope", (skill / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual(sorted(["SKILL.md", "agents/openai.yaml", "assets/sample-data/example.json", "assets/templates/OUTPUT_TEMPLATE.md",
                                     "references/PROCESS_TEMPLATE.md", "scripts/check_inputs.py"]), tree(skill))

    def test_tuong_duong_new_lang_vi_minimal_unchanged(self):
        """tương-đương: `new --lang vi` (no --full) still makes one Vietnamese SKILL.md."""
        with tempfile.TemporaryDirectory() as t:
            code, out, err, skill = self.new(t, "demo-mv", "--lang", "vi")
            self.assertEqual(0, code, out + err)
            self.assertEqual(["SKILL.md"], tree(skill))
            self.assertIn("## Gotchas", (skill / "SKILL.md").read_text(encoding="utf-8"))

    def test_don_vi_ham_moi_full_vietnamese_template_mirrors_the_english_one(self):
        """đơn-vị-hàm-mới: SKILL.vi.md of the full template has the same frontmatter, section count, numbered steps, links and draft marker as SKILL.md."""
        en = (FULL / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        vi = (FULL / "SKILL.vi.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(en.split("---\n", 2)[1], vi.split("---\n", 2)[1], "frontmatter stays English and identical")
        self.assertEqual(len(re.findall(r"^## ", en, re.M)), len(re.findall(r"^## ", vi, re.M)))
        self.assertEqual(len(re.findall(r"^\d+\. ", en, re.M)), len(re.findall(r"^\d+\. ", vi, re.M)))
        self.assertEqual(re.findall(r"\]\(([^)]+)\)", en), re.findall(r"\]\(([^)]+)\)", vi))
        self.assertEqual(re.findall(r"`((?:scripts|assets)/[^`]+)`", en), re.findall(r"`((?:scripts|assets)/[^`]+)`", vi))
        self.assertIn("STUDIO-DRAFT", vi)
        self.assertIn("# Skill Template", vi)


class ProcessShapeTests(unittest.TestCase):
    def test_bat_loi_workflow_references_have_no_pr1(self):
        """bắt-lỗi: NEW_WORKFLOW.md and REFINE_WORKFLOW.md have the process shape `fmt` looks for: 0 PR1 findings (today: 6 each)."""
        for name in ("NEW_WORKFLOW.md", "REFINE_WORKFLOW.md"):
            with self.subTest(file=name):
                text = (SKILL_DIR / "references" / name).read_text(encoding="utf-8")
                self.assertEqual([], E.fmt.check_process_shape(text))

    def test_bat_loi_fmt_check_of_the_skill_folder_reports_no_pr1(self):
        """bắt-lỗi: `fmt --check skills/skill-creator-studio --json` lists no PR1 finding in any file (today: 12)."""
        code, out, err = studio("fmt", "--check", SKILL_DIR, "--json")
        report = json.loads(out)
        pr1 = [(os.path.basename(f["path"]), x["message"]) for f in report["files"] for x in f["findings"] if x["code"] == "PR1"]
        self.assertEqual([], pr1, out)

    def test_bat_loi_new_workflow_no_longer_says_full_vi_exits_2(self):
        """bắt-lỗi: NEW_WORKFLOW.md describes the new behaviour of `--full --lang vi`, not the old exit 2 (today: «exits 2»)."""
        text = (SKILL_DIR / "references" / "NEW_WORKFLOW.md").read_text(encoding="utf-8")
        self.assertNotIn("exits 2", text)
        self.assertNotIn("English-only", text)

    def test_bat_loi_skill_md_no_longer_says_full_is_english_only(self):
        """bắt-lỗi: SKILL.md of the skill no longer says the full template cannot combine with `--lang vi` (today: «English-only»)."""
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("English-only", text)
        self.assertNotIn("cannot combine", text)


if __name__ == "__main__":
    unittest.main()
