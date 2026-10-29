"""SPR-05 lane A, review round 3 (re-review of 50ba891): RF-A9 (Chặn), RF-A10, RF-A12.

RF-A9: the working folder reached through a link spelling must be found at the SHALLOWEST ancestor that is the same folder; a link below it, even one that
points back at the working folder, is a folder below the anchor and stays checked. RF-A10: every tree hash is taken under the scan root and the hash cache
keeps the anchor in its key. RF-A12: no `ctypes` on Python 3.9 is a refusal (UnsafeOpen), not a traceback.

Run: python -X utf8 -m unittest tests.test_spr05_round3 -v
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
SKILL = "---\nname: s\ndescription: A plain skill. Use when testing the review round.\n---\n\n# Title\n\nShort body.\n"


class Round3Case(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05r3_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class ShallowestAnchorTests(Round3Case):
    def test_a_link_below_the_working_folder_that_points_back_at_it_is_not_the_anchor(self):
        """bắt-lỗi: RF-A9 `var` is a link to the working folder (macOS /var -> /private/var) and `var/lnk` a link back to it: the anchor is `var`, the shallowest
        spelling, so `lnk` is checked; swapping `lnk` for another folder after the anchor was chosen is refused, not read."""
        private = self.tmp / "private_var"
        private.mkdir()
        var = self.tmp / "var"
        _links.dir_link(private, var)
        _links.dir_link(private, private / "lnk")
        path = var / "lnk" / "doc.md"
        anchor = fs.anchor_for(path, cwd=private)
        self.assertEqual(os.path.normcase(os.fspath(anchor)), os.path.normcase(os.fspath(var)))
        ext = self.tmp / "ext"
        ext.mkdir()
        (ext / "doc.md").write_text("OUTSIDE-SECRET", encoding="utf-8")
        os.rmdir(private / "lnk")
        _links.dir_link(ext, private / "lnk")  # the swap, after the anchor was chosen
        with self.assertRaises(fs.UnsafeOpen):
            fs.read_capped(path, None, anchor=anchor)


class TreeHashAnchorTests(Round3Case):
    def make_pair(self):
        """root/a/s and a second identical copy that is reached through root/mid, a link to a folder outside the root."""
        ext = self.tmp / "ext"
        (ext / "s").mkdir(parents=True)
        (ext / "s" / "SKILL.md").write_text(SKILL, encoding="utf-8")
        root = self.tmp / "root"
        (root / "a" / "s").mkdir(parents=True)
        (root / "a" / "s" / "SKILL.md").write_text(SKILL, encoding="utf-8")
        _links.dir_link(ext, root / "mid")
        return root

    def blind(self):
        return mock.patch.object(fs, "is_link", lambda path: False)

    def test_same_content_hashes_under_the_anchor_each_item_carries(self):
        """bắt-lỗi: RF-A10 two identical trees, one of them behind a link between the root and the skill: with the scan root as the anchor of each item it cannot be hashed, so they are not «the same»."""
        root = self.make_pair()
        cat = load_catalog_module()
        a = {"path": os.fspath(root / "a" / "s"), "anchor": os.fspath(root)}
        b = {"path": os.fspath(root / "mid" / "s"), "anchor": os.fspath(root)}
        with self.blind():
            self.assertEqual(cat.same_content(a, b, cache=cat.TreeCache()), (False, None))

    def test_the_hash_cache_keeps_the_anchor_in_its_key(self):
        """bắt-lỗi: RF-A10 the digest of one folder asked first without the scan root and then with it is taken again: the answer under the root (refused: None) is not the cached one."""
        root = self.make_pair()
        cat = load_catalog_module()
        cache = cat.TreeCache()
        path = root / "mid" / "s"
        with self.blind():
            self.assertIsNotNone(cache.sha(path, root / "mid"))  # anchored at its own parent: the folder is below it, nothing to refuse
            self.assertIsNone(cache.sha(path, root))
            self.assertIsNone(cache.semantic(path, root))

    def test_overlap_hash_uses_the_item_anchor(self):
        """bắt-lỗi: RF-A10 curator_overlap's own hash of an item takes the item's anchor."""
        root = self.make_pair()
        cat = load_catalog_module()
        item = {"path": os.fspath(root / "mid" / "s"), "anchor": os.fspath(root)}
        with self.blind():
            self.assertIsNone(cat.curator_overlap._sha(item, E.const.CLOUD_MARKERS))


@unittest.skipUnless(os.name == "nt", "the ctypes branch is the Windows one")
class NoCtypesTests(Round3Case):
    def test_missing_ctypes_on_python_39_is_a_refusal(self):
        """bắt-lỗi: RF-A12 Python 3.9 without ctypes: UnsafeOpen («safe open unavailable»), not an ImportError traceback."""
        path = self.tmp / "a.md"
        path.write_text("x\n", encoding="utf-8")
        with mock.patch.object(fs.sys, "version_info", (3, 9, 0, "final", 0)), mock.patch.dict(sys.modules, {"ctypes": None, "ctypes.wintypes": None}):
            with self.assertRaises(fs.UnsafeOpen) as caught:
                fs.read_capped(path, 100)
        self.assertIn("safe open unavailable", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
