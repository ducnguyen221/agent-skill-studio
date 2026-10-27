"""SPR-01 TK3: cloud tag recognition, `package` without rglob, `fmt --fix` exclusive backups (FR2.9 package/fmt, FR3.1, FR3.2, FR5.1-FR5.5).

Labels: bắt-lỗi = goes through the CLI or a function that exists at df875ce and goes red by assertion/exit code;
đơn-vị-hàm-mới = a new helper/parameter; tương-đương = same result as before."""
import contextlib
import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402

studio = _engine.engine
studio_const = _engine.const  # constants live in studio_const (SPR-02 TK4a)
studio_fs = _engine.fs  # file-system helpers live in studio_fs
studio_fmt = _engine.fmt  # SPR-02 TK4c

REPARSE = 0x400
TAG_SYMLINK, TAG_MOUNT, TAG_CLOUD, TAG_CLOUD_CHILD, TAG_ODD = 0xA000000C, 0xA0000003, 0x9000001A, 0x9000101A, 0x99


def fake_stat(attrs=None, tag=None):
    fields = {"st_mode": stat.S_IFREG | 0o644, "st_size": 0}
    if attrs is not None:
        fields["st_file_attributes"] = attrs
    if tag is not None:
        fields["st_reparse_tag"] = tag
    return SimpleNamespace(**fields)


class Entry:
    def __init__(self, st):
        self._st = st

    def stat(self, follow_symlinks=True):
        return self._st


def can_link(kind):
    with tempfile.TemporaryDirectory() as t:
        base = Path(t)
        (base / "a").write_bytes(b"x")
        try:
            if kind == "hard":
                os.link(base / "a", base / "b")
            else:
                os.symlink(base / "a", base / "b")
            return True
        except (OSError, NotImplementedError):
            return False


def dir_link(test, link, target):
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if link.exists():
            return
    test.skipTest("cannot create a symlink or junction here")


class CloudTagTests(unittest.TestCase):
    def cloud(self, st, via="path"):
        with mock.patch.object(studio_const, "CLOUD_ATTRS_AVAILABLE", True):
            if via == "path":
                with mock.patch.object(os, "lstat", return_value=st):
                    return studio_fs.path_is_cloud("x")
            return studio_fs.entry_is_cloud(Entry(st))

    def test_bat_loi_cloud_tag_is_cloud_other_reparse_tags_are_not(self):
        """bắt-lỗi: reparse tags through path_is_cloud and entry_is_cloud."""
        cases = ((REPARSE, TAG_SYMLINK, False), (REPARSE, TAG_MOUNT, False), (REPARSE, TAG_CLOUD, True),
                 (REPARSE, TAG_CLOUD_CHILD, True), (REPARSE, TAG_ODD, False))
        for attrs, tag, want in cases:
            for via in ("path", "entry"):
                with self.subTest(tag=hex(tag), via=via):
                    self.assertEqual(self.cloud(fake_stat(attrs, tag), via), want)

    def test_tuong_duong_no_attributes_means_not_cloud(self):
        """tương-đương (green at df875ce, a guard against regression): FR5.5, a platform without st_file_attributes/st_reparse_tag keeps the old answer."""
        for via in ("path", "entry"):
            self.assertFalse(self.cloud(fake_stat(), via))
            self.assertFalse(self.cloud(fake_stat(REPARSE), via), "reparse point without a tag")

    def test_bat_loi_pinned_alone_is_not_a_placeholder(self):
        """bắt-lỗi: FR5.4."""
        for via in ("path", "entry"):
            self.assertFalse(self.cloud(fake_stat(0x80000), via))
            self.assertTrue(self.cloud(fake_stat(0x80000 | 0x400000), via), "PINNED|RECALL_ON_DATA_ACCESS")
            for bit in (0x40000, 0x400000, 0x1000, 0x100000):
                self.assertTrue(self.cloud(fake_stat(bit), via), hex(bit))

    def test_bat_loi_mask_has_no_pinned_bit(self):
        """bắt-lỗi: CLOUD_ATTR_MASK."""
        self.assertEqual(studio_const.CLOUD_ATTR_MASK & 0x80000, 0)

    def test_tuong_duong_is_link_unchanged_for_every_reparse_tag(self):
        """tương-đương: is_link still true for any reparse point, cloud included (FR5.1)."""
        for tag in (TAG_SYMLINK, TAG_MOUNT, TAG_CLOUD, TAG_CLOUD_CHILD, TAG_ODD):
            with self.subTest(tag=hex(tag)), mock.patch.object(os, "lstat", return_value=fake_stat(REPARSE, tag)):
                self.assertTrue(studio_fs.is_link(Path("x")))
        with mock.patch.object(os, "lstat", return_value=fake_stat()):
            self.assertFalse(studio_fs.is_link(Path("x")))


def make_skill(base: Path) -> Path:
    dest = base / "data-quality-audit"
    shutil.copytree(ROOT / "skills" / "data-quality-audit", dest)
    return dest


