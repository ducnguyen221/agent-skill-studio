"""SPR-02 TK7 (RQ-009, FR7): three holes where the engine still looked through a link or read a cloud placeholder.

(a) `iter_md`, `skill_dirs`, `_is_dir_quiet` must not stat or enter the target of a link (symlink, junction); (b) `package`/`install`
decide about `SKILL.md` before reading it; (c) `move_aside`, on another device, does not copy through a link inside the old tree.
Most tests use spies and mocks so that they run everywhere; the `skipUnless` ones create a real symlink or junction (CI Windows).
Labels: bắt-lỗi = red on the parent commit by assertion/exit code; tương-đương = green before and after (guard).
"""
from __future__ import annotations

import errno
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

ROOT = E.ROOT
SKILL_SRC = ROOT / "examples" / "data-quality-audit"
SKILL_TEXT = "---\nname: %s\ndescription: Checks a toy example. Use when testing the link holes.\n---\n\n# Title\n\nShort body.\n"


def make_dir_link(link: Path, target: Path) -> bool:
    """A directory symlink, or a junction on Windows; False when the machine can make neither."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return True
        except (OSError, ImportError):
            pass
    return False


def drop_dir_link(link: Path) -> None:
    try:
        os.rmdir(link) if os.name == "nt" else os.unlink(link)
    except OSError:
        pass


def can_link() -> bool:
    with tempfile.TemporaryDirectory() as t:
        target = Path(t) / "target"
        target.mkdir()
        link = Path(t) / "link"
        ok = make_dir_link(link, target)
        if ok:
            drop_dir_link(link)
        return ok


def can_file_symlink() -> bool:
    with tempfile.TemporaryDirectory() as t:
        try:
            os.symlink(str(Path(t) / "a"), str(Path(t) / "b"))
            return True
        except (OSError, NotImplementedError):
            return False


class LinkedEntries:
    """os.scandir whose entries named in `links` behave like symlinks to a folder: is_symlink() is True, is_dir(follow_symlinks=False)
    is False, and every call that would follow the link (is_dir()/is_file()/stat() with the default) is recorded in `followed`."""

    def __init__(self, links):
        self.links = set(links)
        self.followed: list = []
        self._real = os.scandir

    def __call__(self, path="."):
        outer = self
        inner = self._real(path)

        class Entry:
            def __init__(self, entry):
                self._e = entry
                self._link = entry.name in outer.links

            def __getattr__(self, name):
                return getattr(self._e, name)

            def is_symlink(self):
                return self._link or self._e.is_symlink()

            def is_dir(self, *, follow_symlinks=True):
                if self._link:
                    if follow_symlinks:
                        outer.followed.append(("is_dir", self._e.path))
                        return True
                    return False
                return self._e.is_dir(follow_symlinks=follow_symlinks)

            def is_file(self, *, follow_symlinks=True):
                if self._link:
                    if follow_symlinks:
                        outer.followed.append(("is_file", self._e.path))
                        return False
                    return False
                return self._e.is_file(follow_symlinks=follow_symlinks)

            def stat(self, *, follow_symlinks=True):
                if self._link and follow_symlinks:
                    outer.followed.append(("stat", self._e.path))
                return self._e.stat(follow_symlinks=follow_symlinks)

        class Scan:
            def __enter__(self_inner):
                inner.__enter__()
                return self_inner

            def __exit__(self_inner, *exc):
                return inner.__exit__(*exc)

            def __iter__(self_inner):
                return (Entry(e) for e in inner)

            def close(self_inner):
                inner.close()

        return Scan()


class StatSpy:
    """Record every os.stat call that follows links, as the path text."""

    def __init__(self):
        self.calls: list = []
        self._real = os.stat

    def __call__(self, path, *a, **k):
        if not isinstance(path, int) and k.get("follow_symlinks", True):
            self.calls.append(os.fspath(path))
        return self._real(path, *a, **k)


def write_md(path: Path, text: str = "# T\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # bytes: Path.write_text has no newline= before Python 3.10


class IterMdLinkTests(unittest.TestCase):
    def test_bat_loi_iter_md_does_not_follow_a_symlink_entry(self):
        """bắt-lỗi: a symlink entry in a folder is reported as `link` without asking what it points at (today: entry.is_dir() stats the target)."""
        with tempfile.TemporaryDirectory() as t:
            base = Path(t) / "docs"
            write_md(base / "real" / "a.md")
            write_md(base / "pointed" / "b.md")  # stands in for the target behind the link
            spy = LinkedEntries({"pointed"})
            skipped: list = []
            with mock.patch.object(os, "scandir", spy):
                files = E.fmt.iter_md([base], False, None, skipped)
            self.assertEqual([], spy.followed, "the target of a link must not be asked about")
            self.assertEqual(["a.md"], [p.name for p in files])
            self.assertIn(("pointed", "link"), [(Path(s["path"]).name, s["reason"]) for s in skipped])

    @unittest.skipUnless(can_link(), "cannot create a directory link here")
    def test_tuong_duong_iter_md_real_link_is_skipped(self):
        """tương-đương: a real symlink or junction to a folder of Markdown is reported as `link` and none of its files is listed."""
        with tempfile.TemporaryDirectory() as t:
            base = Path(t) / "docs"
            write_md(base / "a.md")
            outside = Path(t) / "outside"
            write_md(outside / "secret.md")
            link = base / "linked"
            self.assertTrue(make_dir_link(link, outside))
            try:
                skipped: list = []
                files = E.fmt.iter_md([base], False, None, skipped)
            finally:
                drop_dir_link(link)
            self.assertEqual(["a.md"], [p.name for p in files])
            self.assertIn(("linked", "link"), [(Path(s["path"]).name, s["reason"]) for s in skipped])


class SkillDirsLinkTests(unittest.TestCase):
    def make_root(self, base: Path) -> Path:
        root = base / "repo"
        for name in ("good", "linked"):
            write_md(root / "skills" / name / "SKILL.md", SKILL_TEXT % name)
        return root

    def test_bat_loi_skill_dirs_skips_a_folder_that_is_a_link(self):
        """bắt-lỗi: a folder under skills/ that is a link (fs.is_link) is neither listed nor stat-ed (today: x.is_dir() follows it and lists it)."""
        with tempfile.TemporaryDirectory() as t:
            root = self.make_root(Path(t))
            linked = os.path.normcase(str(root / "skills" / "linked"))
            real_is_link = E.fs.is_link
            spy = StatSpy()
            with mock.patch.object(E.fs, "is_link", lambda p: os.path.normcase(os.fspath(p)) == linked or real_is_link(p)), \
                    mock.patch.object(os, "stat", spy):
                found = E.fs.skill_dirs(root)
            self.assertEqual(["good"], [p.name for p in found])
            self.assertEqual([], [c for c in spy.calls if os.path.normcase(c) == linked], "the link target must not be stat-ed")

    def test_bat_loi_skill_dirs_does_not_follow_a_symlink_entry(self):
        """bắt-lỗi: a symlink entry is skipped without asking what it points at (today: the target is stat-ed)."""
        with tempfile.TemporaryDirectory() as t:
            root = self.make_root(Path(t))
            spy = LinkedEntries({"linked"})
            with mock.patch.object(os, "scandir", spy):
                found = E.fs.skill_dirs(root)
            self.assertEqual(["good"], [p.name for p in found])

    def test_bat_loi_skill_dirs_skips_a_cloud_placeholder_folder(self):
        """bắt-lỗi: a folder the listing reports as a cloud placeholder is not listed, and its SKILL.md is not asked for (today: listed)."""
        with tempfile.TemporaryDirectory() as t:
            root = self.make_root(Path(t))
            cloud = os.path.normcase(str(root / "skills" / "linked"))
            real_entry_is_cloud = E.fs.entry_is_cloud
            with mock.patch.object(E.fs, "entry_is_cloud", lambda e: os.path.normcase(e.path) == cloud or real_entry_is_cloud(e)):
                found = E.fs.skill_dirs(root)
            self.assertEqual(["good"], [p.name for p in found])

    def test_bat_loi_skill_dirs_refuses_a_skills_folder_that_is_a_link(self):
        """bắt-lỗi: when `skills` itself is a link nothing under it is listed (today: it is entered)."""
        with tempfile.TemporaryDirectory() as t:
            root = self.make_root(Path(t))
            skills = os.path.normcase(str(root / "skills"))
            real_is_link = E.fs.is_link
            with mock.patch.object(E.fs, "is_link", lambda p: os.path.normcase(os.fspath(p)) == skills or real_is_link(p)):
                self.assertEqual([], E.fs.skill_dirs(root))

    @unittest.skipUnless(can_link(), "cannot create a directory link here")
    def test_bat_loi_skill_dirs_real_link_is_not_listed(self):
        """bắt-lỗi: a real symlink or junction under skills/ pointing at a folder with SKILL.md is not listed (today: listed)."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "repo"
            write_md(root / "skills" / "good" / "SKILL.md", SKILL_TEXT % "good")
            outside = Path(t) / "outside"
            write_md(outside / "SKILL.md", SKILL_TEXT % "outside")
            link = root / "skills" / "linked"
            self.assertTrue(make_dir_link(link, outside))
            try:
                found = E.fs.skill_dirs(root)
            finally:
                drop_dir_link(link)
            self.assertEqual(["good"], [p.name for p in found])


