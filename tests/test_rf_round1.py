"""SPR-01 RF round 1: package/install secret names and folder case (RF-S1, RF-S2), move_aside (RF-S3), fmt identity (RF-S4),
export cleanup of a link it did not make (RF-T4), --roots-file comment cost (RF-S8).

Labels: bắt-lỗi = goes through the CLI or a function that exists at df875ce and goes red by assertion/exit code;
đơn-vị-hàm-mới = a new helper; tương-đương = same result as before."""
import contextlib
import errno
import importlib.util
import io
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("studio_rf1_impl", ROOT / "studio.py")
studio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(studio)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = studio.main(list(argv))
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue()


class SkillCopy(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.skill = self.tmp / "data-quality-audit"
        shutil.copytree(ROOT / "skills" / "data-quality-audit", self.skill)


SECRET_NAMES = ["auth.json", "prod.credentials.json", ".ENV", "ID_RSA", "Secrets.JSON", "Credentials.JSON", "server.PEM", ".env.production"]


class PackageSecretNamesTests(SkillCopy):
    def test_bat_loi_package_refuses_secret_named_files_any_case(self):
        """bắt-lỗi: `package` shares the --export name rule: auth.json, *.credentials.json, .ENV, ID_RSA, Secrets.JSON... are ERROR, exit 1, no zip."""
        for name in SECRET_NAMES:
            with self.subTest(name):
                (self.skill / "assets").mkdir(exist_ok=True)
                bait = self.skill / "assets" / name
                bait.write_bytes(b"placeholder-not-a-secret")
                out = self.tmp / ("out-" + name.replace(".", "_"))
                code, o, e = run("package", str(self.skill), "--out", str(out))
                self.assertEqual(code, 1, o + e)
                self.assertFalse((out / "data-quality-audit.zip").exists())
                self.assertIn("SEC", o + e)
                bait.unlink()

    def test_bat_loi_install_refuses_secret_named_files_any_case(self):
        """bắt-lỗi: `install` uses the same rule and writes nothing."""
        (self.skill / "assets").mkdir(exist_ok=True)
        for name in ("auth.json", "ID_RSA", ".ENV"):
            with self.subTest(name):
                bait = self.skill / "assets" / name
                bait.write_bytes(b"placeholder-not-a-secret")
                ws = self.tmp / ("ws-" + name.replace(".", "_"))
                ws.mkdir()
                code, o, e = run("install", str(self.skill), "--agent", "claude", "--workspace", str(ws))
                self.assertEqual(code, 1, o + e)
                self.assertFalse((ws / ".claude").exists())
                bait.unlink()

    def test_tuong_duong_ordinary_asset_still_packages(self):
        """tương-đương: a plain asset name is shipped."""
        (self.skill / "assets").mkdir(exist_ok=True)
        (self.skill / "assets" / "notes.txt").write_text("ok\n", encoding="utf-8")
        code, o, e = run("package", str(self.skill), "--out", str(self.tmp / "out"))
        self.assertEqual(code, 0, o + e)


class PackageFolderCaseTests(SkillCopy):
    def test_bat_loi_package_skips_eval_and_test_folders_in_any_case(self):
        """bắt-lỗi: `Evals/` and `TESTS/` are left out of the zip like `evals/` and `tests/`."""
        for folder, name in (("Evals", "fixture.csv"), ("TESTS", "t.py"), ("Tests", "u.py")):
            (self.skill / folder).mkdir(exist_ok=True)
            (self.skill / folder / name).write_text("x\n", encoding="utf-8")
        code, o, e = run("package", str(self.skill), "--out", str(self.tmp / "out"))
        self.assertEqual(code, 0, o + e)
        with zipfile.ZipFile(self.tmp / "out" / "data-quality-audit.zip") as zf:
            names = zf.namelist()
        self.assertEqual([], [n for n in names if n.lower().split("/")[1:2] in (["evals"], ["tests"])], names)

    def test_don_vi_ham_moi_walk_files_skip_names_ignore_case(self):
        """đơn-vị-hàm-mới: walk_files(skip_names=) compares names case-insensitively."""
        (self.skill / "EVALS").mkdir()
        (self.skill / "EVALS" / "f.csv").write_text("x\n", encoding="utf-8")
        found = studio.walk_files(self.skill, skip_names=studio.SKIP_DIRS)[0]
        self.assertEqual([], [p for p in found if "EVALS" in p.parts])


class MoveAsideTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.src, self.dst = self.tmp / "old", self.tmp / "bak"
        (self.src / "sub").mkdir(parents=True)
        for n in ("a.md", "sub/b.md", "z.md"):
            (self.src / n).write_text(n, encoding="utf-8")

    def test_bat_loi_non_exdev_rename_failure_keeps_the_old_folder_whole(self):
        """bắt-lỗi: a rename failing for a reason other than another device (a locked file) does not copy-then-delete; src stays complete, no half dst."""
        with mock.patch.object(os, "rename", side_effect=PermissionError(errno.EACCES, "in use")):
            with self.assertRaises(PermissionError):
                studio.move_aside(self.src, self.dst)
        self.assertEqual(["a.md", "sub", "z.md"], sorted(os.listdir(self.src)))
        self.assertFalse(self.dst.exists())

    def test_tuong_duong_exdev_copies_then_removes(self):
        """tương-đương: across devices the folder is copied and the source removed (as before)."""
        with mock.patch.object(os, "rename", side_effect=OSError(errno.EXDEV, "cross-device")):
            studio.move_aside(self.src, self.dst)
        self.assertFalse(self.src.exists())
        self.assertEqual(["a.md", "sub", "z.md"], sorted(os.listdir(self.dst)))

    def test_bat_loi_failed_delete_after_copy_reports_the_real_state(self):
        """bắt-lỗi: copy done but the old folder cannot be fully removed -> a distinct error that names the backup; the backup stays whole."""
        with mock.patch.object(os, "rename", side_effect=OSError(errno.EXDEV, "cross-device")), \
                mock.patch.object(studio.shutil, "rmtree", side_effect=PermissionError(errno.EACCES, "in use")):
            with self.assertRaises(studio.MoveAsideError) as ctx:
                studio.move_aside(self.src, self.dst)
        self.assertIn(str(self.dst), str(ctx.exception))
        self.assertEqual(["a.md", "sub", "z.md"], sorted(os.listdir(self.dst)))

    def test_bat_loi_install_force_when_rename_is_denied_leaves_the_old_skill_intact(self):
        """bắt-lỗi: `install --force` with a rename denied: exit 1, the installed Skill is complete, the message says it was left in place."""
        skill = self.tmp / "data-quality-audit"
        shutil.copytree(ROOT / "skills" / "data-quality-audit", skill)
        ws = self.tmp / "ws"
        ws.mkdir()
        self.assertEqual(0, run("install", str(skill), "--agent", "claude", "--workspace", str(ws))[0])
        dest = ws / ".claude" / "skills" / "data-quality-audit"
        before = sorted(str(p.relative_to(dest)) for p in dest.rglob("*"))
        with mock.patch.object(os, "rename", side_effect=PermissionError(errno.EACCES, "in use")):
            code, o, e = run("install", str(skill), "--agent", "claude", "--workspace", str(ws), "--force")
        self.assertEqual(1, code, o + e)
        self.assertEqual(before, sorted(str(p.relative_to(dest)) for p in dest.rglob("*")))
        self.assertIn("left in place", e)


class FmtIdentityTests(unittest.TestCase):
    DIRTY = "---\nname: demo-skill\ndescription: Checks a toy example. Use when testing fmt.\n---\n\n# Demo \n\nBody text here.\n"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "SKILL.md"
        self.path.write_bytes(self.DIRTY.encode("utf-8"))

    def test_bat_loi_fmt_passes_the_listing_identity_to_every_read(self):
        """bắt-lỗi: fmt reads (--check) and backs up (--fix) with expect_stat set, so Windows compares the opened handle with the checked file too."""
        calls = []
        real = studio.open_nofollow_read

        def spy(path, expect_stat=None, single_link=True):
            calls.append((Path(path).name, expect_stat is not None))
            return real(path, expect_stat, single_link)

        with mock.patch.object(studio, "open_nofollow_read", spy):
            run("fmt", "--check", str(self.path))
            run("fmt", "--fix", str(self.path))
        self.assertGreaterEqual(len(calls), 3, calls)
        self.assertTrue(all(flag for _, flag in calls), calls)

    def test_bat_loi_fmt_swapped_file_is_refused_not_read(self):
        """bắt-lỗi: a handle whose identity differs from the checked lstat is refused (reported unreadable), not formatted."""
        other = self.path.parent / "other.md"
        other.write_bytes(self.DIRTY.encode("utf-8"))
        real_lstat = os.lstat
        target = os.path.normcase(str(self.path))

        def lie(p, *a, **k):
            return real_lstat(other if os.path.normcase(str(p)) == target else p, *a, **k)

        with mock.patch.object(os, "lstat", lie):
            code, o, e = run("fmt", "--check", "--json", str(self.path))
        self.assertIn("unreadable", o + e)


class ExportCleanupTests(unittest.TestCase):
    def test_bat_loi_existing_link_like_name_is_a_clash_and_survives(self):
        """bắt-lỗi: a name that lexists but not exists() (a dangling link) counts as taken: EX5, and the cleanup loop never removes it."""
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "out"
            argv = ("evals", "data-quality-audit", "--export", "agentskills", "--out", str(out))
            code, o, e = run(*argv)
            self.assertEqual(0, code, o + e)
            target = out / "data-quality-audit" / "evals" / "evals.json"
            target.write_text("PRE-EXISTING", encoding="utf-8")
            real_exists = Path.exists

            exported = os.path.normcase(str(out))

            def blind(self_, *a, **k):  # as if every exported name were a dangling link: exists() False, lexists() True
                return False if os.path.normcase(str(self_)).startswith(exported + os.sep) and self_.is_file() else real_exists(self_, *a, **k)

            with mock.patch.object(Path, "exists", blind):
                code, o, e = run(*argv)
            self.assertEqual(1, code, o + e)
            self.assertIn("EX5", o + e)
            self.assertEqual("PRE-EXISTING", target.read_text(encoding="utf-8"))


class RootsFileCommentTimeTests(unittest.TestCase):
    def test_bat_loi_roots_file_comment_strip_is_linear(self):
        """bắt-lỗi: a line of one word, 40000 blanks and another word is read in well under a second (the old regex took ~2 s)."""
        with tempfile.TemporaryDirectory() as t:
            listing = Path(t) / "roots.txt"
            listing.write_text("a" + " " * 40000 + "b\n", encoding="utf-8")
            started = time.perf_counter()
            with self.assertRaises(ValueError):
                studio.parse_roots(None, str(listing), None)
            self.assertLess(time.perf_counter() - started, 0.5)

    def test_tuong_duong_comment_forms(self):
        """tương-đương: trailing comment after blanks is cut, a '#' inside a name stays."""
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            (base / "a#b").mkdir()
            (base / "plain").mkdir()
            listing = base / "roots.txt"
            listing.write_text("# head\n%s   # note\n%s\n" % (base / "plain", base / "a#b"), encoding="utf-8")
            self.assertEqual([base / "plain", base / "a#b"], studio.parse_roots(None, str(listing), None))


if __name__ == "__main__":
    unittest.main()