def package(skill, out, extra=()):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = studio.main(["package", str(skill), "--out", str(out), *extra])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
    return code, stdout.getvalue(), stderr.getvalue()


class PackageTreeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.skill = make_skill(self.tmp / "src")
        self.out = self.tmp / "dist"

    def names(self):
        with zipfile.ZipFile(self.out / "data-quality-audit.zip") as zf:
            return zf.namelist()

    def test_tuong_duong_clean_tree_packages_and_skips_evals_tests(self):
        """tương-đương: SKIP_DIRS still filtered."""
        (self.skill / "evals").mkdir()
        (self.skill / "evals" / "x.txt").write_text("e")
        (self.skill / "tests").mkdir()
        (self.skill / "tests" / "t.py").write_text("t")
        code, out, err = package(self.skill, self.out)
        self.assertEqual(code, 0, out + err)
        self.assertFalse([n for n in self.names() if "evals/" in n or "tests/" in n])

    def test_bat_loi_junction_in_tree_is_pack_error(self):
        """bắt-lỗi: a link/junction inside the skill is ERROR PACK and is not entered."""
        target = self.tmp / "outside"
        target.mkdir()
        (target / "canary.txt").write_text("CANARY")
        dir_link(self, self.skill / "refs-link", target)
        code, out, err = package(self.skill, self.out)
        self.assertEqual(code, 1, out + err)
        self.assertIn("PACK", out + err)
        self.assertFalse((self.out / "data-quality-audit.zip").exists())

    def test_bat_loi_cloud_placeholder_is_pack_error_and_never_packaged(self):
        """bắt-lỗi: a cloud placeholder (path_is_cloud / entry_is_cloud say so, both exist at df875ce) gives PACK, exit 1 and no zip."""
        (self.skill / "references").mkdir(exist_ok=True)
        (self.skill / "references" / "ghost.md").write_text("x")
        real_entry, real_path = studio_fs.entry_is_cloud, studio_fs.path_is_cloud
        with mock.patch.object(studio_fs, "entry_is_cloud", lambda e: e.name == "ghost.md" or real_entry(e)), \
                mock.patch.object(studio_fs, "path_is_cloud", lambda p: Path(p).name == "ghost.md" or real_path(p)):
            code, out, err = package(self.skill, self.out)
        self.assertEqual(code, 1, out + err)
        self.assertIn("PACK", out + err)
        self.assertFalse((self.out / "data-quality-audit.zip").exists())

    def test_don_vi_ham_moi_cloud_placeholder_is_never_opened(self):
        """đơn-vị-hàm-mới: a cloud placeholder gives PACK and no open_nofollow_read of it."""
        (self.skill / "references").mkdir(exist_ok=True)
        (self.skill / "references" / "ghost.md").write_text("x")
        real = studio_fs.entry_is_cloud
        opened = []
        real_open = studio_fs.open_nofollow_read

        def spy(path, *a, **k):
            opened.append(Path(path).name)
            return real_open(path, *a, **k)

        with mock.patch.object(studio_fs, "entry_is_cloud", lambda e: e.name == "ghost.md" or real(e)), \
                mock.patch.object(studio_fs, "open_nofollow_read", spy):
            code, out, err = package(self.skill, self.out)
        self.assertEqual(code, 1, out + err)
        self.assertIn("PACK", out + err)
        self.assertNotIn("ghost.md", opened)

    def test_bat_loi_scan_limit_is_pack_error_not_a_short_package(self):
        """bắt-lỗi: a tree above the scan limit is refused, not packaged short."""
        with mock.patch.object(studio_const, "DOCTOR_MAX_FILES_PER_SKILL", 3):
            code, out, err = package(self.skill, self.out)
        self.assertEqual(code, 1, out + err)
        self.assertIn("PACK", out + err)
        self.assertFalse((self.out / "data-quality-audit.zip").exists())

    def test_bat_loi_depth_limit_is_pack_error(self):
        """bắt-lỗi: depth limit."""
        with mock.patch.object(studio_const, "DOCTOR_MAX_SKILL_DEPTH", 1):
            code, out, err = package(self.skill, self.out)
        self.assertEqual(code, 1, out + err)
        self.assertIn("PACK", out + err)

    def test_bat_loi_zone_named_folder_is_pack_error(self):
        """bắt-lỗi: a folder named like a cloud/secret zone is not entered and not shipped silently."""
        (self.skill / "OneDrive").mkdir()
        (self.skill / "OneDrive" / "a.txt").write_text("a")
        code, out, err = package(self.skill, self.out)
        self.assertEqual(code, 1, out + err)
        self.assertIn("PACK", out + err)

    def test_tuong_duong_sz2_stays_warn(self):
        """tương-đương: every SZ2 finding in studio.py is WARN (validate/doctor unchanged)."""
        src = _engine.engine_source()
        levels = [m.group(1) for m in re.finditer(r'emit\("(\w+)", "SZ2"', src)]
        self.assertTrue(levels)
        self.assertEqual(set(levels), {"WARN"})

    @unittest.skipUnless(can_link("hard"), "cannot create hard links here")
    def test_bat_loi_hard_linked_file_in_skill_is_pack_error(self):
        """bắt-lỗi: a second name for a packaged file is refused (open_nofollow_read single_link)."""
        outside = self.tmp / "outside.txt"
        outside.write_text("CANARY")
        os.link(outside, self.skill / "extra.txt")
        code, out, err = package(self.skill, self.out)
        self.assertEqual(code, 1, out + err)
        self.assertIn("PACK", out + err)


