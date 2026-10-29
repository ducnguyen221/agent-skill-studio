"""SPR-05, review round 1 of the whole sprint: SC5 (pin once per folder while a skill is hashed), RF-S1 (a path outside the anchor is refused, not pinned
weakly) and RF-U4 (the `--md` output has the same guarantees as `--out`).

Labels: bắt-lỗi = red on a71cda8 by assertion; tương-đương = green before and after (the code path is shared with `--out`, the test closes the gap in SC1).

Run: python -X utf8 -m unittest tests.test_spr05_round4 -v
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
roots_mod = E.roots
SKILL = "---\nname: %s\ndescription: A plain skill. Use when testing the review round.\n---\n\n# Title\n\nShort body.\n"


def run_cli(*argv, cwd=None):
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


class Round4Case(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05r4_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class PinOncePerFolderTests(Round4Case):
    def make_skill(self) -> tuple:
        root = self.tmp / "root"
        skill = root / "s"
        for sub in ("", "references", "scripts"):
            (skill / sub).mkdir(parents=True, exist_ok=True)
            for i in range(4):
                (skill / sub / ("f%d.md" % i)).write_text("text %s %d\n" % (sub, i), encoding="utf-8")
        (skill / "SKILL.md").write_text(SKILL % "s", encoding="utf-8")
        return root, skill

    @contextlib.contextmanager
    def counting_pins(self):
        """Count every folder the chain pin opens (the Windows handle or the POSIX descriptor)."""
        name = "_pin_component_windows" if os.name == "nt" else "_pin_component"
        opened = []
        real = getattr(fs, name)

        def counted(*a, **k):
            opened.append(a[0])
            return real(*a, **k)

        with mock.patch.object(fs, name, counted):
            yield opened

    def test_a_tree_hash_pins_each_folder_once(self):
        """bắt-lỗi: SC5 hashing a skill of 13 files in 3 folders pins each distinct folder of the chains once (anchor, skill, references, scripts = 4), not once per file."""
        root, skill = self.make_skill()
        for semantic in (False, True):
            with self.subTest(semantic=semantic):
                with self.counting_pins() as opened:
                    digest = roots_mod._tree_digest(skill, (), semantic, root)
                self.assertIsNotNone(digest)
                self.assertEqual(len(opened), 4, opened)

    def test_the_digest_is_the_same_with_and_without_the_session(self):
        """tương-đương: SC5 pinning once changes no byte of the result: the digest equals the one taken file by file."""
        root, skill = self.make_skill()
        shared = roots_mod._tree_digest(skill, (), False, root)
        with mock.patch.object(fs, "pin_session", contextlib.nullcontext):
            single = roots_mod._tree_digest(skill, (), False, root)
        self.assertEqual(shared, single)

    def test_the_pins_are_released_when_the_digest_is_done(self):
        """tương-đương: FR2.3 after the hash returns, the folders are not held: the skill folder can be renamed and removed at once (a held handle refuses on Windows)."""
        root, skill = self.make_skill()
        roots_mod._tree_digest(skill, (), False, root)
        moved = root / "moved"
        os.rename(skill, moved)
        shutil.rmtree(moved)

    def test_the_pins_are_released_after_an_error_in_the_walk(self):
        """tương-đương: FR2.3 a hash that stops with an exception does not leave folders held: the tree can be removed after it."""
        root, skill = self.make_skill()
        with mock.patch.object(roots_mod, "_file_sha256", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                roots_mod._tree_digest(skill, (), False, root)
        shutil.rmtree(root)

    def test_a_folder_swapped_for_a_link_before_the_first_pin_is_still_refused(self):
        """tương-đương: FR2.1 the first file of a folder is pinned from the anchor down as before: a junction in the chain makes the digest None, nothing behind it is hashed."""
        root, skill = self.make_skill()
        ext = self.tmp / "ext"
        ext.mkdir()
        (ext / "leak.md").write_text("LEAK", encoding="utf-8")
        shutil.rmtree(skill / "references")
        _links.dir_link(ext, skill / "references")
        self.assertIsNone(roots_mod._tree_digest(skill, (), False, root))


class OutsideAnchorTests(Round4Case):
    def test_a_path_outside_the_anchor_by_spelling_is_refused_not_pinned_from_its_own_folder(self):
        """bắt-lỗi: RF-S1 the path is spelled through an alias of the anchor (not below it by spelling) and its folder is a junction: it is refused (UnsafeOpen), not read
        through the junction after a silent fall back to «the folder that holds it» as the anchor (which is allowed to be a link)."""
        work, ext = self.tmp / "w", self.tmp / "ext"
        work.mkdir()
        ext.mkdir()
        (ext / "b.json").write_text("OUTSIDE-SECRET", encoding="utf-8")
        _links.dir_link(ext, work / "junc")
        _links.dir_link(work, self.tmp / "alias")
        path = self.tmp / "alias" / "junc" / "b.json"
        with self.assertRaises(fs.UnsafeOpen):
            fs.read_capped(path, 100, anchor=work)
        with self.assertRaises(fs.UnsafeOpen):
            fs.open_nofollow_read(path, anchor=work).close()

    def test_a_path_below_the_anchor_is_still_read(self):
        """tương-đương: RF-S1 the same spelling for anchor and path reads as before."""
        work = self.tmp / "w"
        work.mkdir()
        (work / "b.json").write_text("fine", encoding="utf-8")
        self.assertEqual(fs.read_capped(work / "b.json", 100, anchor=work), ("fine", False))


class MdOutputTests(Round4Case):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "root"
        (self.root / "one").mkdir(parents=True)
        (self.root / "one" / "SKILL.md").write_text(SKILL % "one", encoding="utf-8")
        self.safe = self.tmp / "safe"
        self.safe.mkdir()

    def test_catalog_md_swapped_to_symlink_keeps_the_link_target(self):
        """tương-đương: FR4.1 `--md` that became a symlink after the check is replaced as a name: the file it pointed to is unchanged (the path is shared with `--out`)."""
        victim = self.tmp / "victim.txt"
        victim.write_text("VICTIM", encoding="utf-8")
        link = self.safe / "CATALOG.md"
        _links.make_symlink(victim, link)
        with mock.patch.object(E.doctor, "out_problem", lambda *a, **k: None):
            code, out, err = run_cli("catalog", "--roots", self.root, "--md", link, cwd=self.tmp)
        self.assertEqual(victim.read_text(encoding="utf-8"), "VICTIM", out + err)
        self.assertFalse(fs.is_link(link))
        self.assertIn("one", link.read_text(encoding="utf-8"))

    def test_failed_replace_keeps_the_old_md_and_leaves_no_temp(self):
        """tương-đương: FR4.1 a failing rename leaves the old `--md` file byte for byte and no *.spr05tmp."""
        target = self.safe / "CATALOG.md"
        target.write_text("# old\n", encoding="utf-8")
        with mock.patch("os.replace", side_effect=OSError("disk gone")):
            code, out, err = run_cli("catalog", "--roots", self.root, "--md", target, cwd=self.tmp)
        self.assertEqual(code, 2, out + err)
        self.assertIn("ERROR", err)
        self.assertEqual(target.read_text(encoding="utf-8"), "# old\n")
        self.assertEqual([p.name for p in self.safe.iterdir() if p.name.endswith(".spr05tmp")], [])

    def test_home_option_guards_its_harness_folders_for_md(self):
        """tương-đương: FR8.1 with `--home H` a `--md` under H/.claude, H/.codex or H/.gemini is refused like `--out`."""
        home = self.tmp / "home"
        for name in (".claude", ".codex", ".gemini"):
            (home / name).mkdir(parents=True)
            with self.subTest(name):
                target = home / name / "x.md"
                code, out, err = run_cli("catalog", "--roots", self.root, "--home", home, "--installed", "claude", "--md", target, cwd=self.tmp)
                self.assertEqual(code, 2, out + err)
                self.assertIn("harness folder", err)
                self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
