"""SPR-01 TK4: `install` refuses a linked skill root, a linked or dangling destination, and keeps --force backups outside the skill root (FR4.1-FR4.4).

Labels: bắt-lỗi = goes through the CLI `install` that exists at df875ce and goes red by exit code/assertion;
đơn-vị-hàm-mới = a new helper; tương-đương = same result as before."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = "skills/data-quality-audit"


def make_link(link: Path, target: Path) -> bool:
    """Directory junction on Windows (no privilege), symlink elsewhere; False when the machine cannot create one."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, ImportError, NotImplementedError):
        return False


def drop_link(link: Path) -> None:
    try:
        os.rmdir(link) if os.name == "nt" else os.unlink(link)
    except OSError:
        pass


class InstallSafeTests(unittest.TestCase):
    def cli(self, env, *args):
        merged = dict(os.environ)
        merged.update(env)
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), "install", *map(str, args)], cwd=ROOT, env=merged,
                              text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def home(self, base):
        home = Path(base) / "home"
        home.mkdir()
        return home, {"HOME": str(home), "USERPROFILE": str(home)}

    def test_bat_loi_user_root_link_exits_2_and_writes_nothing_outside(self):
        """bắt-lỗi: ~/.agents/skills is a link to a folder elsewhere -> exit 2 naming the real target; nothing lands there (today: exit 0, files written through)."""
        with tempfile.TemporaryDirectory() as t:
            home, env = self.home(t)
            (home / ".agents").mkdir()
            outside = Path(t) / "outside"
            outside.mkdir()
            link = home / ".agents" / "skills"
            if not make_link(link, outside):
                self.skipTest("cannot create a directory link here")
            try:
                run = self.cli(env, SKILL, "--agent", "codex", "--user")
                self.assertEqual(2, run.returncode, run.stdout + run.stderr)
                self.assertIn(os.path.realpath(outside), run.stderr)
                self.assertEqual([], list(outside.iterdir()), "install must not write through the root link")
            finally:
                drop_link(link)

    def test_bat_loi_user_parent_of_root_link_exits_2(self):
        """bắt-lỗi: ~/.agents (the parent of the skill root) is a link -> exit 2 (today: exit 0)."""
        with tempfile.TemporaryDirectory() as t:
            home, env = self.home(t)
            outside = Path(t) / "outside"
            (outside / "skills").mkdir(parents=True)
            link = home / ".agents"
            if not make_link(link, outside):
                self.skipTest("cannot create a directory link here")
            try:
                run = self.cli(env, SKILL, "--agent", "codex", "--user")
                self.assertEqual(2, run.returncode, run.stdout + run.stderr)
                self.assertIn(os.path.realpath(outside), run.stderr)
                self.assertEqual([], list((outside / "skills").iterdir()))
            finally:
                drop_link(link)

    def test_bat_loi_user_allow_root_link_installs_and_prints_real_target(self):
        """bắt-lỗi: with --allow-root-link the install goes ahead (exit 0) and the real target is printed (today the flag does not exist: argparse exit 2)."""
        with tempfile.TemporaryDirectory() as t:
            home, env = self.home(t)
            (home / ".agents").mkdir()
            outside = Path(t) / "outside"
            outside.mkdir()
            link = home / ".agents" / "skills"
            if not make_link(link, outside):
                self.skipTest("cannot create a directory link here")
            try:
                run = self.cli(env, SKILL, "--agent", "codex", "--user", "--allow-root-link")
                self.assertEqual(0, run.returncode, run.stdout + run.stderr)
                self.assertIn(os.path.realpath(outside), run.stdout)
                self.assertTrue((outside / "data-quality-audit" / "SKILL.md").is_file())
            finally:
                drop_link(link)

    def test_bat_loi_workspace_root_link_exits_2(self):
        """bắt-lỗi: <workspace>/.claude/skills is a link -> exit 2 (today: exit 0); the flag lets it through."""
        with tempfile.TemporaryDirectory() as t:
            ws = Path(t) / "ws"
            (ws / ".claude").mkdir(parents=True)
            outside = Path(t) / "outside"
            outside.mkdir()
            link = ws / ".claude" / "skills"
            if not make_link(link, outside):
                self.skipTest("cannot create a directory link here")
            try:
                run = self.cli({}, SKILL, "--agent", "claude", "--workspace", ws)
                self.assertEqual(2, run.returncode, run.stdout + run.stderr)
                self.assertIn(os.path.realpath(outside), run.stderr)
                self.assertEqual([], list(outside.iterdir()))
                ok = self.cli({}, SKILL, "--agent", "claude", "--workspace", ws, "--allow-root-link")
                self.assertEqual(0, ok.returncode, ok.stdout + ok.stderr)
            finally:
                drop_link(link)

    def test_bat_loi_dangling_destination_exits_1_without_traceback(self):
        """bắt-lỗi: dest is a dangling link -> exit 1, `symlink destination refused`, no Traceback, with or without --force (today: traceback)."""
        with tempfile.TemporaryDirectory() as t:
            home, env = self.home(t)
            skills = home / ".agents" / "skills"
            skills.mkdir(parents=True)
            gone = Path(t) / "gone"
            gone.mkdir()
            dest = skills / "data-quality-audit"
            if not make_link(dest, gone):
                self.skipTest("cannot create a directory link here")
            gone.rmdir()
            try:
                for extra in ([], ["--force"]):
                    run = self.cli(env, SKILL, "--agent", "codex", "--user", *extra)
                    self.assertEqual(1, run.returncode, run.stdout + run.stderr)
                    self.assertIn("symlink destination refused", run.stderr)
                    self.assertNotIn("Traceback", run.stderr)
                self.assertEqual(["data-quality-audit"], sorted(p.name for p in skills.iterdir()))
            finally:
                drop_link(dest)

    def test_bat_loi_force_backup_is_outside_the_skill_root(self):
        """bắt-lỗi: --force leaves the backup under <parent of skill root>/.skill-studio-backups/, never inside the root (today: <name>.backup-<UTC> beside the skill)."""
        with tempfile.TemporaryDirectory() as t:
            home, env = self.home(t)
            skills = home / ".agents" / "skills"
            skills.mkdir(parents=True)
            self.assertEqual(0, self.cli(env, SKILL, "--agent", "codex", "--user").returncode)
            (skills / "data-quality-audit" / "marker.txt").write_text("old", encoding="utf-8")
            run = self.cli(env, SKILL, "--agent", "codex", "--user", "--force")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertEqual(["data-quality-audit"], sorted(p.name for p in skills.iterdir()), "the skill root must hold only the skill")
            backups = list((home / ".agents" / ".skill-studio-backups").iterdir())
            self.assertEqual(1, len(backups), backups)
            self.assertTrue(backups[0].name.startswith("data-quality-audit-"))
            self.assertEqual("old", (backups[0] / "marker.txt").read_text(encoding="utf-8"))
            self.assertIn(str(backups[0]), run.stdout)
            self.assertFalse((skills / "data-quality-audit" / "marker.txt").exists())

    def test_tuong_duong_plain_install_unchanged(self):
        """tương-đương: with no link anywhere install behaves as before (exit 0, same message, no backup folder)."""
        with tempfile.TemporaryDirectory() as t:
            home, env = self.home(t)
            (home / ".agents").mkdir()
            run = self.cli(env, SKILL, "--agent", "codex", "--user")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertIn("Installed data-quality-audit for codex at ", run.stdout)
            self.assertFalse((home / ".agents" / ".skill-studio-backups").exists())

    def test_don_vi_ham_moi_move_aside_copies_across_devices(self):
        """đơn-vị-hàm-mới: move_aside falls back to copy-then-delete when rename fails (EXDEV), and keeps the old skill when the copy fails."""
        from unittest import mock
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _engine
        studio_dist = _engine.dist
        with tempfile.TemporaryDirectory() as t:
            src, dst = Path(t) / "src", Path(t) / "dst"
            src.mkdir()
            (src / "a.txt").write_text("a", encoding="utf-8")
            with mock.patch.object(os, "rename", side_effect=OSError(18, "cross-device")):
                studio_dist.move_aside(src, dst)
            self.assertEqual(("a", False), ((dst / "a.txt").read_text(encoding="utf-8"), src.exists()))
            src.mkdir()
            (src / "a.txt").write_text("a", encoding="utf-8")
            dst2 = Path(t) / "dst2"
            with mock.patch.object(os, "rename", side_effect=OSError(18, "cross-device")), \
                    mock.patch.object(shutil, "copytree", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    studio_dist.move_aside(src, dst2)
            self.assertEqual((True, False), ((src / "a.txt").is_file(), dst2.exists()))


if __name__ == "__main__":
    unittest.main()
