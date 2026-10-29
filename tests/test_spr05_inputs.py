"""SPR-05 TK6 (FR5.1, FR5.2, FR7.1, FR9.1, SC1): input files that are links, cloud checks before resolve, `.claude-plugin` as a link, no printed link target.

CQ1 (answered): `--roots-file`, `--baseline` and a `check` path that is a link, or lies under a folder link below the working folder, are refused
BEFORE `resolve()` can touch what they lead to. A link ABOVE the working folder is still accepted (FR2.2). Labels: bắt-lỗi = red on a695479 by
assertion; tương-đương = green before and after (guard, recorded in PROGRESS as «đóng trước sprint»).

Run: python -X utf8 -m unittest tests.test_spr05_inputs -v
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
roots_mod = E.roots
SKILL = "---\nname: %s\ndescription: %s Use when testing the input files.\n---\n\n# Title\n\nShort body.\n"


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


@contextlib.contextmanager
def resolve_spy():
    """Record every `Path.resolve()` call (the text of the path it was called on); the real resolve still runs."""
    seen = []
    real = Path.resolve

    def spy(self, *a, **k):
        seen.append(os.path.normcase(os.fspath(self)))
        return real(self, *a, **k)

    with mock.patch.object(Path, "resolve", spy):
        yield seen


class InputCase(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05in_"))  # not resolved: macOS /var is a link above the working folder
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_skill(self, base: Path, name: str = "alpha") -> Path:
        folder = base / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(SKILL % (name, "Checks a toy."), encoding="utf-8")
        return folder

    def make_baseline(self) -> Path:
        """A real doctor report (a valid --baseline) written outside the working folder."""
        skills = self.tmp / "skills"
        self.make_skill(skills)
        out = self.tmp / "made-baseline.json"
        code, _, err = run_cli("doctor", "--roots", skills, "--json", "--out", out, cwd=self.tmp)
        self.assertEqual(code, 0, err)
        return out


class InputLinkTests(InputCase):
    def test_baseline_symlink_to_a_file_is_refused_before_resolve(self):
        """bắt-lỗi: FR5.1 a --baseline that is a symlink to a plain file is refused («is a link»); the target is not resolved, not read."""
        work, outside = self.tmp / "work", self.tmp / "outside"
        work.mkdir()
        outside.mkdir()
        shutil.copyfile(self.make_baseline(), outside / "ibase.json")
        _links.make_symlink(outside / "ibase.json", work / "ibase.json")
        with resolve_spy() as seen:
            code, out, err = run_cli("doctor", "--roots", self.tmp / "skills", "--baseline", "ibase.json", "--fail-on", "new", cwd=work)
        self.assertEqual(code, 2, out + err)
        self.assertIn("is a link (or under a folder link); not read", err)
        self.assertEqual([p for p in seen if p.endswith("ibase.json")], [], "the baseline was resolved")

    def test_baseline_under_a_folder_link_is_refused_before_resolve(self):
        """bắt-lỗi: FR5.1 a --baseline below a folder link (junction) under the working folder is refused; nothing behind the link is resolved or read."""
        work, outside = self.tmp / "work", self.tmp / "outside"
        work.mkdir()
        outside.mkdir()
        shutil.copyfile(self.make_baseline(), outside / "ibase.json")
        _links.dir_link(outside, work / "lnk")
        with resolve_spy() as seen:
            code, out, err = run_cli("doctor", "--roots", self.tmp / "skills", "--baseline", "lnk/ibase.json", "--fail-on", "new", cwd=work)
        self.assertEqual(code, 2, out + err)
        self.assertIn("is a link (or under a folder link); not read", err)
        self.assertEqual([p for p in seen if p.endswith("ibase.json")], [], "the baseline was resolved")

    def test_roots_file_under_a_folder_link_is_refused_before_resolve(self):
        """bắt-lỗi: FR5.1 a --roots-file below a folder link under the working folder is refused with the link message, before any resolve of it."""
        work, outside = self.tmp / "work", self.tmp / "outside"
        work.mkdir()
        outside.mkdir()
        skills = self.tmp / "skills"
        self.make_skill(skills)
        (outside / "iroots.txt").write_text(os.fspath(skills) + "\n", encoding="utf-8")
        _links.dir_link(outside, work / "lnk")
        with resolve_spy() as seen:
            code, out, err = run_cli("doctor", "--roots-file", "lnk/iroots.txt", cwd=work)
        self.assertEqual(code, 2, out + err)
        self.assertIn("is a link (or under a folder link); not read", err)
        self.assertEqual([p for p in seen if p.endswith("iroots.txt")], [], "the roots file was resolved")

    def test_a_plain_input_file_is_still_accepted(self):
        """tương-đương: FR5.1 a --baseline that is a plain file below the working folder, no link anywhere under it, is read as before."""
        work = self.tmp / "work"
        work.mkdir()
        shutil.copyfile(self.make_baseline(), work / "ibase.json")
        code, out, err = run_cli("doctor", "--roots", self.tmp / "skills", "--baseline", "ibase.json", "--fail-on", "new", cwd=work)
        self.assertEqual(code, 0, out + err)

    def test_a_link_above_the_working_folder_is_still_accepted(self):
        """tương-đương: FR2.2 / CQ1 the working folder itself reached through a link spelling (macOS /tmp, a OneDrive folder) does not make the input a link."""
        real = self.tmp / "real"
        real.mkdir()
        shutil.copyfile(self.make_baseline(), real / "ibase.json")
        _links.dir_link(real, self.tmp / "above")
        code, out, err = run_cli("doctor", "--roots", self.tmp / "skills", "--baseline", "ibase.json", "--fail-on", "new", cwd=self.tmp / "above")
        self.assertEqual(code, 0, out + err)

    def test_check_path_behind_a_folder_link_is_refused(self):
        """tương-đương: FR5.1 `check` already refuses a document below a folder link under the working folder before it is resolved (resolve_check_path); kept as the guard."""
        work, outside = self.tmp / "work", self.tmp / "outside"
        work.mkdir()
        outside.mkdir()
        (outside / "doc.md").write_text("---\ntype: workflow\n---\n\n# T\n", encoding="utf-8")
        _links.dir_link(outside, work / "lnk")
        with resolve_spy() as seen:
            code, out, err = run_cli("check", "lnk/doc.md", cwd=work)
        self.assertEqual(code, 2, out + err)
        self.assertIn("link", err)
        self.assertEqual([p for p in seen if p.endswith("doc.md")], [])


class CloudBeforeResolveTests(InputCase):
    def test_plain_file_cloud_attribute_is_judged_before_resolve(self):
        """bắt-lỗi: FR5.2 (RF-R4) `_plain_file_problem` asks `path_is_cloud` before `resolve()` can touch the file: a placeholder is `cloud`, never resolved."""
        folder = self.tmp / "plugin"
        (folder / ".claude-plugin").mkdir(parents=True)
        manifest = folder / ".claude-plugin" / "plugin.json"
        manifest.write_text('{"name": "x"}', encoding="utf-8")
        with mock.patch.object(fs, "path_is_cloud", lambda path: Path(path) == manifest), resolve_spy() as seen:
            with self.assertRaises(roots_mod.RootError) as caught:
                roots_mod._read_json(manifest, 4096, (), folder)
        self.assertEqual(caught.exception.reason, "cloud")
        self.assertEqual([p for p in seen if p.endswith("plugin.json")], [], "the placeholder was resolved")

    def test_input_file_cloud_attribute_is_judged_before_resolve(self):
        """tương-đương: FR5.2 `input_file_problem` already asks `path_is_cloud` before `resolve()`; kept as the guard."""
        target = self.tmp / "ibase.json"
        target.write_text("{}", encoding="utf-8")
        with mock.patch.object(fs, "path_is_cloud", lambda path: Path(path) == target), resolve_spy() as seen:
            problem = fs.input_file_problem(target)
        self.assertEqual(problem, "is a cloud placeholder; not read")
        self.assertEqual([p for p in seen if p.endswith("ibase.json")], [])


class ManifestLinkTests(InputCase):
    def make_pack(self) -> tuple:
        root = self.tmp / "root"
        plugin = root / "packs"
        self.make_skill(plugin / "skills", "alpha")
        ext = self.tmp / "ext"
        ext.mkdir()
        (ext / "plugin.json").write_text(json.dumps({"name": "LEAK"}), encoding="utf-8")
        return root, plugin, ext

    def test_claude_plugin_junction_leaks_no_pack_name(self):
        """tương-đương: FR7.1 (chốt hồi quy, RF-P5) a `.claude-plugin` that is a junction to a folder holding plugin.json `name: LEAK` gives no pack named LEAK in `doctor --by-pack`."""
        root, plugin, ext = self.make_pack()
        _links.dir_link(ext, plugin / ".claude-plugin")
        code, out, err = run_cli("doctor", "--roots", root, "--by-pack", "--json", cwd=self.tmp)
        self.assertIn(code, (0, 1), out + err)
        self.assertNotIn("LEAK", out + err)

    def test_pack_name_does_not_look_into_a_linked_manifest_folder(self):
        """bắt-lỗi: FR7.1 `_pack_name` treats a `.claude-plugin` link as «no manifest»: the manifest behind it is not even opened (`is_dir()` followed the link before)."""
        root, plugin, ext = self.make_pack()
        _links.dir_link(ext, plugin / ".claude-plugin")
        skill = (plugin / "skills" / "alpha").resolve()
        opened = []

        def blind(path, *a, **k):
            opened.append(os.fspath(path))
            return {"name": "LEAK"}

        with mock.patch.object(roots_mod, "_read_json", blind):
            name = E.doctor._pack_name(skill, [root.resolve()], {}, ())
        self.assertEqual(opened, [], "the manifest behind the link was opened")
        self.assertNotEqual(name, "LEAK")


class HomePathTests(InputCase):
    def test_home_path_does_not_print_the_target_of_a_junction(self):
        """bắt-lỗi: FR9.1 a spelling that reaches the home folder only through a junction stays as written: the real path behind the junction (here a `.secret` folder) is never shown."""
        module = load_catalog_module()
        home = self.tmp / "home"
        (home / ".secret" / "x").mkdir(parents=True)
        _links.dir_link(home / ".secret", self.tmp / "alias")
        with mock.patch.object(os.path, "expanduser", lambda p: str(home) if p == "~" else p):
            shown = module.home_path(str(self.tmp / "alias" / "x"))
        self.assertNotIn(".secret", shown)
        self.assertEqual(shown, (self.tmp / "alias" / "x").as_posix())


if __name__ == "__main__":
    unittest.main()
