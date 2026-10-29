"""SPR-05 TK7 (FR10.1, FR10.2, SC1): one folder budget for the whole scan, and a `limit` line whenever the scan was cut.

A skill may hold skills (05-forensics holds 05a..05d). The folders listed while looking inside skills spend the same DOCTOR_MAX_DIRS as the folders
listed by the first pass: the sum for one run never passes the limit (FR10.1). A scan cut by the budget or by DOCTOR_MAX_SKILL_DEPTH always says so,
as one `limit` line, even when the cut falls where the walk would not go on anyway (FR10.2). Labels: bắt-lỗi = red on a695479 by assertion;
tương-đương = green before and after (guard).

Run: python -X utf8 -m unittest tests.test_spr05_budget -v
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

C = E.const
R = E.roots
SKILL = "---\nname: %s\ndescription: Checks a toy. Use when testing the folder budget.\n---\n\n# Title\n\nShort body.\n"


def make_skill(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(SKILL % folder.name.replace("_", "-"), encoding="utf-8")
    return folder


class BudgetCase(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05bud_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plugin = self.tmp / "plug"
        (self.plugin / ".claude-plugin").mkdir(parents=True)
        (self.plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "plug"}), encoding="utf-8")

    def root(self) -> dict:
        return {"path": self.plugin.as_posix(), "kind": "plugin", "area": "plugins", "status": "ok", "reasons": [], "skipped_by_rule": []}

    def scan(self) -> tuple:
        """(skills, skipped, root, number of folders listed under the test folder) of collect_skills over the one plugin."""
        root, counted, real = self.root(), [], os.scandir
        tag = self.tmp.name.casefold()  # the folder is told by its name: the engine may spell the same folder long or 8.3

        def counting(path=".", *a, **k):
            if tag in os.fspath(path).casefold():
                counted.append(os.fspath(path))
            return real(path, *a, **k)

        with mock.patch.object(os, "scandir", counting):
            skills, skipped = R.collect_skills([root])
        return skills, skipped, root, counted


class FolderBudgetTests(BudgetCase):
    def test_nested_skills_spend_one_budget_for_the_whole_run(self):
        """bắt-lỗi: FR10.1 three skills inside a skill, each in a folder of ten more folders, with DOCTOR_MAX_DIRS=20: the folders listed in the whole run are at most 20
        (the nested scans used to count again from zero), and the cut is reported once, as `limit`, with the root partial."""
        outer = make_skill(self.plugin / "skills" / "outer")
        for i in range(3):
            group = outer / ("g%d" % i)
            make_skill(group / "inner")
            for j in range(10):
                (group / ("d%d" % j)).mkdir()
        with mock.patch.object(C, "DOCTOR_MAX_DIRS", 20):
            skills, skipped, root, counted = self.scan()
        self.assertLessEqual(len(counted), 20, counted)
        self.assertEqual([item for item in skipped if item["reason"] == "limit"].__len__(), 1, skipped)
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["limit"]))
        self.assertLess(len(skills), 4)

    def test_a_tree_that_fits_is_scanned_whole_without_limit(self):
        """tương-đương: FR10.1 with the default limit the same tree is scanned whole: four skills, no `limit`."""
        outer = make_skill(self.plugin / "skills" / "outer")
        for i in range(3):
            group = outer / ("g%d" % i)
            make_skill(group / "inner")
            for j in range(10):
                (group / ("d%d" % j)).mkdir()
        skills, skipped, root, _ = self.scan()
        self.assertEqual(len(skills), 4, skills)
        self.assertEqual([item for item in skipped if item["reason"] == "limit"], [])
        self.assertEqual((root["status"], root["reasons"]), ("ok", []))


class LimitLineTests(BudgetCase):
    def test_budget_ending_where_the_depth_stops_is_still_reported(self):
        """bắt-lỗi: FR10.2 the budget runs out while skills inside a skill are still to be looked at, and the walk is at the deepest allowed level
        (DOCTOR_MAX_SKILL_DEPTH=1): the old code stepped into the folder and returned without a word. Now one `limit` line."""
        outer = make_skill(self.plugin / "skills" / "outer")
        for i in range(5):
            make_skill(outer / ("g%d" % i) / "inner")
        with mock.patch.object(C, "DOCTOR_MAX_SKILL_DEPTH", 1), mock.patch.object(C, "DOCTOR_MAX_DIRS", 5):
            skills, skipped, root, counted = self.scan()
        self.assertLessEqual(len(counted), 5, counted)
        self.assertEqual(len([item for item in skipped if item["reason"] == "limit"]), 1, skipped)
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["limit"]))

    def test_depth_cut_is_reported_as_limit(self):
        """bắt-lỗi: FR10.2 skills nested deeper than DOCTOR_MAX_SKILL_DEPTH (=2) are not looked at and the result says so with a `limit` line for the cut place."""
        node = make_skill(self.plugin / "skills" / "s0")
        for level in range(1, 5):
            node = make_skill(node / "grp" / ("s%d" % level))
        with mock.patch.object(C, "DOCTOR_MAX_SKILL_DEPTH", 2):
            skills, skipped, root, _ = self.scan()
        limits = [item for item in skipped if item["reason"] == "limit"]
        self.assertEqual(len(limits), 1, skipped)
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["limit"]))
        self.assertLess(len(skills), 5)

    def test_nesting_within_the_depth_has_no_limit_line(self):
        """tương-đương: FR10.2 nesting that stays within DOCTOR_MAX_SKILL_DEPTH is not cut and gets no `limit` line."""
        node = make_skill(self.plugin / "skills" / "s0")
        node = make_skill(node / "grp" / "s1")
        skills, skipped, root, _ = self.scan()
        self.assertEqual(len(skills), 2, skills)
        self.assertEqual([item for item in skipped if item["reason"] == "limit"], [])
        self.assertEqual((root["status"], root["reasons"]), ("ok", []))


if __name__ == "__main__":
    unittest.main()
