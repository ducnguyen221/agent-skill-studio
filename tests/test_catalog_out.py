"""SPR-04 TK9 (FR2.3, review focus 4): where `catalog --out` and `--md` may write, and what they may overwrite.

Every refusal test runs inside the in-process write guard, so a catalog written to a refused place raises PermissionError instead of landing on disk.

Run: python -X utf8 -m unittest tests.test_catalog_out -v
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402
import _writeguard  # noqa: E402
from test_catalog import TmpCase, run_catalog  # noqa: E402


class CatalogOutTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.tree = self.clean_tree()
        self.safe = self.tmp / "safe"
        self.safe.mkdir()

    def refused(self, *argv, expect="") -> str:
        """Run catalog with the guard on (only `safe` may be written); the exit must be 2 with `expect` in the message."""
        with _writeguard.block_writes_outside([self.safe]):
            code, out, err = run_catalog("--roots-from", "opcos", *argv, cwd=self.tree)
        self.assertEqual(code, 2, out + err)
        self.assertIn(expect, err)
        return err

    def test_out_refused_in_scanned_root(self):
        """bắt-lỗi: review focus 4 --out and --md inside a scanned root are refused with exit 2 and nothing is written; outside it they are written."""
        for flag, name in (("--out", "inside.json"), ("--md", "INSIDE.md")):
            with self.subTest(flag):
                target = self.tree / "plugins" / name
                self.refused(flag, str(target), expect="scanned root")
                self.assertFalse(target.exists())
        target = self.tree / "system" / "opcos-plugin" / "report.json"
        self.refused("--out", str(target), expect="scanned")
        self.assertFalse(target.exists())

    def test_out_refused_inside_a_scanned_skill_folder(self):
        """bắt-lỗi: review focus 4 a report may not land inside a scanned skill folder."""
        skill = self.tree / "plugins" / "p-two" / "skills" / "two"
        for flag, name in (("--out", "r.json"), ("--md", "R.md")):
            self.refused(flag, str(skill / name), expect="must not be")
            self.assertFalse((skill / name).exists())

    def test_out_refused_in_a_harness_folder(self):
        """bắt-lỗi: review focus 4 a report may not land under the harness folders of the home folder (~/.claude, ~/.codex, ~/.gemini)."""
        home = self.tmp / "home"
        for name in (".claude", ".codex", ".gemini"):
            (home / name / "plugins").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
            for name in (".claude", ".codex", ".gemini"):
                for flag, leaf in (("--out", "catalog.json"), ("--md", "CATALOG.md")):
                    with self.subTest(name, flag=flag):
                        target = home / name / "plugins" / leaf
                        self.refused(flag, str(target), expect="harness folder")
                        self.assertFalse(target.exists())

    def test_out_refused_for_secret_names_and_missing_folders(self):
        """bắt-lỗi: review focus 4 a secret-looking name, a folder that does not exist and a path that is a folder are refused."""
        self.refused("--out", str(self.safe / ".env"), expect="secret-looking")
        self.refused("--md", str(self.safe / ".env.md"), expect="secret-looking")
        self.refused("--out", str(self.safe / "nofolder" / "x.json"), expect="does not exist")
        (self.safe / "dir.json").mkdir()
        self.refused("--out", str(self.safe / "dir.json"), expect="plain file")

    def test_overwrite_only_what_is_a_catalog(self):
        """bắt-lỗi: review focus 4 --out replaces an empty file or a schema report, --md an empty file or a CATALOG.md; any other file is refused and kept."""
        notes = self.safe / "notes.md"
        notes.write_text("# my notes\n", encoding="utf-8")
        self.refused("--md", str(notes), expect="not a catalog")
        self.assertEqual(notes.read_text(encoding="utf-8"), "# my notes\n")
        data = self.safe / "data.json"
        data.write_text('{"other": 1}', encoding="utf-8")
        self.refused("--out", str(data), expect="not a catalog report")
        self.assertEqual(data.read_text(encoding="utf-8"), '{"other": 1}')
        text = self.safe / "plain.txt"
        text.write_text("x", encoding="utf-8")
        self.refused("--out", str(text), expect="not a")
        self.assertEqual(text.read_text(encoding="utf-8"), "x")

    def test_second_run_on_the_same_files_is_accepted(self):
        """bắt-lỗi: review focus 4 running again over its own report and CATALOG.md works (the files start with the marker), also when they are empty."""
        out, md = self.safe / "catalog.json", self.safe / "CATALOG.md"
        for round_ in range(2):
            with _writeguard.block_writes_outside([self.safe]):
                code, so, se = run_catalog("--roots-from", "opcos", "--out", str(out), "--md", str(md), cwd=self.tree)
            self.assertEqual(code, 0, "round %d: %s%s" % (round_, so, se))
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["schema"], 1)
        self.assertEqual(md.read_text(encoding="utf-8").splitlines()[0], "<!-- studio catalog -->")
        for path in (out, md):
            path.write_text("", encoding="utf-8")
        code, so, se = run_catalog("--roots-from", "opcos", "--out", str(out), "--md", str(md), cwd=self.tree)
        self.assertEqual(code, 0, so + se)
        md.write_bytes(b"\xef\xbb\xbf<!-- studio catalog -->\r\nold\r\n")
        self.assertEqual(run_catalog("--roots-from", "opcos", "--md", str(md), cwd=self.tree)[0], 0)
        self.assertNotIn("old", md.read_text(encoding="utf-8"))

    def test_roots_option_has_the_same_rules(self):
        """bắt-lỗi: review focus 4 with --roots the report may not land in a root either."""
        base = self.tmp / "lib" / "skills"
        base.mkdir(parents=True)
        from test_catalog import make_skill
        make_skill(base / "s1")
        target = self.tmp / "lib" / "skills" / "CATALOG.md"
        with _writeguard.block_writes_outside([self.safe]):
            code, out, err = run_catalog("--roots", str(base), "--md", str(target))
        self.assertEqual(code, 2, out + err)
        self.assertFalse(target.exists())
        good = self.safe / "CATALOG.md"
        code, out, err = run_catalog("--roots", str(base), "--md", str(good))
        self.assertEqual(code, 0, out + err)
        self.assertTrue(good.is_file())

    def test_write_failure_is_exit_2(self):
        """bắt-lỗi: FR2.3 a file that cannot be written gives exit 2 and a message, not a traceback."""
        target = self.safe / "catalog.json"
        real_open = open

        def failing(path, mode="r", *a, **k):
            if "w" in mode and Path(path) == target:
                raise OSError(13, "denied")
            return real_open(path, mode, *a, **k)

        with mock.patch("builtins.open", failing):
            code, out, err = run_catalog("--roots-from", "opcos", "--out", str(target), cwd=self.tree)
        self.assertEqual(code, 2, out + err)
        self.assertIn("cannot write --out", err)


if __name__ == "__main__":
    unittest.main()
