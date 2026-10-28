"""SPR-03 TK10 (RQ-023 / RF-S6, FR12): `new` never overwrites an eval file that is there, and `--output` without `--eval-root` puts the evals beside it.

(a) `cases.json`, `rubric.md` and `baselines/BASELINE.md` are created exclusively; one that exists is kept and named on stdout (`kept existing <path>`).
(b) `--output <O>` without `--eval-root`: evals go to `<parent of O>/evals/<name>` when `O` is named `skills`, else `<O>/evals/<name>`; `O` is a drive root,
    or the evals folder would sit directly under a drive root, or a link lies on the way to `O` -> exit 2 before anything is written. Never into the repo of
    the cwd; into the engine's own repo only when `O` is there.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402
from test_catalog_gate import copy_repo, run_studio  # noqa: E402
from test_link_holes import can_link, drop_dir_link, make_dir_link  # noqa: E402

ROOT = E.ROOT
DESC = "Demo skill for the new command. Use when testing where the evals go."


def studio(*args, cwd=ROOT, engine=E.ENGINE_PATH):
    return run_studio(engine, *map(str, args), cwd=cwd)


def porcelain(repo: Path) -> str:
    """`git status --porcelain` of `repo`, untracked files listed one by one; "" when git cannot answer."""
    try:
        run = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=str(repo), capture_output=True, text=True,
                             encoding="utf-8", stdin=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return run.stdout if run.returncode == 0 else ""


class NewOutputTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.engine_before = porcelain(ROOT)

    def tearDown(self):
        self.assertEqual(self.engine_before, porcelain(ROOT), "the engine repo changed")

    def new(self, name, *extra, cwd=ROOT, engine=E.ENGINE_PATH):
        return studio("new", name, "--description", DESC, *extra, cwd=cwd, engine=engine)

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
        code, out, err = self.new("rel-skill", "--output", "rel/skills", cwd=self.tmp)
        self.assertEqual(0, code, out + err)
        self.assertTrue((self.tmp / "rel" / "skills" / "rel-skill" / "SKILL.md").is_file())
        self.assertTrue((self.tmp / "rel" / "evals" / "rel-skill" / "cases.json").is_file())
        self.assertFalse((self.tmp / "evals").exists())

    def test_new_explicit_eval_root_still_wins(self):
        """FR12.2: `--eval-root` is used as given even when `--output` is there."""
        code, out, err = self.new("explicit-root", "--output", self.tmp / "z" / "skills", "--eval-root", self.tmp / "elsewhere")
        self.assertEqual(0, code, out + err)
        self.assertTrue((self.tmp / "elsewhere" / "explicit-root" / "cases.json").is_file())
        self.assertFalse((self.tmp / "z" / "evals").exists())

    def test_new_output_drive_root_refused(self):
        """FR12.2: `--output` that is a drive root, or `<root>skills` (whose evals would sit under the root), exits 2 and creates nothing there."""
        anchor = Path(tempfile.gettempdir()).absolute().anchor
        self.assertTrue(anchor, "the temp folder has no drive root")
        name = "drive-root-refused"
        probes = [Path(anchor) / "evals" / name, Path(anchor) / "skills" / name, Path(anchor) / name]
        before = [p.exists() for p in probes]
        for output in (anchor, anchor + "skills"):
            code, out, err = self.new(name, "--output", output)
            self.assertEqual(2, code, (output, out, err))
            self.assertIn("drive root", err)
            self.assertEqual("", out)
        self.assertEqual(before, [p.exists() for p in probes])

    def test_new_output_inside_engine_repo_allowed(self):
        """FR12.2: `--output <repo>/skills` of the engine's own repo -> `<repo>/evals/<name>` (as when `--output` is not given), no refusal."""
        repo = copy_repo(self.tmp / "repo")
        code, out, err = self.new("in-repo", "--output", repo / "skills", cwd=self.tmp, engine=repo / "studio.py")
        self.assertEqual(0, code, out + err)
        self.assertTrue((repo / "skills" / "in-repo" / "SKILL.md").is_file())
        self.assertTrue((repo / "evals" / "in-repo" / "cases.json").is_file())
        code2, out2, err2 = self.new("in-repo-default", engine=repo / "studio.py", cwd=self.tmp)
        self.assertEqual(0, code2, out2 + err2)
        self.assertTrue((repo / "evals" / "in-repo-default" / "cases.json").is_file())

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

    def test_new_existing_target_still_exits_1_and_writes_no_evals(self):
        """Regression: an existing skill folder is refused with exit 1, and its evals are not touched."""
        (self.tmp / "o" / "taken").mkdir(parents=True)
        code, out, err = self.new("taken", "--output", self.tmp / "o")
        self.assertEqual(1, code, out + err)
        self.assertIn("refusing to overwrite existing", err)
        self.assertFalse((self.tmp / "o" / "evals").exists())


if __name__ == "__main__":
    unittest.main()
