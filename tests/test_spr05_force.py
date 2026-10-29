"""SPR-05 TK5 (FR4.2, SC1): `--force` replaces the previous copy only after the new one is written; a failure in between leaves the previous copy as it was.

The write is made to fail with a patch on the function the command really uses (RF-P7): `shutil.copyfileobj` for install and the eval export, `zipfile.ZipFile.writestr` for
package; it raises on the second file. Labels: bắt-lỗi = red on a695479 by assertion; tương-đương = green before and after (guard).

Run: python -X utf8 -m unittest tests.test_spr05_force -v
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
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

fs = E.fs
SKILL = "---\nname: demo-skill\ndescription: A plain skill. Use when testing the force restore.\n---\n\n# Title\n\n%s\n"


def run_cli(*argv, cwd=None):
    out, err = io.StringIO(), io.StringIO()
    before, code = os.getcwd(), 0
    try:
        if cwd is not None:
            os.chdir(cwd)
        with mock.patch.dict(os.environ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = E.engine.main([str(x) for x in argv])
            except SystemExit as exc:
                code = exc.code
    finally:
        os.chdir(before)
    return code, out.getvalue(), err.getvalue()


def second_call_fails(real):
    """A replacement for `real` that works the first time and raises OSError the second (and later) times."""
    calls = []

    def wrapper(*args, **kwargs):
        calls.append(1)
        if len(calls) >= 2:
            raise OSError("disk full")
        return real(*args, **kwargs)

    return wrapper


def tree_bytes(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


class ForceCase(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05force_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_skill(self, body: str) -> Path:
        folder = self.tmp / "src" / "demo-skill"
        (folder / "references").mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(SKILL % body, encoding="utf-8")
        (folder / "references" / "guide.md").write_text("# Guide\n\n%s\n" % body, encoding="utf-8")
        return folder


class InstallForceTests(ForceCase):
    def test_install_force_restores_the_previous_skill_when_copying_fails(self):
        """bắt-lỗi: FR4.2 `install --force` whose copy fails on the second file: the installed Skill is the previous one, byte for byte, the message says so, no backup is left."""
        workspace = self.tmp / "ws"
        workspace.mkdir()
        folder = self.make_skill("first version")
        code, out, err = run_cli("install", folder, "--agent", "claude", "--workspace", workspace, cwd=self.tmp)
        self.assertEqual(code, 0, out + err)
        dest = workspace / ".claude" / "skills" / "demo-skill"
        before = tree_bytes(dest)
        self.make_skill("second version")
        with mock.patch("shutil.copyfileobj", second_call_fails(shutil.copyfileobj)):
            code, out, err = run_cli("install", folder, "--agent", "claude", "--workspace", workspace, "--force", cwd=self.tmp)
        self.assertEqual(code, 1, out + err)
        self.assertEqual(tree_bytes(dest), before)
        self.assertIn("previous Skill was restored", err)
        backups = workspace / ".claude" / ".skill-studio-backups"
        self.assertEqual(list(backups.iterdir()) if backups.exists() else [], [])


class PackageForceTests(ForceCase):
    def test_package_force_keeps_the_old_zip_when_writing_fails(self):
        """bắt-lỗi: FR4.2 `package --force` whose zip write fails on the second file: the old zip is still there, byte for byte, and no temp file stays."""
        folder = self.make_skill("first version")
        out_dir = self.tmp / "out"
        code, out, err = run_cli("package", folder, "--out", out_dir, cwd=self.tmp)
        self.assertEqual(code, 0, out + err)
        target = out_dir / "demo-skill.zip"
        old = target.read_bytes()
        self.make_skill("second version")
        with mock.patch.object(zipfile.ZipFile, "writestr", second_call_fails(zipfile.ZipFile.writestr)):
            code, out, err = run_cli("package", folder, "--out", out_dir, "--force", cwd=self.tmp)
        self.assertNotEqual(code, 0, out + err)
        self.assertEqual(target.read_bytes(), old)
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()), ["demo-skill.zip"])

    def test_package_force_replaces_the_zip_when_it_works(self):
        """tương-đương: a good `package --force` replaces the zip with the new content."""
        folder = self.make_skill("first version")
        out_dir = self.tmp / "out"
        run_cli("package", folder, "--out", out_dir, cwd=self.tmp)
        self.make_skill("second version")
        code, out, err = run_cli("package", folder, "--out", out_dir, "--force", cwd=self.tmp)
        self.assertEqual(code, 0, out + err)
        with zipfile.ZipFile(out_dir / "demo-skill.zip") as archive:
            self.assertIn(b"second version", archive.read("demo-skill/SKILL.md"))
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()), ["demo-skill.zip"])


class ExportForceTests(ForceCase):
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

    def test_export_force_keeps_the_old_fixture_when_copying_fails(self):
        """bắt-lỗi: FR4.2 `--export agentskills --force` whose copy fails on the second fixture: the exported fixtures that were there are as they were (the old one is not deleted first)."""
        folder = self.make_eval(b"id\n1\n")
        out_root = self.tmp / "export"
        code, findings, _ = E.evals.export_agentskills(folder, "demo-skill", out_root)
        self.assertEqual(code, 0, findings)
        files = out_root / "demo-skill" / "evals" / "files"
        before = tree_bytes(out_root / "demo-skill")
        self.make_eval(b"id\n2\n")
        with mock.patch("shutil.copyfileobj", second_call_fails(shutil.copyfileobj)):
            code, findings, _ = E.evals.export_agentskills(folder, "demo-skill", out_root, force=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(tree_bytes(out_root / "demo-skill"), before)
        self.assertTrue(files.is_dir())
        self.assertEqual([p.name for p in (out_root / "demo-skill" / "evals").glob(".*tmp")], [])


class FmtFixTests(ForceCase):
    def test_fmt_fix_keeps_the_file_when_the_replace_fails(self):
        """tương-đương: FR4.2 (fmt already writes a temp file and replaces: green on a695479) a failing replace leaves the file byte for byte and no temp file."""
        doc = self.tmp / "doc.md"
        original = "# Title\n\nText   with trailing spaces   \n\n\n\n"
        doc.write_text(original, encoding="utf-8", newline="")
        with mock.patch("os.replace", side_effect=OSError("disk gone")):
            code, out, err = run_cli("fmt", "--fix", "--no-backup", doc, cwd=self.tmp)
        self.assertEqual(doc.read_bytes(), original.encode("utf-8"))
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["doc.md"])


if __name__ == "__main__":
    unittest.main()
