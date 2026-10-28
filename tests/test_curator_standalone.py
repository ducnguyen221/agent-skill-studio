"""SPR-04 TK12: the `skill-curator` ZIP and the `install` copy run alone, without `skill-creator-studio` next to them (FR9.3, SC13).

Each test packs or installs into a temporary folder and runs `curator.py` from there, with the repo not on the path."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURATOR = ROOT / "skills" / "skill-curator"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402

dist = _engine.dist
ENGINE_SRC = _engine.ENGINE_DIR
FIXTURE = ROOT / "tests" / "fixtures" / "opcos-tree" / "plugins" / "p-default" / "skills"


def run(args, cwd, env=None):
    merged = dict(os.environ)
    merged.pop("PYTHONPATH", None)
    merged.update(env or {})
    return subprocess.run([sys.executable, "-X", "utf8", *map(str, args)], cwd=str(cwd), env=merged, text=True, encoding="utf-8",
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class CuratorStandaloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="curator-solo-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def unpacked(self) -> Path:
        out = self.tmp / "out"
        done = run([ROOT / "studio.py", "package", CURATOR, "--out", out], ROOT)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        solo = self.tmp / "solo"
        with zipfile.ZipFile(out / "skill-curator.zip") as zf:
            zf.extractall(solo)
        return solo / "skill-curator" / "scripts"

    def check_runs(self, scripts: Path):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(exist_ok=True)
        helped = run([scripts / "curator.py", "catalog", "--help"], elsewhere)
        self.assertEqual(helped.returncode, 0, helped.stderr)
        self.assertIn("usage", helped.stdout.lower())
        scanned = run([scripts / "curator.py", "doctor", "--roots", FIXTURE], elsewhere)
        self.assertEqual(scanned.returncode, 0, scanned.stderr + scanned.stdout)
        self.assertIn("doctor (profile", scanned.stdout)

    def test_zip_runs_alone(self):
        scripts = self.unpacked()
        self.assertTrue((scripts / "_engine" / "studio_const.py").is_file())
        self.assertTrue((scripts / "_engine" / "studio.py").is_file())
        self.assertFalse((scripts.parents[1] / "skill-creator-studio").exists())
        self.check_runs(scripts)

    def test_install_runs_alone(self):
        workspace = self.tmp / "ws"
        workspace.mkdir()
        done = run([ROOT / "studio.py", "install", CURATOR, "--agent", "claude", "--workspace", workspace], ROOT)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        scripts = workspace / ".claude" / "skills" / "skill-curator" / "scripts"
        self.assertTrue((scripts / "_engine" / "studio_const.py").is_file())
        self.check_runs(scripts)

    def test_missing_engine_dep_exit_2(self):
        scripts = self.unpacked()
        (scripts / "_engine" / "studio_lint.py").unlink()
        done = run([scripts / "curator.py", "catalog", "--help"], self.tmp)
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertIn("shared engine modules", done.stderr)
        # the pack side: a name that is not studio_*.py, or not in the engine, stops the package and makes no ZIP
        for bad in ("../evil.py", "studio_nope.py", "Studio_fs.py"):
            copy = self.tmp / ("src-" + re.sub(r"\W", "_", bad)) / "skill-curator"
            shutil.copytree(CURATOR, copy, ignore=shutil.ignore_patterns("__pycache__"))
            deps = copy / "scripts" / "ENGINE_DEPS"
            deps.write_text(deps.read_text(encoding="utf-8") + bad + "\n", encoding="utf-8")
            out = self.tmp / ("out-" + re.sub(r"\W", "_", bad))
            done = run([ROOT / "studio.py", "package", copy, "--out", out], ROOT)
            self.assertEqual(done.returncode, 1, bad + done.stdout + done.stderr)
            self.assertIn("PACK", done.stderr + done.stdout)
            self.assertFalse((out / "skill-curator.zip").exists(), bad)

    def test_foreign_studio_module_on_path_refused(self):
        scripts = self.unpacked()
        foreign = self.tmp / "foreign"
        foreign.mkdir()
        (foreign / "studio_const.py").write_text("VERSION = 'foreign'\n", encoding="utf-8")
        code = ("import sys, runpy; sys.path.insert(0, %r); import studio_const; "
                "sys.argv = [%r, 'catalog', '--help']; runpy.run_path(%r, run_name='__main__')" % (str(foreign), "curator.py", str(scripts / "curator.py")))
        done = run(["-c", code], self.tmp)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("studio_const", done.stderr)


    def source_copy(self, name="src") -> Path:
        copy = self.tmp / name / "skill-curator"
        shutil.copytree(CURATOR, copy, ignore=shutil.ignore_patterns("__pycache__"))
        return copy

    def engine_copy(self, folder: str = "engine") -> Path:
        engine = self.tmp / folder
        engine.mkdir(parents=True)
        for item in ENGINE_SRC.glob("studio*.py"):
            shutil.copy(item, engine / item.name)
        return engine

    def extras_with(self, engine: Path):
        with mock.patch.object(dist, "ENGINE_DIR", engine):
            return dist.engine_extras(self.source_copy(engine.name + "-src"))

    def test_rf_12_1_studio_line_in_engine_deps_is_not_copied_twice(self):
        copy = self.source_copy()
        deps = copy / "scripts" / "ENGINE_DEPS"
        deps.write_text("studio.py\n" + deps.read_text(encoding="utf-8"), encoding="utf-8")
        out = self.tmp / "out"
        done = run([ROOT / "studio.py", "package", copy, "--out", out], ROOT)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertNotIn("Duplicate", done.stderr)
        with zipfile.ZipFile(out / "skill-curator.zip") as zf:
            names = zf.namelist()
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(sum(n.endswith("_engine/studio.py") for n in names), 1)
        workspace = self.tmp / "ws"
        workspace.mkdir()
        done = run([ROOT / "studio.py", "install", copy, "--agent", "claude", "--workspace", workspace], ROOT)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)

    def test_rf_12_2_engine_in_a_cloud_folder_is_refused_unread(self):
        engine = self.engine_copy("OneDrive - Corp")
        opened = []
        real = dist.fs.open_nofollow_read

        def spy(path, *args, **kwargs):
            opened.append(str(path))
            return real(path, *args, **kwargs)
        with mock.patch.object(dist.fs, "open_nofollow_read", spy):
            extras, findings = self.extras_with(engine)
        self.assertTrue(findings and all(f["code"] == "PACK" and f["level"] == "ERROR" for f in findings), findings)
        self.assertEqual([x for x in opened if str(engine) in x], [])

    def test_rf_12_2_engine_file_over_25_mb_is_refused(self):
        engine = self.engine_copy()
        with open(engine / "studio_lint.py", "ab") as handle:
            handle.truncate(25 * 1024 * 1024 + 1)
        extras, findings = self.extras_with(engine)
        self.assertTrue(any("25 MB" in f["message"] and f["code"] == "PACK" for f in findings), findings)

    def test_rf_12_4_secret_in_an_engine_file_is_refused(self):
        engine = self.engine_copy()
        with open(engine / "studio_lint.py", "a", encoding="utf-8") as handle:
            handle.write("\nTOKEN = 'AKIA" + "ABCDEFGHIJKLMNOP'\n")
        extras, findings = self.extras_with(engine)
        self.assertTrue(any(f["code"] == "SEC" for f in findings), findings)

    def test_rf_12_4_engine_folder_already_in_the_source_is_refused(self):
        copy = self.source_copy()
        (copy / "scripts" / "_engine").mkdir()
        (copy / "scripts" / "_engine" / "studio_const.py").write_text("X = 1\n", encoding="utf-8")
        extras, findings = dist.engine_extras(copy)
        self.assertEqual(extras, [])
        self.assertTrue(any(f["code"] == "PACK" and "_engine" in f["message"] for f in findings), findings)
        out = self.tmp / "out"
        done = run([ROOT / "studio.py", "package", copy, "--out", out], ROOT)
        self.assertEqual(done.returncode, 1)
        self.assertFalse((out / "skill-curator.zip").exists())


if __name__ == "__main__":
    unittest.main()
