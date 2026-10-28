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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURATOR = ROOT / "skills" / "skill-curator"
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


if __name__ == "__main__":
    unittest.main()
