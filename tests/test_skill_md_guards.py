"""SPR-03 TK8 (RQ-021, RQ-022; FR10.1, FR11.1): two holes where `SKILL.md` was reached without asking whether it may be.

(a) `check`/`validate`/`audit` on a folder whose `SKILL.md` lies in a cloud or secret zone must refuse before opening it and must not print its `name`.
(b) `skill_dirs` must not list a skill whose `SKILL.md` is a symlink or junction, and must not stat what it points at.
The engine is started as a subprocess, as a user does; the symlink tests create a real link and skip where the machine cannot (Windows
without the privilege, WinError 1314; CI Ubuntu runs them).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

SECRET_NAME = "secret-name"
SKILL_TEXT = "---\nname: %s\ndescription: Checks a toy example. Use when testing the SKILL.md guards.\n---\n\n# Title\n\nShort body.\n"


def run_engine(*args):
    proc = subprocess.run([sys.executable, "-X", "utf8", str(E.ENGINE_PATH)] + list(args), cwd=str(E.ROOT), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", timeout=300)
    return proc.returncode, proc.stdout, proc.stderr


def write_skill(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_TEXT % name, encoding="utf-8")
    return folder


def symlink_or_skip(test: unittest.TestCase, link: Path, target: Path, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:  # Windows without the privilege: WinError 1314
        test.skipTest("cannot create a symlink here: %s" % exc)


class CloudSkillMdNotReadTests(unittest.TestCase):
    def test_check_dir_cloud_skill_md_not_read(self):
        """A folder under a cloud-named parent: no command prints the SKILL.md name, each exits non-zero with a reason."""
        with tempfile.TemporaryDirectory() as t:
            folder = write_skill(Path(t) / "OneDriveFake" / "sk", SECRET_NAME)
            for command in ("check", "validate", "audit"):
                for extra in ([], ["--json"]):
                    with self.subTest(command=command, extra=extra):
                        code, out, err = run_engine(command, str(folder), *extra)
                        self.assertNotEqual(0, code)
                        self.assertNotIn(SECRET_NAME, out + err)
                        self.assertIn("INPUT", out)

    def test_validate_skill_does_not_open_the_manifest_in_a_zone(self):
        """The refusal comes before `read_capped`: the manifest is not opened, and the finding is one ERROR with code INPUT."""
        with tempfile.TemporaryDirectory() as t:
            folder = write_skill(Path(t) / "SharePointFake" / "sk", SECRET_NAME)
            with mock.patch.object(E.fs, "read_capped", side_effect=AssertionError("SKILL.md was read")):
                findings = E.validate.validate_skill(folder)
            self.assertEqual([("ERROR", "INPUT")], [(f["level"], f["code"]) for f in findings])
            self.assertNotIn(SECRET_NAME, repr(findings))

    def test_a_zone_folder_is_not_resolved(self):
        """The spelling given is checked before `Path.resolve`: a folder in a zone is never resolved (so never followed or stat-ed)."""
        with tempfile.TemporaryDirectory() as t:
            folder = write_skill(Path(t) / "OneDriveFake" / "sk", SECRET_NAME)
            with mock.patch.object(Path, "resolve", side_effect=AssertionError("resolve was called")):
                findings = E.validate.validate_skill(folder)
            self.assertEqual([("ERROR", "INPUT")], [(f["level"], f["code"]) for f in findings])

    def test_a_link_manifest_is_refused_not_opened(self):
        """`is_link` says SKILL.md is a link: one ERROR INPUT, `read_capped` never called (open() would follow the link)."""
        with tempfile.TemporaryDirectory() as t:
            folder = write_skill(Path(t) / "plain" / "sk", SECRET_NAME)
            real_is_link = E.fs.is_link
            with mock.patch.object(E.fs, "is_link", lambda p: Path(p).name == "SKILL.md" or real_is_link(p)), \
                    mock.patch.object(E.fs, "read_capped", side_effect=AssertionError("SKILL.md was read")):
                findings = E.validate.validate_skill(folder)
            self.assertEqual([("ERROR", "INPUT")], [(f["level"], f["code"]) for f in findings])
            self.assertIn("symlink or junction", findings[0]["message"])
            self.assertNotIn(SECRET_NAME, repr(findings))

    def test_a_symlinked_skill_md_is_refused(self):
        """A real symlink SKILL.md -> file outside: `check` exits non-zero with INPUT and does not print the target's name."""
        with tempfile.TemporaryDirectory() as t:
            outside = Path(t) / "outside.md"
            outside.write_text(SKILL_TEXT % SECRET_NAME, encoding="utf-8")
            folder = Path(t) / "plain" / "sk"
            folder.mkdir(parents=True)
            symlink_or_skip(self, folder / "SKILL.md", outside)
            code, out, err = run_engine("check", str(folder))
            self.assertNotEqual(0, code)
            self.assertIn("INPUT", out)
            self.assertNotIn(SECRET_NAME, out + err)

    def test_a_folder_that_resolves_into_a_zone_is_refused(self):
        """The spelling given is clean but the real path is in a zone (a link to it): refused all the same."""
        with tempfile.TemporaryDirectory() as t:
            real = write_skill(Path(t) / "OneDriveFake" / "sk", SECRET_NAME)
            alias = Path(t) / "clean"
            symlink_or_skip(self, alias, real, directory=True)
            code, out, err = run_engine("check", str(alias))
            self.assertNotEqual(0, code)
            self.assertNotIn(SECRET_NAME, out + err)

    def test_a_clean_folder_is_still_checked(self):
        """Guard: outside any zone the same folder is read as before (the name mismatch is reported)."""
        with tempfile.TemporaryDirectory() as t:
            folder = write_skill(Path(t) / "plain" / "sk", SECRET_NAME)
            code, out, _err = run_engine("check", str(folder))
            self.assertEqual(1, code)
            self.assertIn("FM2", out)
            self.assertNotIn("INPUT", out)


