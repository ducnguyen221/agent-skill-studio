"""SPR-05 TK3 (FR3.1, FR2.1, SC1): create a file without following a link and without leaving an empty file at a link's target; `new` writes under the pinned folder.

The early `lexists` check of `create_exclusive` is what hides the window, so the tests blind it (`os.path.lexists` says «nothing there») and ask what the
create itself does with a name that is a link. Labels: bắt-lỗi = red on a695479 by assertion; tương-đương = green before and after; đơn-vị = new API.

Run: python -X utf8 -m unittest tests.test_spr05_create -v
"""
from __future__ import annotations

import contextlib
import io
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


def run_new(*argv, cwd=None):
    out, err = io.StringIO(), io.StringIO()
    before, code = os.getcwd(), 0
    try:
        if cwd is not None:
            os.chdir(cwd)
        with mock.patch.dict(os.environ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = E.engine.main(["new", *[str(x) for x in argv]])
            except SystemExit as exc:
                code = exc.code
    finally:
        os.chdir(before)
    return code, out.getvalue(), err.getvalue()


class CreateCase(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05create_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class CreateExclusiveTests(CreateCase):
    def test_dangling_symlink_leaves_no_empty_file(self):
        """bắt-lỗi: FR3.1 a dangling symlink at the name (planted after the early check): the create is refused and no file appears at its target."""
        goal = self.tmp / "goal.txt"
        link = self.tmp / "dangling.txt"
        _links.make_symlink(goal, link)
        with mock.patch("os.path.lexists", lambda p: False):
            with self.assertRaises(FileExistsError):
                fs.create_exclusive(link)
        self.assertFalse(os.path.exists(goal))

    def test_junction_name_refused(self):
        """bắt-lỗi: FR3.1 a junction at the name (planted after the early check) is refused as «already there» (FileExistsError), whatever the OS says first, and it stays empty."""
        ext = self.tmp / "ext"
        ext.mkdir()
        link = self.tmp / "junc"
        _links.dir_link(ext, link)
        with mock.patch("os.path.lexists", lambda p: False):
            try:
                fs.create_exclusive(link)
            except FileExistsError:
                pass
            except OSError as exc:
                self.fail("expected FileExistsError, got %s: %s" % (type(exc).__name__, exc))
            else:
                self.fail("created a file over a junction")
        self.assertEqual(os.listdir(ext), [])

    def test_existing_file_is_kept(self):
        """tương-đương: a plain file at the name is FileExistsError and its bytes are untouched."""
        path = self.tmp / "a.txt"
        path.write_bytes(b"KEEP")
        with self.assertRaises(FileExistsError):
            fs.create_exclusive(path)
        self.assertEqual(path.read_bytes(), b"KEEP")

    def test_creates_a_new_file(self):
        """tương-đương: a free name gives a writable binary file; the bytes are on disk after the with block."""
        path = self.tmp / "new.txt"
        with fs.create_exclusive(path) as handle:
            handle.write("tiếng Việt\n".encode("utf-8"))
        self.assertEqual(path.read_bytes(), "tiếng Việt\n".encode("utf-8"))

    def test_creates_under_a_pinned_anchor(self):
        """đơn-vị: with an anchor the file is made inside the pinned chain; the chain is released when the file is closed (the folders can be renamed)."""
        (self.tmp / "a" / "b").mkdir(parents=True)
        path = self.tmp / "a" / "b" / "new.txt"
        with fs.create_exclusive(path, anchor=self.tmp) as handle:
            handle.write(b"x")
        self.assertEqual(path.read_bytes(), b"x")
        os.rename(self.tmp / "a", self.tmp / "a2")

    def test_junction_in_the_chain_creates_nothing(self):
        """đơn-vị: FR2.1 a junction between the anchor and the new file is UnsafeOpen and the folder behind it stays empty."""
        ext = self.tmp / "ext"
        ext.mkdir()
        (self.tmp / "a").mkdir()
        _links.dir_link(ext, self.tmp / "a" / "b")
        with self.assertRaises(fs.UnsafeOpen):
            fs.create_exclusive(self.tmp / "a" / "b" / "new.txt", anchor=self.tmp)
        self.assertEqual(os.listdir(ext), [])


class NewCommandTests(CreateCase):
    def test_new_parent_swapped_to_junction(self):
        """bắt-lỗi: FR2.1 `new`: the skill folder is swapped for a junction right after it is made (and the early link check is blind): SKILL.md is not written behind it."""
        ext = self.tmp / "ext"
        ext.mkdir()
        output = self.tmp / "out" / "skills"
        real_mkdir = Path.mkdir

        def swapping_mkdir(self_path, *args, **kwargs):
            real_mkdir(self_path, *args, **kwargs)
            if self_path.name == "swapme":
                os.rmdir(self_path)
                _links.dir_link(ext, self_path)

        with mock.patch.object(Path, "mkdir", swapping_mkdir), mock.patch.object(E.scaffold, "link_in_chain", lambda p, stop: None):
            code, out, err = run_new("swapme", "--description", "A plain skill. Use when testing.", "--output", output, cwd=self.tmp)
        self.assertNotEqual(code, 0, out + err)
        self.assertEqual(os.listdir(ext), [], "SKILL.md was written through the swapped folder")
        self.assertIn("cannot write", err)

    def test_new_still_creates_a_skill(self):
        """tương-đương: `new` without any link makes SKILL.md with the name and description filled in, and the eval draft."""
        output = self.tmp / "out" / "skills"
        code, out, err = run_new("fresh-one", "--description", "A plain skill. Use when testing.", "--output", output, cwd=self.tmp)
        self.assertEqual(code, 0, out + err)
        text = (output / "fresh-one" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: fresh-one", text)
        self.assertIn('description: "A plain skill. Use when testing."', text)
        self.assertTrue((self.tmp / "out" / "evals" / "fresh-one" / "cases.json").is_file())


if __name__ == "__main__":
    unittest.main()
