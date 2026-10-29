"""SPR-05 TK2 (FR2.1, FR2.2, FR2.3, SC1, SC4): the folder chain from the scan root to a file is pinned while the file is opened.

A folder between the anchor and the file that is (or becomes) a link must not be read through. The «becomes» cases hide the early link checks
(`early_checks_blind`) so the swap-after-check window is what is tested: the junction is already there, the checks say «no link», and only the pinned
chain can still refuse. Labels: bắt-lỗi = red on a695479 by assertion; tương-đương = green before and after (guard); đơn-vị = touches the new API.

Run: python -X utf8 -m unittest tests.test_spr05_chain -v
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
from test_catalog import load_catalog_module  # noqa: E402

fs = E.fs
SKILL = "---\nname: %s\ndescription: %s Use when testing the pinned chain.\n---\n\n# Title\n\nShort body.\n"
LONG_REF = "line\n" * 300  # more than REF_TOC_LINES without a Contents heading: lint says ST5 when (and only when) it reads the file


@contextlib.contextmanager
def early_checks_blind(resolved_ok=None):
    """The checks that look at links before the open all say «no link»: what is left to refuse a swapped folder is the pin. `resolved_ok(child)` also
    blinds `valid_resolved_under` for the children it accepts (the export checks the resolved fixture path against the eval folder)."""
    real_under = fs.valid_resolved_under

    def under(child, parent):
        return True if resolved_ok is not None and resolved_ok(child) else real_under(child, parent)

    with mock.patch.object(fs, "is_link", lambda path: False), mock.patch.object(fs, "link_in_chain", lambda path, stop: None):
        with mock.patch.object(fs, "valid_resolved_under", under):
            yield


def run_cli(*argv, cwd=None):
    """Run `studio.py <argv>` in-process (cwd switched when given); returns (exit code, stdout, stderr)."""
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


class ChainCase(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05chain_"))  # not resolved: macOS /var is a link above the root
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def skill(self, folder: Path, name: str = None, desc: str = "A plain skill.") -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(SKILL % (name or folder.name, desc), encoding="utf-8")
        return folder

    def outside(self) -> Path:
        """A folder outside every root, holding the data a swapped link would leak."""
        ext = self.tmp / "ext"
        ext.mkdir(exist_ok=True)
        return ext


class PinChainUnitTests(ChainCase):
    def make_chain(self):
        leaf = self.tmp / "a" / "b" / "c"
        leaf.mkdir(parents=True)
        (leaf / "f.txt").write_text("x", encoding="utf-8")
        return leaf / "f.txt"

    @unittest.skipUnless(os.name == "nt", "Windows pins with a handle that has no FILE_SHARE_DELETE")
    def test_rename_pinned_folder_blocked(self):
        """đơn-vị: RF-P1 inside the pin, renaming the folder or any folder above it (down to the anchor) fails; after it, it works."""
        target = self.make_chain()
        with fs.pin_chain(self.tmp, target):
            with self.assertRaises(OSError):
                os.rename(self.tmp / "a" / "b" / "c", self.tmp / "a" / "b" / "c2")
            with self.assertRaises(OSError):
                os.rename(self.tmp / "a" / "b", self.tmp / "a" / "b2")
            with self.assertRaises(OSError):
                os.rename(self.tmp / "a", self.tmp / "a2")
        os.rename(self.tmp / "a", self.tmp / "a2")

    @unittest.skipIf(os.name == "nt", "POSIX pins with a directory fd; the swap needs a symlink")
    def test_posix_swap_inside_pin_stays_put(self):
        """đơn-vị: RF-P2 a folder renamed inside the pin and a symlink put in its place: the open through dir_fd still reads the original folder."""
        target = self.make_chain()
        decoy = self.tmp / "decoy"
        decoy.mkdir()
        (decoy / "f.txt").write_text("DECOY", encoding="utf-8")
        with fs.pin_chain(self.tmp, target) as pin:
            os.rename(self.tmp / "a" / "b" / "c", self.tmp / "a" / "b" / "c_moved")
            _links.make_symlink(decoy, self.tmp / "a" / "b" / "c", is_dir=True)
            fd = os.open("f.txt", os.O_RDONLY, dir_fd=pin.dir_fd)
            try:
                self.assertEqual(os.read(fd, 10), b"x")
            finally:
                os.close(fd)

    def test_pins_released_on_error(self):
        """đơn-vị: FR2.3 an exception inside the with still closes every handle: the folders can be removed at once (Windows keeps a held folder)."""
        target = self.make_chain()
        with self.assertRaises(RuntimeError):
            with fs.pin_chain(self.tmp, target):
                raise RuntimeError("boom")
        shutil.rmtree(self.tmp / "a")
        self.assertFalse((self.tmp / "a").exists())

    def test_pin_refuses_a_link_in_the_middle(self):
        """đơn-vị: FR2.1 a junction between the anchor and the file is UnsafeOpen, and nothing stays pinned."""
        ext = self.outside()
        (ext / "f.txt").write_text("SECRET", encoding="utf-8")
        (self.tmp / "a").mkdir()
        _links.dir_link(ext, self.tmp / "a" / "b")
        with self.assertRaises(fs.UnsafeOpen):
            with fs.pin_chain(self.tmp, self.tmp / "a" / "b" / "f.txt"):
                self.fail("pinned through a link")
        shutil.rmtree(self.tmp / "a")

    def test_pin_outside_anchor_is_value_error(self):
        """đơn-vị: a path that is not below the anchor, by spelling, is a ValueError (a caller bug), not a silent pin of something else."""
        with self.assertRaises(ValueError):
            with fs.pin_chain(self.tmp / "a", self.tmp / "b" / "f.txt"):
                pass

    def test_dotdot_and_short_name_components(self):
        """đơn-vị: review focus 1 `..` is folded by spelling (abspath) before the walk; a path that leaves the anchor by `..` is a ValueError, and an 8.3-looking name is
        a plain component, never resolved."""
        target = self.make_chain()
        sneaky = self.tmp / "a" / "b" / ".." / "b" / "c" / "f.txt"
        with fs.pin_chain(self.tmp, sneaky):
            pass
        with self.assertRaises(ValueError):
            with fs.pin_chain(self.tmp / "a", self.tmp / "a" / ".." / "x" / "f.txt"):
                pass
        (self.tmp / "SECRET~1").mkdir()
        (self.tmp / "SECRET~1" / "f.txt").write_text("x", encoding="utf-8")
        with fs.pin_chain(self.tmp, self.tmp / "SECRET~1" / "f.txt"):
            pass
        self.assertTrue(target.exists())

    def test_anchor_for_rule(self):
        """đơn-vị: the cwd when the path is below it, else the folder that holds the path (the rule resolve_check_path uses)."""
        inside = self.tmp / "x" / "y.md"
        self.assertEqual(fs.anchor_for(inside, cwd=self.tmp), Path(os.path.abspath(self.tmp)))
        elsewhere = self.tmp.parent / "other" / "y.md"
        self.assertEqual(fs.anchor_for(elsewhere, cwd=self.tmp), Path(os.path.abspath(elsewhere)).parent)


class SwapAfterCheckTests(ChainCase):
    """One test for each group of readers: the junction is there, the early checks are blind, the canary must not be read."""

    def test_a_doctor_does_not_read_a_skill_behind_a_swapped_folder(self):
        """bắt-lỗi: FR2.1 (a) a skill folder that became a junction after the scan: doctor does not report the name or the description found behind it."""
        ext = self.outside()
        self.skill(ext / "s", name="leakname", desc="LEAKDESC text.")
        root = self.tmp / "root"
        root.mkdir()
        _links.dir_link(ext / "s", root / "s")
        listing = lambda roots, *args, **kwargs: ([root.resolve() / "s"], [])  # as if the swap came after the scan (on POSIX the scan never enters a symlink)
        with early_checks_blind(), mock.patch.object(E.doctor, "iter_skill_dirs", listing):
            code, out, err = run_cli("doctor", "--roots", root, "--json", cwd=self.tmp)
        self.assertNotIn("leakname", out + err)
        self.assertNotIn("LEAKDESC", out + err)

    def test_a_catalog_does_not_read_a_skill_behind_a_swapped_folder(self):
        """bắt-lỗi: FR2.1 (a) the same for catalog: no name and no description from behind the junction."""
        ext = self.outside()
        self.skill(ext / "s", name="leakname", desc="LEAKDESC text.")
        root = self.tmp / "root"
        root.mkdir()
        _links.dir_link(ext / "s", root / "s")
        listing = lambda roots, *args, **kwargs: ([root.resolve() / "s"], [])  # as if the swap came after the scan (on POSIX the scan never enters a symlink)
        with early_checks_blind(), mock.patch.object(E.doctor, "iter_skill_dirs", listing):
            code, out, err = run_cli("catalog", "--roots", root, "--json", cwd=self.tmp)
        self.assertNotIn("leakname", out + err)
        self.assertNotIn("LEAKDESC", out + err)

    def test_a_roots_json_behind_a_swapped_folder_is_not_read(self):
        """bắt-lỗi: FR2.1 (a) a manifest read under a plugin whose `.claude-plugin` folder became a junction is refused, its JSON is not returned."""
        ext = self.outside()
        (ext / "plugin.json").write_text('{"name": "LEAK"}', encoding="utf-8")
        plugin = self.tmp / "plugin"
        plugin.mkdir()
        _links.dir_link(ext, plugin / ".claude-plugin")
        with early_checks_blind():
            try:
                value = E.roots._read_json(plugin / ".claude-plugin" / "plugin.json", 4096, E.const.CLOUD_MARKERS, plugin)
            except E.roots.RootError:
                return
        self.fail("read %r through a junction" % (value,))

    def test_a_roots_file_behind_a_link_folder_is_not_read(self):
        """bắt-lỗi: FR2.1 (a) a --roots-file below the working folder whose folder is a junction is not read (the listed root is not returned)."""
        ext = self.outside()
        wanted = self.tmp / "wanted"
        wanted.mkdir()
        (ext / "roots.txt").write_text("%s\n" % wanted, encoding="utf-8")
        work = self.tmp / "work"
        work.mkdir()
        _links.dir_link(ext, work / "link")
        before = os.getcwd()
        os.chdir(work)
        try:
            with early_checks_blind():
                try:
                    found = E.doctor.parse_roots(None, str(work / "link" / "roots.txt"), None)
                except ValueError:
                    return
        finally:
            os.chdir(before)
        self.fail("read the roots file through a junction: %r" % (found,))

    def test_b_validate_does_not_read_a_reference_behind_a_swapped_folder(self):
        """bắt-lỗi: FR2.1 (b) a `references` folder that became a junction: its file is not read (no ST5 from lint), the finding says it was refused."""
        ext = self.outside()
        (ext / "ref.md").write_text(LONG_REF, encoding="utf-8")
        skill = self.skill(self.tmp / "s")
        _links.dir_link(ext, skill / "references")
        with early_checks_blind():
            findings = E.validate.validate_skill(skill)
        self.assertNotIn("ST5", [f["code"] for f in findings], findings)

    def test_b_check_does_not_read_a_document_behind_a_link_folder(self):
        """bắt-lỗi: FR2.1 (b) `check` reads a document below the working folder through a junction: refused (read_document gives the reason, no text)."""
        ext = self.outside()
        (ext / "doc.md").write_text("---\ntype: workflow\n---\n\nLEAKTEXT\n", encoding="utf-8")
        work = self.tmp / "work"
        work.mkdir()
        _links.dir_link(ext, work / "link")
        before = os.getcwd()
        os.chdir(work)
        try:
            with early_checks_blind():
                text, why = sys.modules["studio_doctypes"].read_document(work / "link" / "doc.md")
        finally:
            os.chdir(before)
        self.assertIsNone(text)
        self.assertTrue(why)

    def test_c_package_does_not_pack_a_file_behind_a_swapped_folder(self):
        """bắt-lỗi: FR2.1 (c) a `scripts` folder that became a junction: the package is refused, no zip holds the file behind it."""
        ext = self.outside()
        (ext / "leak.py").write_text("print('LEAKBODY')\n", encoding="utf-8")
        skill = self.skill(self.tmp / "s")
        _links.dir_link(ext, skill / "scripts")
        out = self.tmp / "out"
        with early_checks_blind():
            code, _, err = run_cli("package", skill, "--out", out, cwd=self.tmp)
        zips = list(out.glob("*.zip")) if out.exists() else []
        for z in zips:
            self.assertNotIn(b"LEAKBODY", z.read_bytes())  # stored or deflated: a short text may be stored as it is
            import zipfile
            with zipfile.ZipFile(z) as archive:
                self.assertEqual([n for n in archive.namelist() if n.endswith("leak.py")], [])
        self.assertNotEqual(code, 0, "package went through a junction")

    def test_d_export_does_not_copy_a_fixture_behind_a_swapped_folder(self):
        """bắt-lỗi: FR2.1 (d) a fixture folder that became a junction after the checks: the export copies nothing from behind it."""
        ext = self.outside()
        (ext / "a.csv").write_text("LEAKROW\n", encoding="utf-8")
        eval_dir = self.tmp / "evals" / "demo-skill"
        eval_dir.mkdir(parents=True)
        (eval_dir / "rubric.md").write_text("# rubric\n", encoding="utf-8")
        _links.dir_link(ext, eval_dir / "fixtures")
        cases = [{"id": "c1", "kind": "typical", "prompt": "Audit a.csv", "should_trigger": True, "fixtures": ["fixtures/a.csv"], "expected_behaviors": ["Reads a.csv"]},
                 {"id": "c2", "kind": "edge", "prompt": "Audit a.csv twice", "should_trigger": True, "fixtures": ["fixtures/a.csv"], "expected_behaviors": ["Reads a.csv again"]},
                 {"id": "c3", "kind": "near-miss", "prompt": "Explain CALCULATE", "should_trigger": False, "fixtures": [], "expected_behaviors": ["Does not trigger"]}]
        (eval_dir / "cases.json").write_text(json.dumps({"skill_name": "demo-skill", "status": "frozen", "cases": cases}), encoding="utf-8")
        out = self.tmp / "out"
        with early_checks_blind(resolved_ok=lambda child: Path(child).name == "a.csv"):
            E.evals.export_agentskills(eval_dir, "demo-skill", out)
        copied = list(out.rglob("a.csv")) if out.exists() else []
        self.assertEqual(copied, [], "the fixture was copied through a junction")

    def test_e_fmt_does_not_read_a_file_behind_a_swapped_folder(self):
        """bắt-lỗi: FR2.1 (e) fmt --check reads no .md file behind a folder that became a junction (it is listed unreadable)."""
        ext = self.outside()
        (ext / "doc.md").write_text("# T\n\nLEAKTEXT\n\n\n\n", encoding="utf-8")
        work = self.tmp / "work"
        work.mkdir()
        _links.dir_link(ext, work / "sub")
        reads = []
        real = fs.open_nofollow_read

        def spy(path, *args, **kwargs):
            handle = real(path, *args, **kwargs)
            reads.append(os.fspath(path))
            return handle

        with early_checks_blind(), mock.patch.object(fs, "open_nofollow_read", spy):
            run_cli("fmt", "--check", work, cwd=self.tmp)
        self.assertEqual([p for p in reads if p.endswith("doc.md")], [], "fmt opened a file through a junction")


class AnchorRulesTests(ChainCase):
    def test_link_above_anchor_allowed(self):
        """tương-đương: FR2.2 (chốt hồi quy, green on a695479) a link ABOVE the scan root is accepted: validate, doctor and catalog run through it as before."""
        real = self.tmp / "real"
        self.skill(real / "root" / "s", desc="A plain skill.")
        _links.dir_link(real, self.tmp / "via")
        root = self.tmp / "via" / "root"
        code, out, err = run_cli("doctor", "--roots", root, "--json", cwd=self.tmp)
        self.assertIn(code, (0, 1), err)
        self.assertEqual(json.loads(out)["totals"]["skills"], 1)
        code, out, err = run_cli("validate", root / "s", cwd=self.tmp)
        self.assertEqual(code, 0, out + err)
        code, out, err = run_cli("catalog", "--roots", root, "--json", cwd=self.tmp)
        self.assertEqual(code, 0, out + err)

    def test_pins_are_released_after_each_command(self):
        """tương-đương: FR2.3 (guard: green on a695479, red if the new pins leak) right after validate, catalog and doctor, every folder of the chain can be renamed (no handle is held)."""
        root = self.tmp / "root"
        self.skill(root / "grp" / "s")
        for argv in (("validate", root / "grp" / "s"), ("catalog", "--roots", root, "--json"), ("doctor", "--roots", root, "--json")):
            run_cli(*argv, cwd=self.tmp)
            os.rename(root / "grp", root / "grp2")
            os.rename(root / "grp2", root / "grp")
            os.rename(root, self.tmp / "root2")
            os.rename(self.tmp / "root2", root)


if __name__ == "__main__":
    unittest.main()
