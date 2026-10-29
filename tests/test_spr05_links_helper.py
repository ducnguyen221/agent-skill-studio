"""SPR-05 TK0: the link fixtures of the SPR-05 tests (`tests/_links.py`).

A unit test of the test helper. `STUDIO_REQUIRE_SYMLINK=1` (set on the CI runners) turns the «this machine cannot make a symlink» skip into a failure,
so a runner that cannot make symlinks cannot pass the symlink cases by skipping them (SC2).

Run: python -X utf8 -m unittest tests.test_spr05_links_helper -v
"""
from __future__ import annotations

import errno
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


def _denied() -> OSError:
    """The error `os.symlink` gives an account without the symlink privilege."""
    return OSError(None, "denied", None, 1314) if os.name == "nt" else OSError(errno.EPERM, "denied")


class LinksHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05links_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "target").mkdir()
        (self.tmp / "target" / "f.txt").write_text("x", encoding="utf-8")

    def test_dir_link_is_link(self):
        """dir_link makes a folder link that the engine's is_link sees, and the target is reachable through it."""
        link = self.tmp / "dl"
        _links.dir_link(self.tmp / "target", link)
        self.assertTrue(E.fs.is_link(link))
        self.assertTrue((link / "f.txt").is_file())

    def test_junction_is_link_on_windows_and_symlink_elsewhere(self):
        link = self.tmp / "junc"
        _links.make_junction(self.tmp / "target", link)
        self.assertTrue(E.fs.is_link(link))

    def test_hardlink_has_two_names(self):
        link = self.tmp / "hl.txt"
        _links.make_hardlink(self.tmp / "target" / "f.txt", link)
        self.assertEqual(os.lstat(link).st_nlink, 2)

    def test_real_symlink_is_link(self):
        """A real symlink (skipped here without the privilege; with STUDIO_REQUIRE_SYMLINK=1 it fails on a machine that cannot make one)."""
        link = self.tmp / "sl.txt"
        _links.make_symlink(self.tmp / "target" / "f.txt", link)
        self.assertTrue(E.fs.is_link(link))

    def test_symlink_skips_when_privilege_is_missing(self):
        """Without STUDIO_REQUIRE_SYMLINK a denied symlink is a skip with the reason symlink-privilege."""
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch("os.symlink", side_effect=_denied()):
            os.environ.pop("STUDIO_REQUIRE_SYMLINK", None)
            with self.assertRaises(unittest.SkipTest) as caught:
                _links.make_symlink(self.tmp / "target" / "f.txt", self.tmp / "sl")
        self.assertIn("symlink-privilege", str(caught.exception))

    def test_require_symlink_env_fails_instead_of_skip(self):
        """With STUDIO_REQUIRE_SYMLINK=1 the same denial is a failure, not a skip (a runner that cannot link must not pass by skipping)."""
        with mock.patch.dict(os.environ, {"STUDIO_REQUIRE_SYMLINK": "1"}), mock.patch("os.symlink", side_effect=_denied()):
            with self.assertRaises(AssertionError) as caught:
                _links.make_symlink(self.tmp / "target" / "f.txt", self.tmp / "sl")
        self.assertIn("symlink required on this runner", str(caught.exception))

    def test_other_symlink_errors_are_not_swallowed(self):
        """A failure that is not a missing privilege (a missing parent folder) is raised as it is."""
        with self.assertRaises(OSError):
            _links.make_symlink(self.tmp / "target", self.tmp / "nofolder" / "sl", is_dir=True)


if __name__ == "__main__":
    unittest.main()
