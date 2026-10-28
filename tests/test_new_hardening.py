"""SPR-04 TK3 (RQ-026, RQ-031; FR12.1-FR12.5, FR13.2): `new` refuses cloud zones and odd paths with a message, leaves no orphan `SKILL.md`
when an eval file cannot be written, and lets the macOS system links (`/tmp`, `/var`, `/etc`) through while a link the user made is still refused.

Every «refuses to write» test runs `cmd_new` in this process inside `_writeguard.block_writes_outside`, so code that does not refuse
stops at its first write instead of putting files on the disk.
"""
from __future__ import annotations

import argparse
import builtins
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
from _writeguard import block_writes_outside  # noqa: E402
from test_link_holes import can_link, drop_dir_link, make_dir_link  # noqa: E402

DESC = "Demo skill for the new command. Use when testing the hardening of new."


def new_args(name, output=None, eval_root=None):
    return argparse.Namespace(name=name, description=DESC, output=output, eval_root=eval_root, full=False, lang="en")


def listing(base: Path) -> list:
    return sorted(str(p.relative_to(base)) for p in base.rglob("*") if "__pycache__" not in p.parts)


class Base(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def run_new(self, name, output=None, eval_root=None, allowed=None):
        """cmd_new in this process under the write guard; -> (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with block_writes_outside([self.tmp] if allowed is None else allowed), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = E.scaffold.cmd_new(new_args(name, None if output is None else str(output), None if eval_root is None else str(eval_root)))
        return code, out.getvalue(), err.getvalue()


class WriteGuardTests(Base):
    """FR12.5: the guard covers `open`, `write_bytes`, `touch` (and the rest of the list) and lets the allowed folder and reads through."""

    def test_fr12_5_guard_refuses_every_write_outside_the_allowed_folders(self):
        allowed = self.tmp / "ok"
        allowed.mkdir()
        elsewhere = self.tmp / "no"
        elsewhere.mkdir()
        existing = elsewhere / "there.txt"
        existing.write_bytes(b"read me\n")
        writers = {
            "open w": lambda p: open(p, "w"),
            "open ab": lambda p: open(p, "ab"),
            "io.open w": lambda p: io.open(p, "w"),
            "Path.open w": lambda p: p.open("w"),
            "write_text": lambda p: p.write_text("x"),
            "write_bytes": lambda p: p.write_bytes(b"x"),
            "touch": lambda p: p.touch(),
            "os.open": lambda p: os.open(str(p), os.O_WRONLY | os.O_CREAT),
            "mkdir": lambda p: p.mkdir(),
            "os.mkdir": lambda p: os.mkdir(str(p)),
        }
        with block_writes_outside([allowed]):
            for label, write in writers.items():
                with self.assertRaises(PermissionError, msg=label):
                    write(elsewhere / ("new-" + label.replace(" ", "-").replace(".", "-")))
                inside = allowed / ("in-" + label.replace(" ", "-").replace(".", "-"))
                result = write(inside)
                if hasattr(result, "close"):
                    result.close()
                elif label == "os.open":
                    os.close(result)
                self.assertTrue(inside.exists(), label)
            with self.assertRaises(PermissionError):
                open(existing, "r+")
            with open(existing, "rb") as handle:  # a read of a file outside is not a write
                self.assertEqual(b"read me\n", handle.read())
            self.assertEqual(b"read me\n", existing.read_bytes())
            elsewhere.mkdir(exist_ok=True)  # a folder that is there is not made again
        self.assertEqual(["there.txt"], sorted(p.name for p in elsewhere.iterdir()))

    def test_fr12_5_guard_is_removed_on_exit(self):
        original = builtins.open
        with block_writes_outside([]):
            self.assertIsNot(builtins.open, original)
        target = self.tmp / "after.txt"
        target.write_text("free again")
        with open(target, "a") as handle:
            handle.write("!")
        self.assertEqual("free again!", target.read_text())
        self.assertIs(builtins.open, io.open)

    def test_fr12_5_guard_follows_real_paths_and_case(self):
        base = self.tmp / "Mixed"
        base.mkdir()
        with block_writes_outside([Path(str(base).swapcase()) if os.name == "nt" else base]):
            (base / "a.txt").write_text("a")
            with self.assertRaises(PermissionError):
                (self.tmp / "b.txt").write_text("b")


class RefusesCloudTests(Base):
    def test_fr12_1_output_in_a_cloud_zone_is_refused_before_any_write(self):
        before = listing(self.tmp)
        for output in (self.tmp / "OneDrive - Firm" / "skills", self.tmp / "SharePoint" / "x" / "sub", self.tmp / ".secret" / "skills"):
            code, out, err = self.run_new("cloudy", output)
            self.assertEqual(1, code, (output, out, err))
            self.assertIn("ERROR INPUT", err)
            self.assertTrue("cloud" in err or "secret" in err, err)
            self.assertNotIn("Traceback", err)
            self.assertEqual("", out)
        code, out, err = self.run_new("cloudy", self.tmp / "o" / "skills", eval_root=self.tmp / "OneDrive" / "ev")
        self.assertEqual(1, code, out + err)
        self.assertIn("ERROR INPUT", err)
        # a parent that is a cloud placeholder (attribute bits) by lstat, whatever its name
        placeholder = self.tmp / "plain"
        placeholder.mkdir()
        before = listing(self.tmp)
        with mock.patch.object(E.fs, "path_is_cloud", side_effect=lambda p: Path(p) == placeholder):
            code, out, err = self.run_new("cloudy", placeholder / "deep" / "skills")
        self.assertEqual(1, code, out + err)
        self.assertIn("ERROR INPUT", err)
        self.assertEqual(before, listing(self.tmp), "something was written")


class OddPathTests(Base):
    def test_fr12_2_a_path_of_another_system_gives_an_error_line_not_a_traceback(self):
        if os.name == "nt":
            odd = ["a<b", "C:\\x|y", "out\x00put", "x?", "d\\*"]
        else:
            odd = ["C:\\a", "C:/a", "\\\\server\\share\\x", "out\x00put"]
        before = listing(self.tmp)
        for text in odd:
            given = text if (":" in text or text.startswith("\\\\")) else os.path.join(str(self.tmp), text)
            code, out, err = self.run_new("odd-path", given)
            self.assertEqual(1, code, (text, out, err))
            self.assertIn("ERROR INPUT", err, text)
            self.assertNotIn("Traceback", err)
        self.assertEqual(before, listing(self.tmp))

    def test_fr12_2_output_problem_by_system(self):
        problem = E.scaffold.output_problem
        for text in ("C:\\a", "c:/a", "\\\\srv\\share"):
            self.assertTrue(problem(text, windows=False), text)
        for text in ("a<b", "x|y", "a?b", 'q"r', "a*", "trail.", "trail ", "a\x01b", "a\x00b"):
            self.assertTrue(problem(text, windows=True), text)
        self.assertTrue(problem("a\x00b", windows=False))
        for text in ("C:\\a\\b", "C:/a/b", "\\\\srv\\share\\x", "rel\\dir", "..\\up"):
            self.assertIsNone(problem(text, windows=True), text)
        for text in ("/tmp/x", "rel/dir", "a:b", "x\\y", "~/skills"):
            self.assertIsNone(problem(text, windows=False), text)

    def test_fr12_3_the_skills_rule_looks_at_the_normalised_path(self):
        base = self.tmp / "x"
        code, out, err = self.run_new("norm-skills", os.path.join(str(base), "skills", "sub", ".."))
        self.assertEqual(0, code, out + err)
        self.assertTrue((base / "skills" / "norm-skills" / "SKILL.md").is_file())
        self.assertTrue((base / "evals" / "norm-skills" / "cases.json").is_file())
        self.assertFalse((base / "skills" / "evals").exists())
        self.assertFalse((base / "skills" / "sub").exists())


class NoOrphanTests(Base):
    def test_fr12_4_an_eval_that_cannot_be_written_leaves_no_skill_md(self):
        real = E.fs.create_exclusive

        def denied_for_rubric(path):
            if Path(path).name == "rubric.md":
                raise PermissionError(13, "Permission denied")
            return real(path)
        (self.tmp / "ev" / "orphan" / "baselines").mkdir(parents=True)
        kept = self.tmp / "ev" / "orphan" / "baselines" / "BASELINE.md"
        kept.write_bytes(b"mine\n")  # there before this run: stays
        before = listing(self.tmp)
        with mock.patch.object(E.fs, "create_exclusive", denied_for_rubric):
            code, out, err = self.run_new("orphan", self.tmp / "o" / "skills", eval_root=self.tmp / "ev")
        self.assertEqual(2, code, out + err)
        self.assertIn("ERROR: cannot write %s" % (self.tmp / "ev" / "orphan" / "rubric.md"), err)
        self.assertNotIn("Created draft Skill", out)
        self.assertFalse((self.tmp / "o" / "skills" / "orphan").exists())
        self.assertEqual(before, listing(self.tmp), "this run's files and folders are not cleaned up")
        self.assertEqual(b"mine\n", kept.read_bytes())

    def test_fr12_4_a_failing_copy_is_reported_and_cleaned(self):
        before = listing(self.tmp)
        with mock.patch.object(E.scaffold.shutil, "copyfile", side_effect=PermissionError(13, "Permission denied")):
            code, out, err = self.run_new("copy-fails", self.tmp / "o" / "skills")
        self.assertEqual(2, code, out + err)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(before, listing(self.tmp))


class SystemLinkTests(Base):
    def test_fr13_2_system_link_table(self):
        ok = E.scaffold._system_link_ok
        for prefix in ("/tmp", "/var", "/etc"):
            for target in ("private" + prefix, "/private" + prefix):
                with mock.patch.object(E.scaffold.os, "readlink", return_value=target):
                    self.assertTrue(ok(Path(prefix)), (prefix, target))
        other = {"/tmp": "/private/var", "/var": "/elsewhere/var", "/etc": "private/tmpx"}
        for prefix, target in other.items():
            with mock.patch.object(E.scaffold.os, "readlink", return_value=target):
                self.assertFalse(ok(Path(prefix)), (prefix, target))
        with mock.patch.object(E.scaffold.os, "readlink", return_value="/private/tmp/ln"):
            self.assertFalse(ok(Path("/tmp/ln")))  # a link under /tmp is the user's
            self.assertFalse(ok(Path("/tmp/ln/x")))
        for text in ("/usr", "/", "/private/tmp"):
            with mock.patch.object(E.scaffold.os, "readlink", return_value="/private/tmp"):
                self.assertFalse(ok(Path(text)), text)
        with mock.patch.object(E.scaffold.os, "readlink", side_effect=OSError("not a link")):
            self.assertFalse(ok(Path("/tmp")))

    def test_fr13_2_chain_skips_system_links_only(self):
        system, user = self.tmp / "sys", self.tmp / "usr"
        system.mkdir()
        user.mkdir()
        links = {system, user}
        with mock.patch.object(E.fs, "is_link", side_effect=lambda p: Path(p) in links), \
                mock.patch.object(E.scaffold, "_system_link_ok", side_effect=lambda p: Path(p) == system):
            code, out, err = self.run_new("via-system", system / "skills")
            self.assertEqual(0, code, out + err)
            self.assertTrue((system / "skills" / "via-system" / "SKILL.md").is_file())
            before = listing(self.tmp)
            code, out, err = self.run_new("via-user", user / "skills")
            self.assertEqual(2, code, out + err)
            self.assertIn("symlink or junction", err)
            self.assertEqual(before, listing(self.tmp))

    @unittest.skipIf(sys.platform != "darwin", "FR13.2: the system links exist on macOS only")
    def test_fr13_2_new_under_system_tmp_is_allowed(self):
        base = Path(tempfile.mkdtemp(dir="/tmp"))
        self.addCleanup(shutil.rmtree, str(base), True)
        code, out, err = self.run_new("mac-tmp", base / "skills", allowed=[base])
        self.assertEqual(0, code, out + err)
        self.assertTrue((base / "skills" / "mac-tmp" / "SKILL.md").is_file())
        var_base = Path(tempfile.mkdtemp(dir="/var/tmp"))  # `/var/tmp` is under the system link `/var`
        self.addCleanup(shutil.rmtree, str(var_base), True)
        code, out, err = self.run_new("mac-var", var_base / "skills", allowed=[var_base])
        self.assertEqual(0, code, out + err)

    @unittest.skipIf(sys.platform != "darwin", "FR13.2: the system links exist on macOS only")
    def test_fr13_2_a_link_the_user_made_under_tmp_is_still_refused(self):
        base = Path(tempfile.mkdtemp(dir="/tmp"))
        self.addCleanup(shutil.rmtree, str(base), True)
        target = base / "target"
        target.mkdir()
        link = base / "ln"
        os.symlink(str(target), str(link))
        code, out, err = self.run_new("mac-link", link / "skills", allowed=[base])
        self.assertEqual(2, code, out + err)
        self.assertIn("symlink or junction", err)
        self.assertEqual([], sorted(p.name for p in target.iterdir()))

    @unittest.skipUnless(can_link(), "this machine can make neither a symlink nor a junction")
    def test_a_real_link_is_still_refused_whatever_its_name(self):
        """The system exception is by exact prefix: a link called `tmp` in a temporary folder is not `/tmp`."""
        target = self.tmp / "target"
        target.mkdir()
        link = self.tmp / "tmp"
        self.assertTrue(make_dir_link(link, target))
        self.addCleanup(drop_dir_link, link)
        code, out, err = self.run_new("lookalike", link / "skills")
        self.assertEqual(2, code, out + err)
        self.assertEqual([], sorted(p.name for p in target.iterdir()))


if __name__ == "__main__":
    unittest.main()
