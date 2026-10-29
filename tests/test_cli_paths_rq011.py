"""SPR-02 TK8 (RQ-011, FR8.2): the error and refusal paths of the commands, run in this process so that coverage sees them.

`check`/`validate`/`audit`, `new`, `package` and `install` are called through `engine.main(argv)`; each test checks the exit code (SPEC mục 7)
and the message that tells the user what to do. Label: độ-phủ = guards a path no other test reached in-process (a regression there
turns a clear refusal into a crash or a silent success).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

engine, const, fs, scaffold = E.engine, E.const, E.fs, E.scaffold
SKILL = "---\nname: %s\ndescription: Checks a toy example. Use when testing the command line paths.\n---\n\n# Title\n\nShort body.\n"


def cli(*argv):
    """(exit code, stdout, stderr) of `studio.py <argv>` run in this process."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = engine.main(list(argv))
        except SystemExit as exc:  # argparse
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        E.clear_caches()
        self.addCleanup(E.clear_caches)

    def skill(self, name="toy-skill", parent=None) -> Path:
        folder = (parent or self.tmp) / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(SKILL % name, encoding="utf-8")
        return folder


class CheckCliTests(TmpCase):
    def test_check_text_json_and_audit_on_a_skill_folder(self):
        """độ-phủ: `check` prints findings and exits 0 for a clean skill; --json adds type 'skill'; `audit` adds its read-only notice."""
        folder = self.skill()
        code, out, err = cli("check", str(folder))
        self.assertEqual((code, err), (0, ""))
        code, out, _ = cli("check", str(folder), "--json")
        data = json.loads(out)
        self.assertEqual((code, data["audit"], [r["type"] for r in data["reports"]]), (0, False, ["skill"]))
        code, out, _ = cli("audit", str(folder))
        self.assertEqual(code, 0)
        self.assertIn("AUDIT IS READ-ONLY", out)

    def test_check_exits_1_for_a_skill_with_an_error_and_2_without_a_target(self):
        """độ-phủ: an ERROR finding gives exit 1; no path and no --all gives exit 2 with the instruction."""
        folder = self.skill("bad-skill")
        (folder / "SKILL.md").write_text("no frontmatter at all\n", encoding="utf-8")
        self.assertEqual(cli("check", str(folder))[0], 1)
        code, _out, err = cli("check")
        self.assertEqual(code, 2)
        self.assertIn("provide a skill path or --all", err)

    def test_check_all_with_the_repo_skills_and_without_a_repo(self):
        """độ-phủ: `validate --all` walks the repo's skills; with no repository found --all is refused with exit 2."""
        code, out, _ = cli("validate", "--all", "--json")
        self.assertIn(code, (0, 1))
        self.assertTrue(json.loads(out)["reports"])
        with mock.patch.object(fs, "repo_root", return_value=None):
            code, _out, err = cli("validate", "--all")
        self.assertEqual(code, 2)
        self.assertIn("--all requires Studio repository", err)

    def test_check_names_the_reason_when_a_file_is_not_a_skill_document(self):
        """độ-phủ: plain files, links, placeholders, big and non-UTF-8 files are refused with exit 2 and a reason (rules files and workflows are checked since SPR-04 TK8)."""
        untyped = self.tmp / "note.md"
        untyped.write_text("---\ntitle: x\n---\n\nbody\n", encoding="utf-8")
        text = self.tmp / "note.txt"
        text.write_text("x", encoding="utf-8")
        binary = self.tmp / "bin.md"
        binary.write_bytes(b"\xff\xfe\x00\x80 not utf-8")
        for path, expected in ((untyped, "cannot tell the document type"), (text, "cannot tell the document type"),
                               (binary, "cannot be read as UTF-8")):
            code, _out, err = cli("check", str(path))
            self.assertEqual(code, 2, path.name)
            self.assertIn(expected, err, path.name)
        with mock.patch.object(fs, "is_link", return_value=True):
            code, _out, err = cli("check", str(untyped))
        self.assertEqual(code, 2)
        self.assertIn("symlink or junction", err)
        with mock.patch.object(fs, "path_is_cloud", return_value=True):
            code, _out, err = cli("check", str(untyped))
        self.assertEqual(code, 2)
        self.assertIn("cloud placeholder", err)
        with mock.patch.object(const, "DOCTOR_MAX_FILE_BYTES", 5):
            code, _out, err = cli("check", str(untyped))
        self.assertEqual(code, 2)
        self.assertIn("is larger than 5 bytes", err)

    def test_check_skill_md_path_means_its_folder(self):
        """độ-phủ: `check <folder>/SKILL.md` checks the folder."""
        folder = self.skill()
        code, out, _ = cli("check", str(folder / "SKILL.md"), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(Path(json.loads(out)["reports"][0]["skill"]), folder)


class NewCliTests(TmpCase):
    def new(self, *extra, name="toy-skill", desc="Does a toy thing. Use when testing."):
        return cli("new", name, "--description", desc, "--output", str(self.tmp / "out"), "--eval-root", str(self.tmp / "ev"), *extra)

    def test_new_refuses_bad_names_descriptions_and_existing_targets(self):
        """độ-phủ: a name that is not kebab-case or holds a reserved word, a missing/long/multi-line description exit 2; an existing target exits 1."""
        code, _o, err = self.new(name="Bad_Name")
        self.assertEqual(code, 2)
        self.assertIn("kebab-case", err)
        code, _o, err = self.new(name="my-claude-helper")
        self.assertEqual(code, 2)
        self.assertIn("reserved word 'claude'", err)
        for bad in ("", "x" * 1025, "two\nlines"):
            code, _o, err = self.new(desc=bad)
            self.assertEqual(code, 2, repr(bad[:10]))
            self.assertIn("--description is required", err)
        self.assertEqual(self.new()[0], 0)
        code, _o, err = self.new()
        self.assertEqual(code, 1)
        self.assertIn("refusing to overwrite", err)

    def test_new_creates_the_skill_and_a_draft_eval_suite_and_reports_a_missing_template(self):
        """độ-phủ: a good call writes SKILL.md with the given name and description plus the draft evals; a missing bundled template exits 2."""
        code, out, _ = self.new()
        self.assertEqual(code, 0)
        text = (self.tmp / "out" / "toy-skill" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: toy-skill", text)
        self.assertTrue((self.tmp / "ev" / "toy-skill" / "cases.json").is_file())
        with mock.patch.object(scaffold, "get_template", return_value=self.tmp / "nowhere"):
            code, _o, err = self.new(name="other-skill")
        self.assertEqual(code, 2)
        self.assertIn("bundled template missing", err)

    def test_user_skill_root_by_agent(self):
        """độ-phủ: the per-user skill folder of antigravity and codex; claude has none and says to use --workspace."""
        with mock.patch.object(Path, "home", return_value=self.tmp):
            self.assertEqual(scaffold.user_skill_root("antigravity"), self.tmp / ".gemini" / "config" / "skills")
            self.assertEqual(scaffold.user_skill_root("codex"), self.tmp / ".agents" / "skills")
        with self.assertRaises(ValueError) as ctx:
            scaffold.user_skill_root("claude")
        self.assertIn("use --workspace", str(ctx.exception))


class PackageInstallCliTests(TmpCase):
    def test_package_refuses_a_missing_folder_a_secret_and_an_existing_zip(self):
        """độ-phủ: package exits 2 for a missing folder, 1 (Package blocked) for a secret-named file, 1 for an existing ZIP without --force."""
        out_dir = self.tmp / "dist"
        self.assertEqual(cli("package", str(self.tmp / "nope"), "--out", str(out_dir))[0], 2)
        folder = self.skill()
        (folder / "auth.json").write_text("{}", encoding="utf-8")
        code, _o, err = cli("package", str(folder), "--out", str(out_dir))
        self.assertEqual(code, 1)
        self.assertIn("Package blocked", err)
        (folder / "auth.json").unlink()
        self.assertEqual(cli("package", str(folder), "--out", str(out_dir))[0], 0)
        code, _o, err = cli("package", str(folder), "--out", str(out_dir))
        self.assertEqual(code, 1)
        self.assertIn("package exists", err)
        self.assertEqual(cli("package", str(folder), "--out", str(out_dir), "--force")[0], 0)
        with zipfile.ZipFile(out_dir / "toy-skill.zip") as zf:
            self.assertEqual(zf.namelist(), ["toy-skill/SKILL.md"])

    def test_package_blocks_a_hardcoded_token_and_an_unreadable_candidate(self):
        """độ-phủ: a token-shaped string in a reference blocks the package (SEC); a .pem file is refused by name."""
        folder = self.skill()
        (folder / "references").mkdir()
        (folder / "references" / "notes.md").write_text("token " + "ghp_" + "a" * 36 + "\n", encoding="utf-8")
        code, out, err = cli("package", str(folder), "--out", str(self.tmp / "d1"))
        self.assertEqual(code, 1)
        self.assertIn("possible hardcoded secret", out + err)
        (folder / "references" / "notes.md").write_text("fine\n", encoding="utf-8")
        (folder / "key.pem").write_text("x", encoding="utf-8")
        code, out, err = cli("package", str(folder), "--out", str(self.tmp / "d2"))
        self.assertEqual(code, 1)
        self.assertIn("secret/credential-like file", out + err)

    def test_install_refusals_and_a_good_install(self):
        """độ-phủ: install exits 2 for a missing folder or workspace, 1 when the target exists (until --force, which keeps a backup), 1 for self-overwrite."""
        folder = self.skill()
        work = self.tmp / "work"
        work.mkdir()
        self.assertEqual(cli("install", str(self.tmp / "nope"), "--agent", "claude", "--workspace", str(work))[0], 2)
        code, _o, err = cli("install", str(folder), "--agent", "claude", "--workspace", str(self.tmp / "nowork"))
        self.assertEqual(code, 2)
        self.assertIn("workspace directory not found", err)
        code, out, _ = cli("install", str(folder), "--agent", "claude", "--workspace", str(work))
        self.assertEqual(code, 0)
        self.assertIn("Installed toy-skill for claude", out)
        installed = work / ".claude" / "skills" / "toy-skill"
        self.assertTrue((installed / "SKILL.md").is_file())
        code, _o, err = cli("install", str(folder), "--agent", "claude", "--workspace", str(work))
        self.assertEqual(code, 1)
        self.assertIn("Use --force only if you intend replacement", err)
        code, out, _ = cli("install", str(folder), "--agent", "claude", "--workspace", str(work), "--force")
        self.assertEqual(code, 0)
        self.assertIn("Existing installation backed up to", out)
        backups = list((work / ".claude" / ".skill-studio-backups").iterdir())
        self.assertEqual(len(backups), 1)
        code, _o, err = cli("install", str(installed), "--agent", "claude", "--workspace", str(work))
        self.assertEqual(code, 1)
        self.assertIn("refusing self-overwrite", err)

    def test_install_user_scope(self):
        """độ-phủ: --user is refused for claude (2), refused when the agent's config folder is missing (2, nothing created), and works when it exists."""
        folder = self.skill()
        home = self.tmp / "home"
        home.mkdir()
        with mock.patch.object(Path, "home", return_value=home):
            code, _o, err = cli("install", str(folder), "--agent", "claude", "--user")
            self.assertEqual(code, 2)
            self.assertIn("use --workspace", err)
            code, _o, err = cli("install", str(folder), "--agent", "antigravity", "--user")
            self.assertEqual(code, 2)
            self.assertIn("nothing was created", err)
            self.assertFalse((home / ".gemini").exists())
            (home / ".gemini" / "config").mkdir(parents=True)
            code, out, _ = cli("install", str(folder), "--agent", "antigravity", "--user")
        self.assertEqual(code, 0)
        self.assertTrue((home / ".gemini" / "config" / "skills" / "toy-skill" / "SKILL.md").is_file())

    def test_install_refuses_a_destination_that_is_a_link(self):
        """độ-phủ: a destination that is a link (by the engine's own test) is refused with exit 1 before anything is written."""
        folder = self.skill()
        work = self.tmp / "work"
        (work / ".claude" / "skills" / "toy-skill").mkdir(parents=True)
        real = fs.is_link
        dest = work / ".claude" / "skills" / "toy-skill"
        with mock.patch.object(fs, "is_link", side_effect=lambda p: Path(p) == dest or real(p)):
            code, _o, err = cli("install", str(folder), "--agent", "claude", "--workspace", str(work))
        self.assertEqual(code, 1)
        self.assertIn("symlink destination refused", err)

    def skill(self, name="toy-skill"):
        folder = self.tmp / "src" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(SKILL % name, encoding="utf-8")
        return folder


if __name__ == "__main__":
    unittest.main()
