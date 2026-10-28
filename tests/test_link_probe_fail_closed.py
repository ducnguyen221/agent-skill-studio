"""SPR-03 TK9 (RQ-025 / RF-S4, FR13.1; RF-S9, FR13.3): a path that cannot be probed is treated as a link, and the model_evaluated gate does not read an installed engine's tree.

(a) `fs.is_link` fails closed: an OSError other than "not there" (PermissionError, ENAMETOOLONG, Windows winerror 123) means "link", so the
    callers refuse or skip it with the report they already have for a link; a missing path is still "not a link".
(b) `evals --all` run from an engine under `.claude`, `.agents`, `.codex` or `.gemini` says so on stderr and reads no catalog; the exit code is the one
    of a skipped gate. The engine's own repository always runs the gate.
"""
from __future__ import annotations

import contextlib
import errno
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402
from test_catalog_gate import copy_repo, run_studio  # noqa: E402

SKIP_MESSAGE = "model_evaluated gate skipped: installed engine"


def key(path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def lstat_denied(*paths, error=PermissionError(errno.EACCES, "Permission denied")):
    """Patch `os.lstat` so that exactly `paths` raise `error`; every other path (and every file descriptor) is answered by the real call."""
    bad, real = {key(p) for p in paths}, os.lstat

    def guarded(path, *args, **kwargs):
        if not isinstance(path, int) and key(path) in bad:
            raise error
        return real(path, *args, **kwargs)

    return mock.patch.object(os, "lstat", guarded)


class IsLinkFailsClosedTests(unittest.TestCase):
    def test_is_link_fails_closed(self):
        """FR13.1: any OSError that is not «not there» means link; «not there» and «a parent is not a folder» mean not a link."""
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "x"
            winerror_123 = OSError(None, "The filename, directory name, or volume label syntax is incorrect", None, 123)
            for error in (PermissionError(errno.EACCES, "denied"), OSError(errno.ENAMETOOLONG, "too long"), OSError(errno.ELOOP, "loop"), winerror_123):
                with self.subTest(error=repr(error)), mock.patch.object(os, "lstat", side_effect=error):
                    self.assertTrue(E.fs.is_link(path))
            for error in (FileNotFoundError(errno.ENOENT, "gone"), NotADirectoryError(errno.ENOTDIR, "not a folder")):
                with self.subTest(error=repr(error)), mock.patch.object(os, "lstat", side_effect=error):
                    self.assertFalse(E.fs.is_link(path))

    def test_is_link_missing_and_plain_paths_are_not_links(self):
        """FR13.1 (regression): a path that does not exist, a file and a folder are not links."""
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "f.txt").write_text("x", encoding="utf-8")
            self.assertFalse(E.fs.is_link(Path(t) / "absent"))
            self.assertFalse(E.fs.is_link(Path(t) / "f.txt" / "below"))
            self.assertFalse(E.fs.is_link(Path(t) / "f.txt"))
            self.assertFalse(E.fs.is_link(Path(t)))


