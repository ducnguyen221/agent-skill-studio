"""SPR-05 TK1 (FR1.1, FR1.2, FR6.1, SC1, SC6): open a file without following a link at its last name, on Windows too; a hard link is not read.

Labels: bắt-lỗi = red on a695479 by assertion; tương-đương = green before and after (guard); đơn-vị = touches the new API, not counted in SC1.
Symlink cases skip here with `symlink-privilege`; the junction and hard-link cases run for real on Windows.

Run: python -X utf8 -m unittest tests.test_spr05_open -v
"""
from __future__ import annotations

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
from test_catalog import load_catalog_module  # noqa: E402

fs = E.fs
SKILL = "---\nname: %s\ndescription: Checks a toy example. Use when testing the safe open.\n---\n\n# Title\n\n%s\n"


class OpenCase(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05open_")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def assertRefused(self, call, *args, **kwargs):
        """The call must raise UnsafeOpen; any other outcome (a different error, a returned value) is a failed assertion, not a crash."""
        try:
            result = call(*args, **kwargs)
        except fs.UnsafeOpen as exc:
            return exc
        except OSError as exc:
            self.fail("expected UnsafeOpen, got %s: %s" % (type(exc).__name__, exc))
        self.fail("expected UnsafeOpen, got a result: %r" % (result,))


class ReadCappedLinkTests(OpenCase):
    def test_read_capped_refuses_symlink(self):
        """bắt-lỗi: FR1.2 read_capped on a symlink is refused, with and without a limit (no open() that follows it)."""
        target = self.tmp / "real.md"
        target.write_text("SECRET\n", encoding="utf-8")
        link = self.tmp / "link.md"
        _links.make_symlink(target, link)
        for limit in (None, 100):
            with self.subTest(limit=limit):
                self.assertRefused(fs.read_capped, link, limit)

    def test_read_capped_refuses_a_junction_in_the_file_spot(self):
        """bắt-lỗi: FR1.2 a junction (symlink on POSIX) where the file should be is UnsafeOpen, not PermissionError from a plain open()."""
        folder = self.tmp / "folder"
        folder.mkdir()
        (folder / "secret.txt").write_text("SECRET", encoding="utf-8")
        link = self.tmp / "junc.md"
        _links.dir_link(folder, link)
        for limit in (None, 100):
            with self.subTest(limit=limit):
                self.assertRefused(fs.read_capped, link, limit)

    def test_read_capped_plain_file(self):
        """tương-đương: a plain file reads as before: newlines folded, UTF-8, too_big above the limit, None for no limit."""
        path = self.tmp / "a.md"
        path.write_bytes("dòng một\r\ndòng hai\rba\n".encode("utf-8"))
        self.assertEqual(fs.read_capped(path, None), ("dòng một\ndòng hai\nba\n", False))
        self.assertEqual(fs.read_capped(path, 1000), ("dòng một\ndòng hai\nba\n", False))
        self.assertEqual(fs.read_capped(path, 5), (None, True))
        path.write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(UnicodeError):
            fs.read_capped(path, None)

    def test_read_capped_single_link_refuses_a_hard_link(self):
        """đơn-vị: FR6.1 with single_link=True a file with two names is refused before a byte is read; without it the file reads (the old default)."""
        real = self.tmp / "real.md"
        real.write_text("SECRET\n", encoding="utf-8")
        _links.make_hardlink(real, self.tmp / "alias.md")
        exc = self.assertRefused(fs.read_capped, self.tmp / "alias.md", 100, single_link=True)
        self.assertIn("hard link", str(exc))
        self.assertEqual(fs.read_capped(self.tmp / "alias.md", 100), ("SECRET\n", False))


@unittest.skipUnless(os.name == "nt", "Windows opens through CreateFile; POSIX through O_NOFOLLOW")
class WindowsOpenTests(OpenCase):
    def test_open_refuses_reparse_without_following(self):
        """bắt-lỗi: FR1.1 on Windows a link in the file spot is refused without os.open ever seeing the link path (open then compare is gone)."""
        folder = self.tmp / "folder"
        folder.mkdir()
        link = self.tmp / "junc.md"
        _links.dir_link(folder, link)
        seen = []
        real_open = os.open

        def spy(path, *args, **kwargs):
            seen.append(os.fspath(path))
            return real_open(path, *args, **kwargs)

        with mock.patch.object(os, "open", spy):
            self.assertRefused(fs.open_nofollow_read, link, os.lstat(link), False)
        self.assertEqual([p for p in seen if p == os.fspath(link)], [])

    def test_folder_in_the_file_spot_is_unsafe_open(self):
        """bắt-lỗi: FR1.1 a real folder where a file is expected is UnsafeOpen (not PermissionError 5)."""
        folder = self.tmp / "dir.md"
        folder.mkdir()
        self.assertRefused(fs.open_nofollow_read, folder)

    def test_missing_winapi_fails_closed(self):
        """bắt-lỗi: SC6 without _winapi the open is refused («safe open unavailable»), not done with a plain open()."""
        path = self.tmp / "a.md"
        path.write_text("x\n", encoding="utf-8")
        with mock.patch.dict(sys.modules, {"_winapi": None}):
            exc = self.assertRefused(fs.open_nofollow_read, path)
            self.assertIn("safe open unavailable", str(exc))
            self.assertRefused(fs.read_capped, path, 100)

    def test_missing_file_is_still_file_not_found(self):
        """tương-đương: a missing file raises FileNotFoundError as before (callers tell «absent» from «refused»)."""
        with self.assertRaises(FileNotFoundError):
            fs.open_nofollow_read(self.tmp / "nope.md")


class HardLinkCallerTests(OpenCase):
    def test_hardlink_skill_md_skipped_by_validate(self):
        """bắt-lỗi: FR6.1 a SKILL.md with two names gets an INPUT error naming «hard link», and its content reaches no finding."""
        store = self.tmp / "store"
        store.mkdir()
        (store / "real.md").write_text(SKILL % ("s", "LEAKED_BODY"), encoding="utf-8")
        skill = self.tmp / "s"
        skill.mkdir()
        _links.make_hardlink(store / "real.md", skill / "SKILL.md")
        findings = E.validate.validate_skill(skill)
        self.assertEqual([f["code"] for f in findings], ["INPUT"], findings)
        self.assertIn("hard link", findings[0]["message"])
        self.assertNotIn("LEAKED_BODY", repr(findings))

    def test_hardlink_skill_md_gives_no_catalog_description(self):
        """bắt-lỗi: FR6.1 the catalog row of a hard-linked SKILL.md carries the folder name and no description."""
        store = self.tmp / "store"
        store.mkdir()
        (store / "real.md").write_text(SKILL % ("other-name", "body"), encoding="utf-8")
        skill = self.tmp / "s"
        skill.mkdir()
        _links.make_hardlink(store / "real.md", skill / "SKILL.md")
        name, desc, keys, notes = load_catalog_module()._read_skill_meta(skill)
        self.assertEqual((name, desc), ("s", ""))

    def test_hardlink_manifest_is_not_read_by_roots(self):
        """bắt-lỗi: FR6.1 a plugin manifest / index with two names is a RootError (reason link), its JSON is not returned."""
        base = self.tmp / "base"
        base.mkdir()
        store = self.tmp / "store.json"
        store.write_text('{"name": "LEAK"}', encoding="utf-8")
        _links.make_hardlink(store, base / "plugin.json")
        try:
            value = E.roots._read_json(base / "plugin.json", 4096, E.const.CLOUD_MARKERS, base)
        except E.roots.RootError as exc:
            self.assertIn("hard link", str(exc))
        else:
            self.fail("expected RootError, read %r" % (value,))


if __name__ == "__main__":
    unittest.main()
