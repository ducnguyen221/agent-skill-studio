"""SPR-05 lane A, review round 2 (CI on 0b10713: Linux, macOS, Windows with Python 3.9).

Root causes, one test each: (1) on Python 3.9 `_winapi.CreateFile` is the ANSI function, so a non-ASCII name was created under a wrong (mojibake) name;
(2) `anchor_for` compared the working folder with the path by spelling only, so on macOS (`/var` is a link to `/private/var`) a path below the working
folder was anchored at its own folder, which since RF-A5 may itself be a link; (3) a symlink to a folder at the output name was replaced as if it were a file.

Run: python -X utf8 -m unittest tests.test_spr05_round2 -v
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402
import _links  # noqa: E402

fs = E.fs
VI = "Dữ liệu"  # NFC, as the export writes it


class Round2Case(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05r2_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class NonAsciiNameTests(Round2Case):
    def test_non_ascii_names_are_made_and_read_under_their_own_name(self):
        """bắt-lỗi: a file and a folder with Vietnamese letters are created, listed, pinned, read and replaced by their real names (Python 3.9: CreateFile was ANSI)."""
        folder = self.tmp / ("thư mục " + VI)
        folder.mkdir()
        target = folder / (VI + ".csv")
        with fs.create_exclusive(target, anchor=self.tmp) as handle:
            handle.write(b"1")
        self.assertEqual(os.listdir(folder), [VI + ".csv"])
        self.assertEqual(fs.read_capped(target, None, anchor=self.tmp), ("1", False))
        fs.write_replace(target, b"2", anchor=self.tmp)
        self.assertEqual(target.read_bytes(), b"2")
        self.assertEqual(os.listdir(folder), [VI + ".csv"])


class AnchorForAliasTests(Round2Case):
    def test_anchor_is_found_when_the_working_folder_is_spelled_through_a_link(self):
        """bắt-lỗi: the working folder is `real`; the path is spelled through a link to it (macOS /var -> /private/var): the anchor is that spelling of `real`, so a link folder below it is still checked."""
        real = self.tmp / "real"
        (real / "sub").mkdir(parents=True)
        alias = self.tmp / "alias"
        _links.dir_link(real, alias)
        path = alias / "sub" / "roots.txt"
        self.assertEqual(Path(os.path.normcase(os.fspath(fs.anchor_for(path, cwd=real)))), Path(os.path.normcase(os.fspath(alias))))

    def test_anchor_for_a_path_outside_the_working_folder_is_its_folder(self):
        """tương-đương: a path that is not below the working folder by any spelling is anchored at the folder that holds it."""
        (self.tmp / "a").mkdir()
        (self.tmp / "b").mkdir()
        path = self.tmp / "b" / "x.md"
        self.assertEqual(fs.anchor_for(path, cwd=self.tmp / "a"), path.parent)


class FolderLinkAtOutputNameTests(Round2Case):
    def test_a_link_to_a_folder_at_the_output_name_is_refused(self):
        """bắt-lỗi (POSIX symlink; a junction on Windows): the name is a link to a folder: UnsafeOpen, the folder is untouched and keeps its link."""
        ext = self.tmp / "ext"
        ext.mkdir()
        link = self.tmp / "out.json"
        _links.dir_link(ext, link)
        with self.assertRaises(fs.UnsafeOpen):
            fs.write_replace(link, b"X", anchor=self.tmp)
        self.assertEqual(os.listdir(ext), [])
        self.assertTrue(fs.is_link(link))


if __name__ == "__main__":
    unittest.main()
