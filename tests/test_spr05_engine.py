"""SPR-05 TK8 (FR11.1, FR11.2, FR11.3, SC1): the engine the curator accepts has every module `ENGINE_DEPS` lists, the engine files `package`/`install` ship are read once, and
the module check runs after the engine is loaded.

Labels: bắt-lỗi = red on a695479 by assertion. Every test goes through `curator.py`'s command line or a function that already existed there.

Run: python -X utf8 -m unittest tests.test_spr05_engine -v
"""
from __future__ import annotations

import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CURATOR_SCRIPTS = ROOT / "skills" / "skill-curator" / "scripts"
CURATOR_SKILL = ROOT / "skills" / "skill-curator"
SECRET_BYTES = b'API_KEY = "AKIA' + b'ABCDEFGHIJKLMNOP"\n'


def load_curator():
    spec = importlib.util.spec_from_file_location("curator_under_test", CURATOR_SCRIPTS / "curator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(args, cwd, env=None):
    merged = dict(os.environ)
    merged.pop("PYTHONPATH", None)
    merged.update(env or {})
    return subprocess.run([sys.executable, "-X", "utf8", *map(str, args)], cwd=str(cwd), env=merged, text=True, encoding="utf-8",
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class EngineCase(unittest.TestCase):
    def setUp(self):
        E.clear_caches()
        self.addCleanup(E.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="spr05engine_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def engine_copy(self, name="engine") -> Path:
        engine = self.tmp / name
        engine.mkdir(parents=True)
        for item in E.ENGINE_DIR.glob("studio*.py"):
            shutil.copy(item, engine / item.name)
        return engine

    def curator_home(self) -> Path:
        """A packaged-looking `scripts/` folder: the curator files, `ENGINE_DEPS` and a full `_engine/` next to them."""
        scripts = self.tmp / "home" / "scripts"
        scripts.mkdir(parents=True)
        for item in list(CURATOR_SCRIPTS.glob("*.py")) + [CURATOR_SCRIPTS / "ENGINE_DEPS"]:
            if not item.name.startswith("studio_"):
                shutil.copy(item, scripts / item.name)
        shutil.copytree(self.engine_copy("staging"), scripts / "_engine")
        return scripts

    def source_with_deps(self) -> Path:
        copy = self.tmp / "src" / "skill-curator"
        shutil.copytree(CURATOR_SKILL, copy, ignore=shutil.ignore_patterns("__pycache__"))
        return copy


class FindEngineTests(EngineCase):
    def test_engine_missing_a_listed_module_is_refused(self):
        """bắt-lỗi: FR11.1 a folder without `studio_scaffold.py` (listed in ENGINE_DEPS, absent from the old hard-coded eight) is not an engine."""
        curator = load_curator()
        engine = self.engine_copy()
        (engine / "studio_scaffold.py").unlink()
        with mock.patch.object(curator, "ENGINE_CANDIDATES", (engine,)):
            self.assertIsNone(curator.find_engine())

    def test_complete_engine_is_accepted(self):
        """tương-đương: the same copy with every module is found."""
        curator = load_curator()
        engine = self.engine_copy()
        with mock.patch.object(curator, "ENGINE_CANDIDATES", (engine,)):
            self.assertEqual(curator.find_engine(), engine)

    def test_missing_engine_deps_file_errors(self):
        """bắt-lỗi: FR11.1 / RF-P13 a copy without `ENGINE_DEPS` stops with a plain ERROR (exit 2), whatever the engine folder holds."""
        scripts = self.curator_home()
        (scripts / "ENGINE_DEPS").unlink()
        done = run([scripts / "curator.py", "catalog", "--help"], self.tmp)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("ERROR: engine list ENGINE_DEPS missing or unreadable in", done.stderr)
        self.assertIn("reinstall skill-curator", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_engine_deps_with_a_path_name_is_unreadable(self):
        """tương-đương: a line that is not a `studio_*.py` file name is refused as an unreadable list, never joined onto a path."""
        scripts = self.curator_home()
        (scripts / "ENGINE_DEPS").write_text("studio_const.py\n../evil.py\n", encoding="utf-8")
        done = run([scripts / "curator.py", "catalog", "--help"], self.tmp)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("missing or unreadable", done.stderr)


class ExtrasReadOnceTests(EngineCase):
    def spy_calls(self):
        return mock.patch.object(E.dist, "engine_extras", wraps=E.dist.engine_extras)

    def test_package_asks_for_the_engine_files_once(self):
        """bắt-lỗi: FR11.2 `package` calls `engine_extras` once (it was three times: check, write, count)."""
        out = self.tmp / "out"
        with self.spy_calls() as spy:
            done = E.dist.cmd_package(mock.Mock(skill=str(self.source_with_deps()), out=str(out), force=False))
        self.assertEqual(done, 0)
        self.assertEqual(spy.call_count, 1)
        self.assertTrue((out / "skill-curator.zip").is_file())

    def test_install_asks_for_the_engine_files_once(self):
        """bắt-lỗi: FR11.2 `install` calls `engine_extras` once (it was twice: check, copy)."""
        workspace = self.tmp / "ws"
        workspace.mkdir()
        args = mock.Mock(skill=str(self.source_with_deps()), agent="claude", workspace=str(workspace), user=False, force=False, allow_root_link=False)
        with self.spy_calls() as spy:
            done = E.dist.cmd_install(args)
        self.assertEqual(done, 0)
        self.assertEqual(spy.call_count, 1)

    def reread_returns_secret(self, wanted: Path):
        """`open_nofollow_read` that answers the first open of `wanted` truthfully and every later open with a secret."""
        real, seen = E.fs.open_nofollow_read, []
        target = os.path.normcase(str(wanted.resolve()))

        def wrapper(path, *args, **kwargs):
            if os.path.normcase(str(Path(path).resolve())) == target:
                seen.append(1)
                if len(seen) >= 2:
                    return io.BytesIO(SECRET_BYTES)
            return real(path, *args, **kwargs)
        return mock.patch.object(E.fs, "open_nofollow_read", wrapper), seen

    def test_package_writes_the_bytes_it_checked(self):
        """bắt-lỗi: FR11.2 an engine file that changes after the secret check is not what lands in the ZIP."""
        wanted = E.ENGINE_DIR / "studio_lint.py"
        patched, seen = self.reread_returns_secret(wanted)
        out = self.tmp / "out"
        with patched:
            done = E.dist.cmd_package(mock.Mock(skill=str(self.source_with_deps()), out=str(out), force=False))
        self.assertEqual(done, 0)
        with zipfile.ZipFile(out / "skill-curator.zip") as zf:
            shipped = zf.read("skill-curator/scripts/_engine/studio_lint.py")
        self.assertEqual(shipped, wanted.read_bytes())
        self.assertNotIn(b"AKIA", shipped)
        self.assertEqual(len(seen), 1, "the engine file was opened more than once")

    def test_install_writes_the_bytes_it_checked(self):
        """bắt-lỗi: FR11.2 the same for the installed copy."""
        wanted = E.ENGINE_DIR / "studio_lint.py"
        patched, seen = self.reread_returns_secret(wanted)
        workspace = self.tmp / "ws"
        workspace.mkdir()
        args = mock.Mock(skill=str(self.source_with_deps()), agent="claude", workspace=str(workspace), user=False, force=False, allow_root_link=False)
        with patched:
            done = E.dist.cmd_install(args)
        self.assertEqual(done, 0)
        shipped = (workspace / ".claude" / "skills" / "skill-curator" / "scripts" / "_engine" / "studio_lint.py").read_bytes()
        self.assertEqual(shipped, wanted.read_bytes())
        self.assertEqual(len(seen), 1, "the engine file was opened more than once")


class ForeignAfterLoadTests(EngineCase):
    def test_module_pulled_in_while_loading_the_engine_stops_doctor(self):
        """bắt-lỗi: FR11.3 `studio.py` that imports a `studio_*` module from outside the engine folder while it loads: ERROR (exit 2), `main` of the engine never runs."""
        scripts = self.curator_home()
        foreign = self.tmp / "foreign"
        foreign.mkdir()
        (foreign / "studio_extra.py").write_text("VALUE = 'foreign'\n", encoding="utf-8")
        (scripts / "_engine" / "studio.py").write_text("import studio_extra\n\n\ndef main(argv):\n    print('ENGINE RAN')\n    return 0\n", encoding="utf-8")
        done = run([scripts / "curator.py", "doctor", "--help"], self.tmp, {"PYTHONPATH": str(foreign)})
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("studio_extra", done.stderr)
        self.assertIn("ERROR", done.stderr)
        self.assertNotIn("ENGINE RAN", done.stdout)

    def test_doctor_still_runs_the_engine_when_nothing_foreign_is_loaded(self):
        """tương-đương: the same fake `studio.py` without the stray import runs."""
        scripts = self.curator_home()
        (scripts / "_engine" / "studio.py").write_text("def main(argv):\n    print('ENGINE RAN')\n    return 0\n", encoding="utf-8")
        done = run([scripts / "curator.py", "doctor", "--help"], self.tmp)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("ENGINE RAN", done.stdout)


if __name__ == "__main__":
    unittest.main()