class IsDirQuietLinkTests(unittest.TestCase):
    def test_bat_loi_is_dir_quiet_is_false_for_a_link_and_does_not_stat_it(self):
        """bắt-lỗi: a path that is a link (fs.is_link) is not a directory for this test and its target is not stat-ed (today: Path.is_dir() follows it)."""
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t) / "folder"
            folder.mkdir()
            key = os.path.normcase(str(folder))
            real_is_link = E.fs.is_link
            spy = StatSpy()
            with mock.patch.object(E.fs, "is_link", lambda p: os.path.normcase(os.fspath(p)) == key or real_is_link(p)), \
                    mock.patch.object(os, "stat", spy):
                result = E.fs._is_dir_quiet(folder)
            self.assertFalse(result)
            self.assertEqual([], [c for c in spy.calls if os.path.normcase(c) == key])

    def test_bat_loi_is_dir_quiet_is_false_for_a_cloud_placeholder(self):
        """bắt-lỗi: a path that carries cloud attributes (fs.path_is_cloud) is not a directory for this test (today: Path.is_dir() reads it)."""
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t) / "folder"
            folder.mkdir()
            key = os.path.normcase(str(folder))
            real = E.fs.path_is_cloud
            with mock.patch.object(E.fs, "path_is_cloud", lambda p: os.path.normcase(os.fspath(p)) == key or real(p)):
                self.assertFalse(E.fs._is_dir_quiet(folder))

    def test_tuong_duong_is_dir_quiet_plain_cases(self):
        """tương-đương: a real folder is True; a file, a missing path and an over-long name are False and nothing raises."""
        with tempfile.TemporaryDirectory() as t:
            folder, file = Path(t) / "folder", Path(t) / "file.txt"
            folder.mkdir()
            file.write_text("x", encoding="utf-8")
            self.assertTrue(E.fs._is_dir_quiet(folder))
            self.assertFalse(E.fs._is_dir_quiet(file))
            self.assertFalse(E.fs._is_dir_quiet(Path(t) / "missing"))
            self.assertFalse(E.fs._is_dir_quiet(Path(t) / ("x" * 5000)))

    def test_bat_loi_is_dir_quiet_any_oserror_is_not_a_directory(self):
        """bắt-lỗi: an OSError from lstat that pathlib does not swallow (POSIX ENAMETOOLONG, errno 36) makes the answer False, never a crash (CI ubuntu on 913306a: is_link raised)."""
        import errno
        with tempfile.TemporaryDirectory() as t:
            for code in (errno.ENAMETOOLONG, errno.EACCES):
                with self.subTest(errno=code), mock.patch.object(os, "lstat", side_effect=OSError(code, "mock")),                         mock.patch.object(os, "stat", side_effect=OSError(code, "mock")):  # Path.is_symlink goes through either, by Python version
                    self.assertFalse(E.fs._is_dir_quiet(Path(t) / "x"))

    @unittest.skipUnless(can_link(), "cannot create a directory link here")
    def test_bat_loi_is_dir_quiet_real_link_is_false(self):
        """bắt-lỗi: a real symlink or junction to a folder is not a directory for this test (today: True)."""
        with tempfile.TemporaryDirectory() as t:
            target = Path(t) / "target"
            target.mkdir()
            link = Path(t) / "link"
            self.assertTrue(make_dir_link(link, target))
            try:
                self.assertFalse(E.fs._is_dir_quiet(link))
            finally:
                drop_dir_link(link)