def fmt(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = studio.main(["fmt", *argv])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue()


DIRTY = "---\nname: demo-skill\ndescription: Checks a toy example. Use when testing fmt.\n---\n\n# Demo \n\nBody text here.\n"


class FmtBackupExclusiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.path = self.tmp / "SKILL.md"
        self.path.write_bytes(DIRTY.encode("utf-8"))

    def fixed_names(self):
        return sorted(p.name for p in self.tmp.iterdir() if ".bak-" in p.name)

    @unittest.skipUnless(can_link("hard"), "cannot create hard links here")
    def test_tuong_duong_planted_hard_link_backup_is_not_written_through(self):
        """tương-đương (green at df875ce, which already avoided the existing name): a hard link at the first .bak name must survive; the backup takes the next suffix."""
        outside = self.tmp / "outside.txt"
        outside.write_bytes(b"CANARY")
        with mock.patch.object(studio_fmt, "datetime") as dt:
            dt.now.return_value.strftime.return_value = "STAMP"
            os.link(outside, self.tmp / "SKILL.md.bak-STAMP")
            code, out, err = fmt("--fix", str(self.path))
        self.assertEqual(code, 0, out + err)
        self.assertEqual(outside.read_bytes(), b"CANARY")
        self.assertEqual((self.tmp / "SKILL.md.bak-STAMP").read_bytes(), b"CANARY")
        self.assertEqual((self.tmp / "SKILL.md.bak-STAMP-1").read_bytes(), DIRTY.encode("utf-8"))

    @unittest.skipUnless(can_link("sym"), "cannot create symlinks here")
    def test_bat_loi_planted_symlink_backup_is_not_written_through(self):
        """bắt-lỗi: same with a (dangling) symlink at the first name."""
        victim = self.tmp / "victim.txt"
        with mock.patch.object(studio_fmt, "datetime") as dt:
            dt.now.return_value.strftime.return_value = "STAMP"
            os.symlink(victim, self.tmp / "SKILL.md.bak-STAMP")
            code, out, err = fmt("--fix", str(self.path))
        self.assertEqual(code, 0, out + err)
        self.assertFalse(victim.exists())
        self.assertTrue((self.tmp / "SKILL.md.bak-STAMP-1").is_file())

    def test_bat_loi_failed_copy_keeps_a_preexisting_backup_name(self):
        """bắt-lỗi: a copy that fails leaves the file already at the first name untouched and removes only its own."""
        with mock.patch.object(studio_fmt, "datetime") as dt:
            dt.now.return_value.strftime.return_value = "STAMP"
            (self.tmp / "SKILL.md.bak-STAMP").write_bytes(b"PREEXISTING")
            with mock.patch.object(shutil, "copyfileobj", side_effect=OSError(28, "no space")):
                code, out, err = fmt("--fix", str(self.path))
        self.assertEqual(code, 2, out + err)
        self.assertEqual((self.tmp / "SKILL.md.bak-STAMP").read_bytes(), b"PREEXISTING")
        self.assertEqual(self.fixed_names(), ["SKILL.md.bak-STAMP"])
        self.assertEqual(self.path.read_bytes(), DIRTY.encode("utf-8"))

    def test_don_vi_ham_moi_source_is_read_with_open_nofollow_read(self):
        """đơn-vị-hàm-mới: fmt reads the .md through the no-follow helper."""
        seen = []
        real = studio_fs.open_nofollow_read

        def spy(path, *a, **k):
            seen.append(Path(path).name)
            return real(path, *a, **k)

        with mock.patch.object(studio_fs, "open_nofollow_read", spy):
            self.assertEqual(fmt("--fix", str(self.path))[0], 0)
        self.assertIn("SKILL.md", seen)


class FmtDirSymlinkTests(unittest.TestCase):
    @unittest.skipUnless(can_link("sym"), "cannot create symlinks here")
    def test_bat_loi_dir_symlink_without_md_name_is_reported(self):
        """bắt-lỗi: a symlink to a directory is `skipped (link)`, whatever its name (FR3.2)."""
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            real = base / "real"
            real.mkdir()
            (real / "a.md").write_bytes(b"# A  \n")
            outer = base / "outer"
            outer.mkdir()
            os.symlink(real, outer / "linked", target_is_directory=True)
            code, out, err = fmt("--fix", str(outer))
            self.assertIn("skipped (link)", out + err)
            self.assertEqual((real / "a.md").read_bytes(), b"# A  \n")


if __name__ == "__main__":
    unittest.main()
