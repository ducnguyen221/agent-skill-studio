"""SPR-03 TK10 (RQ-023 / RF-S6, FR12): `new` never overwrites an eval file that is there, and `--output` without `--eval-root` puts the evals beside it.

(a) `cases.json`, `rubric.md` and `baselines/BASELINE.md` are created exclusively; one that exists is kept and named on stdout (`kept existing <path>`).
(b) `--output <O>` without `--eval-root`: evals go to `<parent of O>/evals/<name>` when `O` is named `skills`, else `<O>/evals/<name>`; `O` is a drive root,
    or the evals folder would sit directly under a drive root, or a link lies on the way to `O` -> exit 2 before anything is written. Never into the repo of
    the cwd; into the engine's own repo only when `O` is there.
"""
from __future__ import annotations

import argparse
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
from test_catalog_gate import copy_repo, run_studio  # noqa: E402
from test_link_holes import can_link, drop_dir_link, make_dir_link  # noqa: E402

ROOT = E.ROOT
DESC = "Demo skill for the new command. Use when testing where the evals go."


def studio(*args, cwd, engine):
    return run_studio(engine, *map(str, args), cwd=cwd)


def listing(base: Path) -> list:
    """Every file and folder under `base` (a link counts as one entry), `__pycache__` left out."""
    return sorted(str(p.relative_to(base)) for p in base.rglob("*") if "__pycache__" not in p.parts)


def forbid(*_args, **_kwargs):
    raise AssertionError("a write was attempted where none may happen")


def new_args(name, output=None, eval_root=None):
    return argparse.Namespace(name=name, description=DESC, output=output, eval_root=eval_root, full=False, lang="en")