class ProbeErrorTests(unittest.TestCase):
    """An OSError while probing a path the user gave (POSIX ENAMETOOLONG; pathlib re-raises it) is never a crash: the path is simply not a link / not a folder (1a RF-T6)."""

    def too_long(self):
        import errno
        return mock.patch.object(Path, "is_symlink", side_effect=OSError(errno.ENAMETOOLONG, "File name too long"))

    def test_bat_loi_is_link_treats_oserror_as_not_a_link(self):
        """bắt-lỗi, LẬT ở SPR-03 TK9 (1a RF-T6 asserted False; now True): fs.is_link returns True when pathlib raises ENAMETOOLONG for the path
        (CI ubuntu on 138cbfa: it raised). Why flipped: a path that cannot be probed is no longer «not a link» — that failed open, and the callers
        (doctor, fmt, validate, package, install) went on as if it were an ordinary path (RQ-025 / RF-S4, SPEC FR13.1). Fails closed: the callers
        refuse or skip it with the report they have for a link. What stays: the next test, `parse_roots` still ends in «root not found»; replaced by
        tests/test_link_probe_fail_closed.py (test_is_link_fails_closed and the caller tests)."""
        with tempfile.TemporaryDirectory() as t, self.too_long():
            self.assertTrue(E.fs.is_link(Path(t) / "x"))

    def test_bat_loi_parse_roots_oserror_while_probing_is_root_not_found(self):
        """bắt-lỗi: doctor `--roots` with a path that cannot be probed (ENAMETOOLONG) ends in the old ValueError «root not found», not an OSError traceback."""
        with tempfile.TemporaryDirectory() as t, self.too_long():
            with self.assertRaises(ValueError) as caught:
                E.doctor.parse_roots(str(Path(t) / "x"), None, None)
            self.assertIn("root not found or not a directory", str(caught.exception))

    def test_bat_loi_parse_roots_oserror_from_os_stat_is_root_not_found(self):
        """bắt-lỗi: the same with os.stat/os.lstat failing for the root (as the CI test does)."""
        import errno
        real_stat, real_lstat = os.stat, os.lstat
        with tempfile.TemporaryDirectory() as t:
            bad = os.path.normcase(os.path.abspath(str(Path(t) / "x")))

            def guard(real):
                def wrapper(path, *a, **k):
                    if not isinstance(path, int) and os.path.normcase(os.path.abspath(os.fspath(path))) == bad:
                        raise OSError(errno.ENAMETOOLONG, "File name too long")
                    return real(path, *a, **k)
                return wrapper

            with mock.patch.object(os, "stat", guard(real_stat)), mock.patch.object(os, "lstat", guard(real_lstat)):
                with self.assertRaises(ValueError):
                    E.doctor.parse_roots(bad, None, None)

    def test_bat_loi_probes_added_by_tk7_survive_oserror(self):
        """bắt-lỗi: skill_dirs, ensure_distributable and iter_md (the other places TK7 asks is_link about a user path) raise nothing when the probe fails."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "repo"
            write_md(root / "skills" / "good" / "SKILL.md", SKILL_TEXT % "good")
            write_md(root / "docs" / "a.md")
            with self.too_long():
                E.fs.skill_dirs(root)
                files, findings = E.dist.ensure_distributable(root / "skills" / "good")
                E.fmt.iter_md([root / "docs"], False, None, [])


class PackagePrecheckTests(unittest.TestCase):
    def make_skill(self, base: Path) -> Path:
        folder = base / "toy"
        write_md(folder / "SKILL.md", SKILL_TEXT % "toy")
        return folder

    def run_precheck(self, folder: Path, patch_name: str):
        key = os.path.normcase(str(folder / "SKILL.md"))
        real = getattr(E.fs, patch_name)
        reads: list = []
        validated: list = []
        real_read_text = Path.read_text

        def read_spy(self_path, *a, **k):
            reads.append(os.path.normcase(str(self_path)))
            return real_read_text(self_path, *a, **k)

        real_validate = E.validate.validate_skill

        def validate_spy(path, *a, **k):
            validated.append(path)
            return real_validate(path, *a, **k)

        with mock.patch.object(E.fs, patch_name, lambda p, *a, **k: os.path.normcase(os.fspath(p)) == key or real(p, *a, **k)), \
                mock.patch.object(Path, "read_text", read_spy), mock.patch.object(E.validate, "validate_skill", validate_spy):
            files, findings = E.dist.ensure_distributable(folder)
        return files, findings, reads, validated, key

    def check(self, patch_name: str):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_skill(Path(t))
            files, findings, reads, validated, key = self.run_precheck(folder, patch_name)
            self.assertIn("PACK", [f["code"] for f in findings if f["level"] == "ERROR"], findings)
            self.assertEqual([], validated, "validate_skill reads SKILL.md; it must not run first")
            self.assertEqual([], [r for r in reads if r == key], "SKILL.md must not be read")
            self.assertEqual([], files)

    def test_bat_loi_package_precheck_does_not_read_a_linked_skill_md(self):
        """bắt-lỗi: SKILL.md that is a link (fs.is_link) -> ERROR PACK before validate_skill/read_text (today: read first)."""
        self.check("is_link")

    def test_bat_loi_package_precheck_does_not_read_a_cloud_skill_md(self):
        """bắt-lỗi: SKILL.md that carries cloud attributes (fs.path_is_cloud) -> ERROR PACK before validate_skill/read_text (today: read first)."""
        self.check("path_is_cloud")

    def test_bat_loi_package_precheck_refuses_skill_md_in_a_secret_zone_without_reading(self):
        """bắt-lỗi: input_file_problem says no (a zone or secret-looking name) -> ERROR PACK, SKILL.md not read (today: read first)."""
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_skill(Path(t))
            reads: list = []
            real_read_text = Path.read_text

            def read_spy(self_path, *a, **k):
                reads.append(self_path.name)
                return real_read_text(self_path, *a, **k)

            with mock.patch.object(E.fs, "input_file_problem", lambda p, *a, **k: "is inside a cloud zone; not read"), mock.patch.object(Path, "read_text", read_spy):
                _, findings = E.dist.ensure_distributable(folder)
            self.assertIn("PACK", [f["code"] for f in findings if f["level"] == "ERROR"], findings)
            self.assertNotIn("SKILL.md", reads)

    def test_tuong_duong_package_precheck_plain_skill_has_no_error(self):
        """tương-đương: an ordinary finished skill passes the precheck with the same files and no ERROR."""
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_skill(Path(t))
            files, findings = E.dist.ensure_distributable(folder)
            self.assertEqual([], [f for f in findings if f["level"] == "ERROR"], findings)
            self.assertEqual(["SKILL.md"], [p.name for p in files])

    @unittest.skipUnless(can_file_symlink(), "cannot create a symlink here")
    def test_bat_loi_package_real_symlinked_skill_md_exits_1_with_pack(self):
        """bắt-lỗi: SKILL.md that is a real symlink makes `package` exit 1 with PACK and no ZIP, and its target is never read."""
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t) / "toy"
            folder.mkdir()
            target = Path(t) / "real-skill.md"
            target.write_bytes((SKILL_TEXT % "toy").encode("utf-8"))
            os.symlink(str(target), str(folder / "SKILL.md"))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = E.engine.main(["package", str(folder), "--out", str(Path(t) / "out")])
            self.assertEqual(1, code, out.getvalue() + err.getvalue())
            self.assertIn("PACK", out.getvalue() + err.getvalue())
            self.assertFalse((Path(t) / "out" / "toy.zip").exists())


class MoveAsideLinkTests(unittest.TestCase):
    def exdev(self, *a, **k):
        raise OSError(errno.EXDEV, "cross-device")

    def make_old(self, base: Path) -> Path:
        old = base / "old"
        write_md(old / "SKILL.md", SKILL_TEXT % "old")
        write_md(old / "sub" / "keep.md", "kept\n")
        return old

    def test_bat_loi_move_aside_across_devices_refuses_a_link_inside_the_old_tree(self):
        """bắt-lỗi: on another device the old tree is scanned without following links, and a link inside it (fs.is_link) stops the move; the old tree stays whole (today: copied through)."""
        with tempfile.TemporaryDirectory() as t:
            old = self.make_old(Path(t))
            dst = Path(t) / "backup"
            key = os.path.normcase(str(old / "sub"))
            real_is_link = E.fs.is_link
            with mock.patch.object(os, "rename", self.exdev), \
                    mock.patch.object(E.fs, "is_link", lambda p: os.path.normcase(os.fspath(p)) == key or real_is_link(p)):
                with self.assertRaises(OSError):
                    E.dist.move_aside(old, dst)
            self.assertTrue((old / "sub" / "keep.md").is_file())
            self.assertTrue((old / "SKILL.md").is_file())
            self.assertFalse(dst.exists(), "nothing may be copied")

    def test_bat_loi_move_aside_across_devices_refuses_a_cloud_placeholder_inside(self):
        """bắt-lỗi: a cloud placeholder inside the old tree stops the cross-device move before any file is copied (today: copied, i.e. downloaded)."""
        with tempfile.TemporaryDirectory() as t:
            old = self.make_old(Path(t))
            dst = Path(t) / "backup"
            key = os.path.normcase(str(old / "SKILL.md"))
            real = E.fs.entry_is_cloud
            with mock.patch.object(os, "rename", self.exdev), \
                    mock.patch.object(E.fs, "entry_is_cloud", lambda e: os.path.normcase(e.path) == key or real(e)):
                with self.assertRaises(OSError):
                    E.dist.move_aside(old, dst)
            self.assertFalse(dst.exists())
            self.assertTrue((old / "SKILL.md").is_file())

    def test_tuong_duong_move_aside_across_devices_without_links_still_copies(self):
        """tương-đương: with no link inside, the cross-device move copies and removes the old tree as before."""
        with tempfile.TemporaryDirectory() as t:
            old = self.make_old(Path(t))
            dst = Path(t) / "backup"
            with mock.patch.object(os, "rename", self.exdev):
                E.dist.move_aside(old, dst)
            self.assertEqual("kept\n", (dst / "sub" / "keep.md").read_text(encoding="utf-8"))
            self.assertFalse(old.exists())

    def install(self, ws: Path, *extra):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = E.engine.main(["install", str(SKILL_SRC), "--agent", "claude", "--workspace", str(ws), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_bat_loi_install_force_old_tree_with_a_link_exits_1_and_keeps_it(self):
        """bắt-lỗi: `install --force` across devices with a link inside the old tree exits 1 with a plain message; the old Skill is untouched and no backup is made (today: exit 0, copied through)."""
        with tempfile.TemporaryDirectory() as t:
            ws = Path(os.path.realpath(t)) / "ws"  # install resolves the workspace: 8.3 short temp names must not make the mock miss
            dest = ws / ".claude" / "skills" / SKILL_SRC.name
            write_md(dest / "SKILL.md", "OLD\n")
            write_md(dest / "sub" / "keep.md", "kept\n")
            key = os.path.normcase(str(dest / "sub"))
            real_is_link = E.fs.is_link
            with mock.patch.object(os, "rename", self.exdev), \
                    mock.patch.object(E.fs, "is_link", lambda p: os.path.normcase(os.fspath(p)) == key or real_is_link(p)):
                code, out, err = self.install(ws, "--force")
            self.assertEqual(1, code, out + err)
            self.assertIn("link", err.lower())
            self.assertEqual("OLD\n", (dest / "SKILL.md").read_text(encoding="utf-8"))
            self.assertTrue((dest / "sub" / "keep.md").is_file())
            backups = ws / ".claude" / ".skill-studio-backups"
            self.assertEqual([], list(backups.iterdir()) if backups.exists() else [])

    @unittest.skipUnless(can_link(), "cannot create a directory link here")
    def test_bat_loi_install_force_real_junction_in_old_tree_exits_1(self):
        """bắt-lỗi: `install --force` across devices (rename mocked) with a real junction/symlink inside the old tree exits 1; nothing behind the link is copied."""
        with tempfile.TemporaryDirectory() as t:
            ws = Path(t) / "ws"
            dest = ws / ".claude" / "skills" / SKILL_SRC.name
            write_md(dest / "SKILL.md", "OLD\n")
            outside = Path(t) / "outside"
            write_md(outside / "canary.md", "CANARY\n")
            link = dest / "linked"
            self.assertTrue(make_dir_link(link, outside))
            try:
                with mock.patch.object(os, "rename", self.exdev):
                    code, out, err = self.install(ws, "--force")
                self.assertEqual(1, code, out + err)
                backups = ws / ".claude" / ".skill-studio-backups"
                self.assertEqual([], list(backups.iterdir()) if backups.exists() else [])
                self.assertTrue((outside / "canary.md").is_file())
                self.assertEqual("OLD\n", (dest / "SKILL.md").read_text(encoding="utf-8"))
            finally:
                drop_dir_link(link)


if __name__ == "__main__":
    unittest.main()
