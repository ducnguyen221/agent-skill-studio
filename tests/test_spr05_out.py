"""SPR-05 TK4 (FR4.1, FR8.1, SC1): `--out` / `--md` are written by replacing the file atomically, never through a link; `--home` guards its own harness folders.

Labels: bắt-lỗi = red on a695479 by assertion; tương-đương = green before and after (guard, or a case a695479 already closes); đơn-vị = new API.
The symlink case skips here (`symlink-privilege`); the junction cases run for real.

Run: python -X utf8 -m unittest tests.test_spr05_out -v
"""
from __future__ import annotations

import contextlib
import io
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
import _links  # noqa: E402

fs = E.fs
SKILL = "---\nname: %s\ndescription: A plain skill. Use when testing the atomic output.\n---\n\n# Title\n\nShort body.\n"


def run_cli(*argv, cwd=None, home=None):
    out, err = io.StringIO(), io.StringIO()
    before, code = os.getcwd(), 0
    try:
        if cwd is not None:
            os.chdir(cwd)
        with mock.patch.dict(os.environ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            os.environ.pop("OPCOS_ROOT", None)
            try:
                code = E.engine.main([str(x) for x in argv])
            except SystemExit as exc:
                code = exc.code
    finally:
        os.chdir(before)
    return code, out.getvalue(), err.getvalue()


class OutCase(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05out_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "root"
        (self.root / "one").mkdir(parents=True)
        (self.root / "one" / "SKILL.md").write_text(SKILL % "one", encoding="utf-8")
        self.safe = self.tmp / "safe"
        self.safe.mkdir()

    def leftovers(self, folder: Path) -> list:
        return sorted(p.name for p in folder.iterdir() if p.name.endswith(".spr05tmp"))


class AtomicOutTests(OutCase):
    def test_catalog_out_swapped_to_symlink_keeps_the_link_target(self):
        """bắt-lỗi: FR4.1 `--out` that became a symlink after the check is replaced as a name: the file it pointed to is unchanged, `--out` is now a plain JSON file."""
        victim = self.tmp / "victim.txt"
        victim.write_text("VICTIM", encoding="utf-8")
        link = self.safe / "report.json"
        _links.make_symlink(victim, link)
        with mock.patch.object(E.doctor, "out_problem", lambda *a, **k: None):
            code, out, err = run_cli("catalog", "--roots", self.root, "--out", link, cwd=self.tmp)
        self.assertEqual(victim.read_text(encoding="utf-8"), "VICTIM", out + err)
        self.assertFalse(fs.is_link(link))
        self.assertEqual(json.loads(link.read_text(encoding="utf-8"))["schema"], 1)

    def test_catalog_out_junction_is_refused_and_untouched(self):
        """tương-đương: FR4.1 (closed before the sprint: an open() of a folder fails) `--out` is a junction: exit 2, ERROR, nothing written behind it, with and without the early check."""
        ext = self.tmp / "ext"
        ext.mkdir()
        link = self.safe / "report.json"
        _links.dir_link(ext, link)
        for blind in (False, True):
            with self.subTest(blind=blind):
                patcher = mock.patch.object(E.doctor, "out_problem", lambda *a, **k: None) if blind else contextlib.nullcontext()
                with patcher:
                    code, out, err = run_cli("catalog", "--roots", self.root, "--out", link, cwd=self.tmp)
                self.assertEqual(code, 2, out + err)
                self.assertIn("ERROR", err)
                self.assertEqual(os.listdir(ext), [])

    def test_failed_replace_keeps_the_old_file_and_leaves_no_temp(self):
        """bắt-lỗi: FR4.2-style the output is written to a temp file and renamed: a failing rename leaves the old report byte for byte and no *.spr05tmp."""
        target = self.safe / "report.json"
        old = '{"schema": 1, "old": true}\n'
        target.write_text(old, encoding="utf-8")
        for argv in (("catalog", "--roots", self.root, "--out", target), ("doctor", "--roots", self.root, "--out", target)):
            with self.subTest(command=argv[0]):
                with mock.patch("os.replace", side_effect=OSError("disk gone")):
                    code, out, err = run_cli(*argv, cwd=self.tmp)
                self.assertEqual(code, 2, out + err)
                self.assertIn("ERROR", err)
                self.assertEqual(target.read_text(encoding="utf-8"), old)
                self.assertEqual(self.leftovers(self.safe), [])

    def test_successful_out_leaves_no_temp(self):
        """tương-đương: after a good run only the report is in the folder."""
        target = self.safe / "report.json"
        code, out, err = run_cli("catalog", "--roots", self.root, "--out", target, cwd=self.tmp)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(sorted(p.name for p in self.safe.iterdir()), ["report.json"])

    @unittest.skipUnless(os.name == "nt", "an NTFS data stream is a Windows name")
    def test_out_with_a_stream_name_is_refused(self):
        """tương-đương: FR8-adjacent (closed before the sprint) `--out x.json:ads` is an ERROR, exit 2, nothing created."""
        code, out, err = run_cli("catalog", "--roots", self.root, "--out", str(self.safe / "x.json:ads"), cwd=self.tmp)
        self.assertEqual(code, 2, out + err)
        self.assertIn("ERROR", err)
        self.assertEqual(os.listdir(self.safe), [])


class HomeOptionTests(OutCase):
    def test_home_option_guards_its_harness_folders(self):
        """bắt-lỗi: FR8.1 with `--home H` an output under H/.claude, H/.codex or H/.gemini is refused like one under the real home."""
        home = self.tmp / "home"
        for name in (".claude", ".codex", ".gemini"):
            (home / name).mkdir(parents=True)
            with self.subTest(name):
                target = home / name / "x.json"
                code, out, err = run_cli("catalog", "--roots", self.root, "--home", home, "--installed", "claude", "--out", target, cwd=self.tmp)
                self.assertEqual(code, 2, out + err)
                self.assertIn("harness folder", err)
                self.assertFalse(target.exists())


class WriteReplaceUnitTests(OutCase):
    def test_replaces_a_file_and_keeps_no_temp(self):
        """đơn-vị: write_replace puts the bytes in place; the temp name carries the constant suffix while it exists."""
        target = self.safe / "a.json"
        target.write_bytes(b"OLD")
        fs.write_replace(target, "tiếng Việt\n".encode("utf-8"))
        self.assertEqual(target.read_bytes(), "tiếng Việt\n".encode("utf-8"))
        self.assertEqual(sorted(p.name for p in self.safe.iterdir()), ["a.json"])
        self.assertEqual(E.const.REPLACE_TMP_SUFFIX, ".spr05tmp")

    def test_creates_a_missing_target(self):
        """đơn-vị: a target that is not there yet is created."""
        target = self.safe / "new.json"
        fs.write_replace(target, b"{}")
        self.assertEqual(target.read_bytes(), b"{}")

    def test_junction_target_is_refused(self):
        """đơn-vị: review focus 3 a junction at the target name is UnsafeOpen («folder»), the folder behind it is untouched."""
        ext = self.tmp / "ext"
        ext.mkdir()
        link = self.safe / "j.json"
        _links.dir_link(ext, link)
        with self.assertRaises(fs.UnsafeOpen):
            fs.write_replace(link, b"X")
        self.assertEqual(os.listdir(ext), [])
        self.assertTrue(fs.is_link(link))

    def test_failure_removes_the_temp_and_keeps_the_target(self):
        """đơn-vị: review focus 4 an error between the write and the rename removes the temp file and re-raises."""
        target = self.safe / "a.json"
        target.write_bytes(b"OLD")
        with mock.patch("os.replace", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                fs.write_replace(target, b"NEW")
        self.assertEqual(target.read_bytes(), b"OLD")
        self.assertEqual(self.leftovers(self.safe), [])

    def test_junction_in_the_chain_is_refused(self):
        """đơn-vị: FR2.1 a junction between the anchor and the target stops the write."""
        ext = self.tmp / "ext"
        ext.mkdir()
        (self.safe / "a").mkdir()
        _links.dir_link(ext, self.safe / "a" / "b")
        with self.assertRaises(fs.UnsafeOpen):
            fs.write_replace(self.safe / "a" / "b" / "x.json", b"X", anchor=self.safe)
        self.assertEqual(os.listdir(ext), [])


if __name__ == "__main__":
    unittest.main()