class NewOutputTests(unittest.TestCase):
    """Every test runs the engine of a copy of the repo, from a folder that is not a repo, so a `new` that goes wrong writes into the temporary folder only."""
    repo_may_change = False

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.repo = copy_repo(self.tmp / "repo")
        self.cwd = self.tmp / "cwd"
        self.cwd.mkdir()
        self.repo_before = listing(self.repo)

    def tearDown(self):
        if not self.repo_may_change:
            self.assertEqual(self.repo_before, listing(self.repo), "the engine's repo changed")

    def new(self, name, *extra, cwd=None):
        return studio("new", name, "--description", DESC, *extra, cwd=cwd or self.cwd, engine=self.repo / "studio.py")

    def test_new_keeps_existing_cases(self):
        """FR12.1: an eval file that is there is kept byte for byte and named; the ones that are not there are made."""
        evals = self.tmp / "ev" / "keep-me"
        evals.mkdir(parents=True)
        (evals / "cases.json").write_bytes(b'{"mine": true}\n')
        (evals / "baselines").mkdir()
        (evals / "baselines" / "BASELINE.md").write_bytes(b"my baseline\n")
        code, out, err = self.new("keep-me", "--output", self.tmp / "skills", "--eval-root", self.tmp / "ev")
        self.assertEqual(0, code, out + err)
        self.assertEqual(b'{"mine": true}\n', (evals / "cases.json").read_bytes())
        self.assertEqual(b"my baseline\n", (evals / "baselines" / "BASELINE.md").read_bytes())
        self.assertIn("kept existing %s" % (evals / "cases.json"), out)
        self.assertIn("kept existing %s" % (evals / "baselines" / "BASELINE.md"), out)
        self.assertNotIn("kept existing %s" % (evals / "rubric.md"), out)
        self.assertTrue((evals / "rubric.md").is_file())
        self.assertIn("External evals: %s" % evals, out)

    def test_new_keeps_every_existing_eval_file_and_says_so_per_file(self):
        """FR12.1: all three there -> three `kept existing` lines, nothing rewritten, exit 0 (the skill itself is new)."""
        evals = self.tmp / "ev" / "keep-all"
        (evals / "baselines").mkdir(parents=True)
        files = {evals / "cases.json": b"A\n", evals / "rubric.md": b"B\n", evals / "baselines" / "BASELINE.md": b"C\n"}
        for path, data in files.items():
            path.write_bytes(data)
        code, out, err = self.new("keep-all", "--output", self.tmp / "skills", "--eval-root", self.tmp / "ev")
        self.assertEqual(0, code, out + err)
        for path, data in files.items():
            self.assertEqual(data, path.read_bytes())
            self.assertIn("kept existing %s" % path, out)
        self.assertEqual(3, out.count("kept existing "))

    def test_new_does_not_write_through_a_link_in_the_eval_folder(self):
        """FR12.1: a link where an eval file should be is kept as it is, never written through."""
        evals = self.tmp / "ev" / "linked"
        evals.mkdir(parents=True)
        victim = self.tmp / "victim.txt"
        victim.write_bytes(b"untouched\n")
        try:
            os.symlink(str(victim), str(evals / "cases.json"))
        except (OSError, NotImplementedError):
            self.skipTest("this machine cannot make a file symlink")
        code, out, err = self.new("linked", "--output", self.tmp / "skills", "--eval-root", self.tmp / "ev")
        self.assertEqual(0, code, out + err)
        self.assertEqual(b"untouched\n", victim.read_bytes())
        self.assertIn("kept existing %s" % (evals / "cases.json"), out)

    def test_new_output_named_skills(self):
        """FR12.2: `--output x/skills` -> evals in `x/evals/<name>`, nothing in `x/skills/evals`."""
        base = self.tmp / "x"
        code, out, err = self.new("named-skills", "--output", base / "skills")
        self.assertEqual(0, code, out + err)
        self.assertTrue((base / "skills" / "named-skills" / "SKILL.md").is_file())
        for rel in ("cases.json", "rubric.md", "baselines/BASELINE.md"):
            self.assertTrue((base / "evals" / "named-skills" / rel).is_file(), rel)
        self.assertFalse((base / "skills" / "evals").exists())
        self.assertIn("External evals: %s" % (base / "evals" / "named-skills"), out)

    def test_new_output_other_name(self):
        """FR12.2: `--output y` (not named skills) -> evals in `y/evals/<name>`, the skill in `y/<name>`."""
        base = self.tmp / "y"
        code, out, err = self.new("other-name", "--output", base)
        self.assertEqual(0, code, out + err)
        self.assertTrue((base / "other-name" / "SKILL.md").is_file())
        self.assertTrue((base / "evals" / "other-name" / "cases.json").is_file())
        self.assertIn("External evals: %s" % (base / "evals" / "other-name"), out)
        self.assertFalse((self.tmp / "evals").exists())

    def test_new_output_relative(self):
        """FR12.2: a relative `--output` is taken from the cwd, which is not a repo; nothing goes into the engine's repo."""
        code, out, err = self.new("rel-skill", "--output", "rel/skills")
        self.assertEqual(0, code, out + err)
        self.assertTrue((self.cwd / "rel" / "skills" / "rel-skill" / "SKILL.md").is_file())
        self.assertTrue((self.cwd / "rel" / "evals" / "rel-skill" / "cases.json").is_file())
        self.assertFalse((self.cwd / "evals").exists())

    def test_new_explicit_eval_root_still_wins(self):
        """FR12.2: `--eval-root` is used as given even when `--output` is there."""
        code, out, err = self.new("explicit-root", "--output", self.tmp / "z" / "skills", "--eval-root", self.tmp / "elsewhere")
        self.assertEqual(0, code, out + err)
        self.assertTrue((self.tmp / "elsewhere" / "explicit-root" / "cases.json").is_file())
        self.assertFalse((self.tmp / "z" / "evals").exists())

    def test_new_output_drive_root_refused(self):
        """FR12.2: `--output` that is a drive root, or `<root>skills` (whose evals would sit under the root), exits 2 and writes nothing.
        A `..` that leads back to the root (`<root>x/..`, `<root>x/../skills`) is the same refusal (RF-B1).

        Run in this process with every way of writing or making a folder replaced by one that fails the test, so a `new` that does not refuse
        stops at its first write and leaves nothing on the drive."""
        anchor = Path(tempfile.gettempdir()).absolute().anchor
        self.assertTrue(anchor, "the temp folder has no drive root")
        name = "drive-root-refused"
        probes = [Path(anchor) / "evals" / name, Path(anchor) / "skills" / name, Path(anchor) / name]
        before = [p.exists() for p in probes]

        def drop_what_the_test_made():  # only a probe that was not there before the test; unreachable while the guards below hold
            for probe, existed in zip(probes, before):
                if not existed and probe.exists():
                    shutil.rmtree(probe, ignore_errors=True)
        self.addCleanup(drop_what_the_test_made)
        guards = [mock.patch.object(Path, "mkdir", forbid), mock.patch.object(Path, "write_text", forbid), mock.patch.object(os, "mkdir", forbid),
                  mock.patch.object(os, "makedirs", forbid), mock.patch.object(shutil, "copytree", forbid), mock.patch.object(shutil, "copyfile", forbid),
                  mock.patch.object(E.fs, "create_exclusive", forbid)]
        with contextlib.ExitStack() as stack:
            for guard in guards:
                stack.enter_context(guard)
            dotted = os.path.join(anchor, "x", "..")
            for output in (anchor, anchor + "skills", dotted, os.path.join(dotted, "skills")):
                err, out = io.StringIO(), io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                    code = E.scaffold.cmd_new(new_args(name, output))
                self.assertEqual(2, code, (output, out.getvalue(), err.getvalue()))
                self.assertIn("drive root", err.getvalue())
                self.assertEqual("", out.getvalue())
        self.assertEqual(before, [p.exists() for p in probes])

    def test_new_output_inside_engine_repo_allowed(self):
        """FR12.2: `--output <repo>/skills` of the engine's own repo -> `<repo>/evals/<name>` (as when `--output` is not given), no refusal."""
        self.repo_may_change = True
        code, out, err = self.new("in-repo", "--output", self.repo / "skills")
        self.assertEqual(0, code, out + err)
        self.assertTrue((self.repo / "skills" / "in-repo" / "SKILL.md").is_file())
        self.assertTrue((self.repo / "evals" / "in-repo" / "cases.json").is_file())
        code2, out2, err2 = self.new("in-repo-default")
        self.assertEqual(0, code2, out2 + err2)
        self.assertTrue((self.repo / "evals" / "in-repo-default" / "cases.json").is_file())

    @unittest.skipUnless(can_link(), "this machine can make neither a symlink nor a junction")
    def test_new_output_through_link_refused(self):
        """FR12.2: a link on the way to `--output` (or at `evals`) exits 2 before anything is written, the link's target stays empty."""
        target = self.tmp / "target"
        target.mkdir()
        link = self.tmp / "link"
        self.assertTrue(make_dir_link(link, target))
        self.addCleanup(drop_dir_link, link)
        for output in (link / "skills", link / "sub", link):
            code, out, err = self.new("through-link", "--output", output)
            self.assertEqual(2, code, (output, out, err))
            self.assertIn("link", err)
        self.assertEqual([], sorted(p.name for p in target.iterdir()))
        # `evals` itself a link: the derived eval folder is refused too
        base = self.tmp / "b"
        base.mkdir()
        evals_link = base / "evals"
        self.assertTrue(make_dir_link(evals_link, target))
        self.addCleanup(drop_dir_link, evals_link)
        code, out, err = self.new("through-link", "--output", base / "skills")
        self.assertEqual(2, code, out + err)
        self.assertEqual([], sorted(p.name for p in target.iterdir()))
        self.assertFalse((base / "skills").exists())

    @unittest.skipUnless(can_link(), "this machine can make neither a symlink nor a junction")
    def test_new_refuses_a_link_at_the_eval_folder_or_below_it(self):
        """FR12.1/FR12.2 (TK10 round 1): a link at `evals/<name>`, `evals/<name>/baselines` or `evals/<name>/fixtures` exits 2 and writes nothing
        into the link's target or anywhere else; the same with a given `--eval-root`."""
        target = self.tmp / "target"
        target.mkdir()
        for case, where in enumerate(("", "baselines", "fixtures")):
            for derived in (True, False):
                base = self.tmp / ("case%d%s" % (case, "d" if derived else "g"))
                evals = base / "evals"
                evals.mkdir(parents=True)
                hole = evals / "hole"
                if where:
                    hole.mkdir()
                    hole = hole / where
                self.assertTrue(make_dir_link(hole, target), where)
                self.addCleanup(drop_dir_link, hole)
                args = ("--output", base / "skills") if derived else ("--output", base / "skills", "--eval-root", evals)
                code, out, err = self.new("hole", *args)
                self.assertEqual(2, code, (where, derived, out, err))
                self.assertIn("symlink or junction", err)
                self.assertIn(str(hole), err)
                self.assertEqual([], sorted(p.name for p in target.iterdir()), (where, derived))
                self.assertFalse((base / "skills").exists(), (where, derived))
                if where:
                    self.assertEqual([where], sorted(p.name for p in (evals / "hole").iterdir()), (where, derived))

    def test_write_new_reports_a_file_it_cannot_create(self):
        """TK10 round 1: `PermissionError` and `UnsafeOpen` from `create_exclusive` give an ERROR line with the path and a False answer, not a traceback."""
        path = self.tmp / "f.txt"
        for error in (PermissionError(13, "Permission denied"), E.fs.UnsafeOpen("created file is not the named path (link raced in): %s" % path)):
            err = io.StringIO()
            with mock.patch.object(E.fs, "create_exclusive", side_effect=error), contextlib.redirect_stderr(err):
                self.assertFalse(E.scaffold.write_new(path, "x"))
            self.assertIn("ERROR: cannot write %s" % path, err.getvalue())
        self.assertFalse(path.exists())

    def test_new_exits_2_when_an_eval_file_cannot_be_created(self):
        """TK10 round 1: `new` ends with exit 2 and the path on stderr when an eval file cannot be written (the other two are still tried, then everything this run made is taken back: FR12.4)."""
        err, out = io.StringIO(), io.StringIO()
        real = E.fs.create_exclusive

        def denied_for_rubric(path, anchor=None):  # SPR-05 TK3: create_exclusive also takes the anchor of the pinned folder chain
            if Path(path).name == "rubric.md":
                raise PermissionError(13, "Permission denied")
            return real(path, anchor=anchor)
        with mock.patch.object(E.fs, "create_exclusive", denied_for_rubric), contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = E.scaffold.cmd_new(new_args("no-rubric", self.tmp / "skills", self.tmp / "ev"))
        self.assertEqual(2, code, out.getvalue() + err.getvalue())
        self.assertIn("ERROR: cannot write %s" % (self.tmp / "ev" / "no-rubric" / "rubric.md"), err.getvalue())
        self.assertFalse((self.tmp / "ev" / "no-rubric" / "cases.json").exists())  # SPR-04 FR12.4: what this run made is taken back, no orphan SKILL.md either
        self.assertFalse((self.tmp / "skills" / "no-rubric").exists())
        self.assertNotIn("Created draft Skill", out.getvalue())

    def test_new_existing_target_still_exits_1_and_writes_no_evals(self):
        """Regression: an existing skill folder is refused with exit 1, and its evals are not touched."""
        (self.tmp / "o" / "taken").mkdir(parents=True)
        code, out, err = self.new("taken", "--output", self.tmp / "o")
        self.assertEqual(1, code, out + err)
        self.assertIn("refusing to overwrite existing", err)
        self.assertFalse((self.tmp / "o" / "evals").exists())


if __name__ == "__main__":
    unittest.main()
