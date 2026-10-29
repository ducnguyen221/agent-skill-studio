"""SPR-05 lane A, review round 1 (RF-A1 … RF-A5, RF-A8): the holes the security review found after TK5.

RF-A1 `fmt --fix` writes under the pinned chain; RF-A2 `catalog` pins from the scan root; RF-A3 one pin from the temp file to the rename;
RF-A4 the eval export puts all its files in place or none; RF-A5 an anchor that is itself a link is accepted (the folders below it are not);
RF-A8 `new --full` and `install` create their files under the pin. Labels: bắt-lỗi = red on 69f14c8 by assertion; đơn-vị = new API or a unit.

Run: python -X utf8 -m unittest tests.test_spr05_round1 -v
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
SKILL = "---\nname: %s\ndescription: %s Use when testing the review round.\n---\n\n# Title\n\nShort body.\n"
DIRTY = "# Title\n\nText   with trailing spaces   \n\n\n\n"


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


@contextlib.contextmanager
def early_checks_blind():
    with mock.patch.object(fs, "is_link", lambda path: False), mock.patch.object(fs, "link_in_chain", lambda path, stop: None):
        yield


class RoundCase(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05round_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class FmtFixPinTests(RoundCase):
    def swap_after_read(self, work: Path, victim: Path):
        """`fmt_text` runs after the file is read and before it is written: there the folder `work/sub` is swapped for a junction to `victim`."""
        real, state = E.fmt.fmt_text, {"swapped": False}

        def wrapper(*args, **kwargs):
            if not state["swapped"]:
                state["swapped"] = True
                os.rename(work / "sub", work / "sub_real")
                _links.dir_link(victim, work / "sub")
            return real(*args, **kwargs)

        return wrapper, state

    def setup_tree(self):
        work, victim = self.tmp / "work", self.tmp / "victim"
        (work / "sub").mkdir(parents=True)
        (work / "sub" / "doc.md").write_bytes(DIRTY.encode("utf-8"))
        victim.mkdir()
        (victim / "doc.md").write_bytes(b"VICTIM\n")
        return work, victim

    def test_fmt_fix_does_not_write_through_a_swapped_folder(self):
        """bắt-lỗi: RF-A1 `fmt --fix` (with and without the backup) after the folder is swapped for a junction: the file behind it is unchanged and nothing is added there."""
        for extra in (("--no-backup",), ()):
            with self.subTest(extra=extra):
                shutil.rmtree(self.tmp / "work", True)
                shutil.rmtree(self.tmp / "victim", True)
                work, victim = self.setup_tree()
                wrapper, state = self.swap_after_read(work, victim)
                with mock.patch.object(E.fmt, "fmt_text", wrapper):
                    run_cli("fmt", "--fix", *extra, work, cwd=self.tmp)
                self.assertTrue(state["swapped"], "the swap hook never ran")
                self.assertEqual((victim / "doc.md").read_bytes(), b"VICTIM\n")
                self.assertEqual(os.listdir(victim), ["doc.md"])
                if os.path.islink(work / "sub"):
                    os.unlink(work / "sub")  # a POSIX symlink: drop it before the cleanup walks the tree
                elif os.path.lexists(work / "sub") and fs.is_link(work / "sub"):
                    os.rmdir(work / "sub")  # a Windows junction

    def test_fmt_fix_still_fixes_and_backs_up(self):
        """tương-đương: with no swap the file is fixed, a backup is made, and no temp file stays."""
        work, _ = self.setup_tree()
        code, out, err = run_cli("fmt", "--fix", work, cwd=self.tmp)
        self.assertNotEqual((work / "sub" / "doc.md").read_bytes(), DIRTY.encode("utf-8"), out + err)
        names = sorted(p.name for p in (work / "sub").iterdir())
        self.assertEqual(len(names), 2, names)
        self.assertTrue(any(".bak-" in n for n in names))
        self.assertFalse(any(n.endswith("tmp") for n in names))


class CatalogRootAnchorTests(RoundCase):
    def test_catalog_does_not_read_a_skill_behind_a_swapped_middle_folder(self):
        """bắt-lỗi: RF-A2 a folder BETWEEN the scan root and the skill became a junction: catalog reads neither its name and description nor its tree."""
        ext = self.tmp / "ext"
        (ext / "s").mkdir(parents=True)
        (ext / "s" / "SKILL.md").write_text(SKILL % ("leakname", "LEAKDESC text."), encoding="utf-8")
        root = self.tmp / "root"
        root.mkdir()
        _links.dir_link(ext, root / "mid")
        listing = lambda roots, *args, **kwargs: ([root.resolve() / "mid" / "s"], [])  # as if the swap came after the scan (on POSIX the scan never enters a symlink)
        with early_checks_blind(), mock.patch.object(E.doctor, "iter_skill_dirs", listing):
            code, out, err = run_cli("catalog", "--roots", root, "--json", cwd=self.tmp)
        self.assertNotIn("leakname", out + err)
        self.assertNotIn("LEAKDESC", out + err)
        for row in json.loads(out)["skills"]:
            self.assertIsNone(row["tree_sha256"], row)

    def test_tree_digest_takes_the_scan_root(self):
        """đơn-vị: RF-A2 tree_sha256 with an anchor above the skill refuses a junction between them (None), not a hash of what is behind it."""
        ext = self.tmp / "ext"
        (ext / "s").mkdir(parents=True)
        (ext / "s" / "SKILL.md").write_text(SKILL % ("s", "A plain skill."), encoding="utf-8")
        root = self.tmp / "root"
        root.mkdir()
        _links.dir_link(ext, root / "mid")
        with early_checks_blind():
            self.assertIsNone(E.roots.tree_sha256(root / "mid" / "s", anchor=root))


class SinglePinTests(RoundCase):
    def test_replace_with_pins_the_chain_once(self):
        """bắt-lỗi: RF-A3 creating the temp file and renaming it over the target happen under ONE pin."""
        (self.tmp / "a").mkdir()
        calls = []
        real = fs.pin_chain

        def counting(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        with mock.patch.object(fs, "pin_chain", counting):
            fs.write_replace(self.tmp / "a" / "x.json", b"{}", anchor=self.tmp)
        self.assertEqual(len(calls), 1)

    def test_commit_refuses_a_temp_file_that_is_not_the_one_written(self):
        """bắt-lỗi: RF-A3 a file put at the temp name in its place is not renamed over the target (identity of the temp file is checked), and the target is unchanged."""
        target = self.tmp / "out.json"
        target.write_bytes(b"OLD")
        staged = fs.stage_write(target, lambda handle: handle.write(b"NEW"), anchor=self.tmp)
        os.rename(staged.tmp, staged.tmp.with_name(staged.tmp.name + ".kept"))  # the original keeps its inode: a deleted file's number can be handed to the next one
        staged.tmp.write_bytes(b"FOREIGN")
        with self.assertRaises(fs.UnsafeOpen):
            staged.commit()
        self.assertEqual(target.read_bytes(), b"OLD")

    def test_refused_commit_in_replace_with_leaves_no_temp(self):
        """tương-đương: RF-A3 (already true on 69f14c8: discard) a target that became a folder is refused and the temp file made for it is removed."""
        target = self.tmp / "out.json"
        real_refuse = fs._refuse_folder_target
        calls = []

        def second_time_refuses(path, dir_fd):
            calls.append(1)
            if len(calls) >= 2:
                raise fs.UnsafeOpen("output is a folder or a folder link: %s" % path)
            return real_refuse(path, dir_fd)

        with mock.patch.object(fs, "_refuse_folder_target", second_time_refuses):
            with self.assertRaises(fs.UnsafeOpen):
                fs.write_replace(target, b"X", anchor=self.tmp)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), [])


class ExportCommitTests(RoundCase):
    def make_eval(self, fixture: bytes) -> Path:
        folder = self.tmp / "evals" / "demo-skill"
        (folder / "fixtures").mkdir(parents=True, exist_ok=True)
        (folder / "rubric.md").write_text("# rubric\n", encoding="utf-8")
        (folder / "fixtures" / "a.csv").write_bytes(fixture)
        (folder / "fixtures" / "b.csv").write_bytes(fixture)
        cases = [
            {"id": "c1", "kind": "typical", "prompt": "Audit a.csv", "should_trigger": True, "fixtures": ["fixtures/a.csv", "fixtures/b.csv"], "expected_behaviors": ["Reads a.csv"]},
            {"id": "c2", "kind": "edge", "prompt": "Audit b.csv", "should_trigger": True, "fixtures": ["fixtures/b.csv"], "expected_behaviors": ["Reads b.csv"]},
            {"id": "c3", "kind": "near-miss", "prompt": "Explain CALCULATE", "should_trigger": False, "fixtures": [], "expected_behaviors": ["Does not trigger"]},
        ]
        (folder / "cases.json").write_text(json.dumps({"skill_name": "demo-skill", "status": "frozen", "cases": cases}), encoding="utf-8")
        return folder

    def tree(self, folder: Path) -> dict:
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}

    def test_export_force_commit_failure_restores_every_file(self):
        """bắt-lỗi: RF-A4 the second fixture cannot be put in place: the first one is back to its old bytes too, the old evals.json stays, and no temp or aside file is left."""
        folder = self.make_eval(b"id\n1\n")
        out_root = self.tmp / "export"
        self.assertEqual(E.evals.export_agentskills(folder, "demo-skill", out_root)[0], 0)
        before = self.tree(out_root / "demo-skill")
        self.make_eval(b"id\n2\n")
        real = os.replace

        def failing(src, dst, *args, **kwargs):
            if os.path.basename(os.fspath(dst)) == "b.csv" and os.fspath(src).endswith(".spr05tmp"):
                raise OSError("target is open elsewhere")
            return real(src, dst, *args, **kwargs)

        with mock.patch("os.replace", failing):
            code, findings, _ = E.evals.export_agentskills(folder, "demo-skill", out_root, force=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.tree(out_root / "demo-skill"), before)

    def test_export_force_good_run_replaces_everything(self):
        """tương-đương: a good --force export has the new fixtures and evals.json, and nothing else in the folder."""
        folder = self.make_eval(b"id\n1\n")
        out_root = self.tmp / "export"
        E.evals.export_agentskills(folder, "demo-skill", out_root)
        self.make_eval(b"id\n2\n")
        self.assertEqual(E.evals.export_agentskills(folder, "demo-skill", out_root, force=True)[0], 0)
        files = self.tree(out_root / "demo-skill")
        self.assertEqual(sorted(files), ["evals/evals.json", "evals/files/a.csv", "evals/files/b.csv"])
        self.assertEqual(files["evals/files/a.csv"], b"id\n2\n")


class LinkedAnchorTests(RoundCase):
    def test_an_anchor_that_is_a_link_is_accepted(self):
        """bắt-lỗi: RF-A5 the user entered through a link (a junction as the anchor): reads and writes below it work; a link BELOW the anchor is still refused."""
        real = self.tmp / "real"
        (real / "sub").mkdir(parents=True)
        (real / "sub" / "a.md").write_text("hello\n", encoding="utf-8")
        entry = self.tmp / "entry"
        _links.dir_link(real, entry)
        self.assertEqual(fs.read_capped(entry / "sub" / "a.md", None, anchor=entry), ("hello\n", False))
        fs.write_replace(entry / "sub" / "out.json", b"{}", anchor=entry)
        self.assertEqual((real / "sub" / "out.json").read_bytes(), b"{}")
        ext = self.tmp / "ext"
        ext.mkdir()
        (ext / "b.md").write_text("SECRET", encoding="utf-8")
        _links.dir_link(ext, real / "inner")
        with self.assertRaises(fs.UnsafeOpen):
            fs.read_capped(entry / "inner" / "b.md", None, anchor=entry)


class ScaffoldAndInstallPinTests(RoundCase):
    def swapping_mkdir(self, ext: Path, leaf: str):
        real_mkdir, state = Path.mkdir, {"done": False}

        def mkdir(self_path, *args, **kwargs):
            real_mkdir(self_path, *args, **kwargs)
            if self_path.name == leaf and not state["done"]:
                state["done"] = True
                os.rmdir(self_path)
                _links.dir_link(ext, self_path)

        real_makedirs = os.makedirs

        def makedirs(name, *args, **kwargs):  # shutil.copytree makes its folders with os.makedirs
            real_makedirs(name, *args, **kwargs)
            if Path(name).name == leaf and not state["done"]:
                state["done"] = True
                os.rmdir(name)
                _links.dir_link(ext, name)

        return mkdir, makedirs

    def test_new_full_does_not_copy_the_template_through_a_swapped_folder(self):
        """bắt-lỗi: RF-A8 `new --full`: a template folder (`references`) that became a junction right after it was made receives no file."""
        ext = self.tmp / "ext"
        ext.mkdir()
        output = self.tmp / "out" / "skills"
        mkdir, makedirs = self.swapping_mkdir(ext, "references")
        with mock.patch.object(Path, "mkdir", mkdir), mock.patch("os.makedirs", makedirs), mock.patch.object(fs, "link_in_chain", lambda p, stop: None):
            code, out, err = run_cli("new", "swapfull", "--full", "--description", "A plain skill. Use when testing.", "--output", output, cwd=self.tmp)
        self.assertEqual(os.listdir(ext), [], out + err)

    def test_install_does_not_copy_through_a_swapped_folder(self):
        """bắt-lỗi: RF-A8 `install`: a folder of the new copy that became a junction after it was made receives no file."""
        ext = self.tmp / "ext"
        ext.mkdir()
        src = self.tmp / "src" / "demo-skill"
        (src / "references").mkdir(parents=True)
        (src / "SKILL.md").write_text(SKILL % ("demo-skill", "A plain skill."), encoding="utf-8")
        (src / "references" / "guide.md").write_text("# Guide\n\ntext\n", encoding="utf-8")
        workspace = self.tmp / "ws"
        workspace.mkdir()
        mkdir, makedirs = self.swapping_mkdir(ext, "references")
        with mock.patch.object(Path, "mkdir", mkdir), mock.patch("os.makedirs", makedirs), mock.patch.object(fs, "link_in_chain", lambda p, stop: None):
            code, out, err = run_cli("install", src, "--agent", "claude", "--workspace", workspace, cwd=self.tmp)
        self.assertEqual(os.listdir(ext), [], out + err)


if __name__ == "__main__":
    unittest.main()