class CallersReportUnprobeablePathTests(unittest.TestCase):
    """The callers keep the report they already have for a link; none of them goes on as if the path were an ordinary one."""

    def make_tree(self, t):
        root = Path(t) / "root"
        bad = root / "bad"
        bad.mkdir(parents=True)
        (bad / "a.md").write_text("# a\n", encoding="utf-8")
        (root / "ok").mkdir()
        (root / "ok" / "b.md").write_text("# b\n", encoding="utf-8")
        return root, bad

    def test_doctor_reports_unprobeable_path(self):
        """FR13.1: a folder under a scanned root that cannot be probed is skipped with the reason `link` (the path is named) and is not entered."""
        with tempfile.TemporaryDirectory() as t:
            root, bad = self.make_tree(t)
            root, bad = root.resolve(), bad.resolve()  # the scan spells its paths long (no 8.3 names)
            (bad / "inner").mkdir()
            (bad / "inner" / "SKILL.md").write_text("---\nname: inner\ndescription: x\n---\n", encoding="utf-8")
            with lstat_denied(bad):
                skills, skipped = E.doctor.iter_skill_dirs([root])
            self.assertIn({"path": E.doctor._posix(bad), "reason": "link"}, skipped)
            self.assertEqual([], skills, "nothing below the unprobeable folder is listed")

    def test_doctor_unprobeable_root_is_not_resolved(self):
        """FR13.1: a `--roots` entry that cannot be probed is «root not found» and gets no `realpath` call of its own: as many calls as for a root
        that is simply absent (was one more: is_link False→True made parse_roots resolve it)."""
        with tempfile.TemporaryDirectory() as t:
            root, bad = self.make_tree(t)
            real_realpath = os.path.realpath

            def count_calls(path, patch):
                asked = []

                def spy(p, *a, **k):
                    asked.append(key(p))
                    return real_realpath(p, *a, **k)

                with patch, mock.patch.object(os.path, "realpath", spy):
                    with self.assertRaises(ValueError) as caught:
                        E.doctor.parse_roots(str(path), None, None)
                self.assertIn("root not found or not a directory", str(caught.exception))
                return asked.count(key(path))

            with lstat_denied(bad):
                self.assertFalse(E.doctor._real_link(bad))
            self.assertEqual(count_calls(root / "absent", contextlib.nullcontext()), count_calls(bad, lstat_denied(bad)))

    def test_doctor_real_link_root_is_still_resolved(self):
        """FR13.1 (regression): a root that is a real link keeps being judged by what it resolves to."""
        with tempfile.TemporaryDirectory() as t:
            target = Path(t) / "target"
            target.mkdir()
            link = Path(t) / "link"
            try:
                os.symlink(target, link, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest("cannot create a symlink here: %s" % exc)
            self.assertEqual([link], E.doctor.parse_roots(str(link), None, None))

    def test_fmt_reports_unprobeable_path(self):
        """FR13.1: `fmt` skips a folder that cannot be probed with the reason `link`, reads nothing in it, and still formats the rest."""
        with tempfile.TemporaryDirectory() as t:
            root, bad = self.make_tree(t)
            skipped = []
            with lstat_denied(bad):
                files = E.fmt.iter_md([root], False, None, skipped)
            self.assertIn({"path": str(bad), "reason": "link"}, skipped)
            self.assertEqual([root / "ok" / "b.md"], files)

    def test_fmt_unprobeable_start_is_skipped_as_link(self):
        """FR13.1: a path given on the command line that cannot be probed is skipped as `link`, not read."""
        with tempfile.TemporaryDirectory() as t:
            root, bad = self.make_tree(t)
            skipped = []
            with lstat_denied(bad):
                files = E.fmt.iter_md([bad], False, None, skipped)
            self.assertEqual([], files)
            self.assertTrue(any(s["reason"] == "link" for s in skipped), skipped)

    def test_package_refuses_unprobeable_skill_md(self):
        """FR13.1: `package`/`install` refuse a SKILL.md that cannot be probed with the PACK ERROR they give a link, naming the path."""
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t) / "sk"
            folder.mkdir()
            manifest = folder / "SKILL.md"
            manifest.write_text("---\nname: sk\ndescription: x\n---\n", encoding="utf-8")
            with lstat_denied(manifest):
                files, findings = E.dist.ensure_distributable(folder)
            self.assertEqual([], files)
            self.assertEqual(["PACK"], [f["code"] for f in findings])
            self.assertIn("symlink or junction", findings[0]["message"])
            self.assertIn("SKILL.md", findings[0]["path"])

    def test_install_refuses_unprobeable_destination(self):
        """FR13.1: a destination that cannot be probed ends in `symlink destination refused` naming the path and nothing is written there
        (was: `os.path.lexists` answered False for the same OSError and the install went on)."""
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "home"
            skills = home / ".agents" / "skills"
            skills.mkdir(parents=True)
            dest = skills / "data-quality-audit"
            out, err = io.StringIO(), io.StringIO()
            env = {"HOME": str(home), "USERPROFILE": str(home)}
            source = E.ROOT / "examples" / "data-quality-audit"
            with mock.patch.dict(os.environ, env), lstat_denied(dest), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = E.engine.main(["install", str(source), "--agent", "codex", "--user"])
            self.assertEqual(1, code, err.getvalue())
            self.assertIn("symlink destination refused", err.getvalue())
            self.assertIn(str(dest), err.getvalue())
            self.assertEqual([], list(skills.iterdir()), "nothing was installed")