class SkillDirsSymlinkedManifestTests(unittest.TestCase):
    def test_skill_dirs_skips_symlinked_skill_md(self):
        """A skills/<x>/SKILL.md that is a symlink to a file outside is not listed; a real one beside it is."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "repo"
            write_skill(root / "skills" / "good", "good")
            outside = Path(t) / "outside.md"
            outside.write_text(SKILL_TEXT % "linked", encoding="utf-8")
            (root / "skills" / "linked").mkdir()
            symlink_or_skip(self, root / "skills" / "linked" / "SKILL.md", outside)
            self.assertEqual(["good"], [p.name for p in E.fs.skill_dirs(root)])

    def test_skill_dirs_does_not_stat_through_a_link_manifest(self):
        """With `is_link` saying the manifest is a link, nothing asks `os.stat` about it (lstat only) and the folder is not listed."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "repo"
            write_skill(root / "skills" / "good", "good")
            write_skill(root / "skills" / "linked", "linked")
            manifest = os.path.normcase(str(root / "skills" / "linked" / "SKILL.md"))
            real_is_link = E.fs.is_link
            stat_calls = []
            real_stat = os.stat

            def spy(path, *args, **kwargs):
                stat_calls.append(os.path.normcase(os.fspath(path)))
                return real_stat(path, *args, **kwargs)

            with mock.patch.object(E.fs, "is_link", lambda p: os.path.normcase(os.fspath(p)) == manifest or real_is_link(p)), \
                    mock.patch.object(os, "stat", spy):
                found = E.fs.skill_dirs(root)
            self.assertEqual(["good"], [p.name for p in found])
            self.assertNotIn(manifest, stat_calls)

    def test_skill_dirs_skips_a_manifest_that_is_a_folder(self):
        """A `SKILL.md` that is a directory is not a skill manifest."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "repo"
            write_skill(root / "skills" / "good", "good")
            (root / "skills" / "odd" / "SKILL.md").mkdir(parents=True)
            self.assertEqual(["good"], [p.name for p in E.fs.skill_dirs(root)])


    def test_skill_dirs_skips_a_manifest_that_cannot_be_probed(self):
        """An OSError while asking about the manifest drops that folder, not the listing."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "repo"
            write_skill(root / "skills" / "good", "good")
            write_skill(root / "skills" / "bad", "bad")
            bad = os.path.normcase(str(root / "skills" / "bad" / "SKILL.md"))
            real_lexists = os.path.lexists

            def lexists(path):
                if os.path.normcase(os.fspath(path)) == bad:
                    raise PermissionError("denied")
                return real_lexists(path)

            with mock.patch.object(os.path, "lexists", lexists):
                self.assertEqual(["good"], [p.name for p in E.fs.skill_dirs(root)])


if __name__ == "__main__":
    unittest.main()