class GateEvidenceFolderTests(unittest.TestCase):
    def test_evals_folder_that_cannot_be_probed_is_a_problem(self):
        """FR13.1: `evals/` that is a link or cannot be probed is no longer a silent «nothing more to check»: one more line in the gate's problems."""
        with tempfile.TemporaryDirectory() as t:
            repo = copy_repo(Path(t) / "repo")
            self.assertEqual([], E.evals.catalog_problems(repo))
            real_is_link = E.fs.is_link
            with mock.patch.object(E.fs, "is_link", lambda p: key(p) == key(repo / "evals") or real_is_link(p)):
                problems = E.evals.catalog_problems(repo)
            self.assertTrue(any(p.startswith("evals/ is a link or cannot be probed") for p in problems), problems)


class InstalledEngineGateTests(unittest.TestCase):
    def test_gate_skips_installed_engine(self):
        """FR13.3: an engine under `.claude` says it skips the gate on stderr, once, reads no catalog (this copy has none: a run gate would say EV20), exit 0."""
        for folder in (".claude", ".agents", ".codex", ".gemini"):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as t:
                repo = copy_repo(Path(t) / folder / "plugins" / "agent-skill-studio")
                (repo / "evals" / "catalog.json").unlink()
                code, out, err = run_studio(repo / "studio.py", "evals", "--all", "--json", cwd=repo)
                self.assertEqual(0, code, out + err)
                self.assertEqual(1, err.count(SKIP_MESSAGE), err)
                self.assertNotIn("EV20", out)

    def test_gate_runs_outside_install_folder_without_message(self):
        """FR13.3: the same copy outside such a folder runs the gate (a missing catalog is EV20, exit 1) and prints no skip line."""
        with tempfile.TemporaryDirectory() as t:
            repo = copy_repo(Path(t) / "claude-not-hidden" / "repo")
            (repo / "evals" / "catalog.json").unlink()
            code, out, err = run_studio(repo / "studio.py", "evals", "--all", "--json", cwd=repo)
            self.assertEqual(1, code, out + err)
            self.assertNotIn(SKIP_MESSAGE, err)
            self.assertIn("EV20", out)

    def test_installed_engine_matches_folder_names_only(self):
        """FR13.3: the test is on a whole folder name above the engine file, not on a part of a name."""
        names = E.evals.INSTALL_DIR_NAMES
        self.assertEqual((".claude", ".agents", ".codex", ".gemini"), tuple(names))
        yes = Path("x") / ".claude" / "plugins" / "p" / "scripts" / "studio_evals.py"
        no = [Path("x") / "claude" / "scripts" / "studio_evals.py", Path("x") / "my.claude" / "scripts" / "studio_evals.py",
              Path("x") / ".claude-plugin-dev" / "scripts" / "studio_evals.py", Path("x") / "scripts" / "studio_evals.py"]
        self.assertTrue(E.evals.installed_engine(yes))
        for path in no:
            self.assertFalse(E.evals.installed_engine(path), path)

    def test_gate_runs_on_own_repo(self):
        """FR13.3: on the engine's own repository the gate root is that repository (it always runs)."""
        self.assertFalse(E.evals.installed_engine())
        self.assertEqual(E.ROOT, E.evals.gate_root())

    def test_gate_root_none_for_installed_engine(self):
        """FR13.3: `gate_root` itself answers None when the engine file lies under an install folder."""
        with mock.patch.object(E.evals, "installed_engine", return_value=True):
            self.assertIsNone(E.evals.gate_root())


if __name__ == "__main__":
    unittest.main()
