"""The `model_evaluated` gate inside the engine (SPR-02 TK6, FR6, RQ-018): `evals --all` checks `registry/catalog.json`.

Every problem is an ERROR `EV20` and the exit code is 1. The engine runs from a throw-away copy of the repository, started as a
subprocess, so the repository under test is never touched. The old self-tests of the gate (tests/test_studio.py) now call the engine.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

ROOT = E.ROOT
REPO_PARTS = ("studio.py", ".claude-plugin", "standards", "registry", "evals", "skills")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".git")


def copy_repo(dest: Path) -> Path:
    """A copy of the parts of the repository the engine reads, at the engine under test."""
    dest.mkdir(parents=True)
    for part in REPO_PARTS:
        source = ROOT / part
        if source.is_dir():
            shutil.copytree(source, dest / part, ignore=IGNORE)
        else:
            shutil.copy2(source, dest / part)
    return dest


def run_studio(studio_path, *args, cwd, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run([sys.executable, "-X", "utf8", str(studio_path)] + list(args), cwd=str(cwd), stdin=subprocess.DEVNULL, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=300)
    return proc.returncode, proc.stdout, proc.stderr


def can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as t:
        try:
            os.symlink(str(Path(t) / "a"), str(Path(t) / "b"))
        except (OSError, NotImplementedError):
            return False
    return True


class CatalogGateBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repo = copy_repo(self.tmp / "repo")

    def evals_all(self, *extra, cwd=None, env_extra=None):
        return run_studio(self.repo / "studio.py", "evals", "--all", *extra, cwd=cwd or self.repo, env_extra=env_extra)

    def ev20(self, out):
        """The EV20 findings of an `evals --all --json` answer."""
        found = [f for r in json.loads(out)["reports"] for f in r["findings"] if f["code"] == "EV20"]
        self.assertTrue(all(f["level"] == "ERROR" for f in found), found)
        return found

    def edit_catalog(self, change):
        path = self.repo / "registry" / "catalog.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        change(catalog)
        path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")


class EnginePassesAndFailsTests(CatalogGateBase):
    def test_healthy_catalog_passes_without_ev20(self):
        """tương-đương: FR6.3 the committed catalog is valid, so `evals --all` in a repository copy exits 0 and reports no EV20."""
        code, out, err = self.evals_all("--json")
        self.assertEqual((0, ""), (code, err))
        self.assertEqual([], self.ev20(out))

    def test_catalog_claiming_model_evaluated_without_evidence_exits_1_with_ev20(self):
        """bắt-lỗi (red at 37fb2f9: exit 0, no gate in the engine): FR6.2 `model_evaluated: true` on counted-evidence-less numbers -> ERROR EV20 per problem, exit 1, in JSON and in text."""
        def claim(catalog):
            for skill in catalog["skills"]:
                if skill["name"] == "data-quality-audit":
                    skill["model_evaluated"] = True
                    skill["status"] = "model-evaluated"
        self.edit_catalog(claim)
        code, out, _ = self.evals_all("--json")
        found = self.ev20(out)
        self.assertEqual(1, code)
        self.assertGreaterEqual(len(found), 2)
        self.assertTrue(any("data-quality-audit" in f["message"] for f in found), found)
        self.assertTrue(all(f["path"].replace("\\", "/").endswith("registry/catalog.json") for f in found), found)
        code_text, out_text, _ = self.evals_all()
        self.assertEqual(1, code_text)
        self.assertIn("EV20", out_text)

    def test_catalog_that_is_not_json_exits_1_without_traceback(self):
        """bắt-lỗi (red at 37fb2f9: exit 0): FR6.2 a catalog that is not JSON is an EV20, not a traceback."""
        (self.repo / "registry" / "catalog.json").write_text("{not json", encoding="utf-8")
        code, out, err = self.evals_all("--json")
        self.assertEqual(1, code)
        self.assertEqual(1, len(self.ev20(out)))
        self.assertNotIn("Traceback", err)

    def test_missing_catalog_in_the_repository_is_ev20(self):
        """bắt-lỗi (red at 37fb2f9: exit 0): FR6.2 / RF14 inside the repository a missing registry/catalog.json is an ERROR, never a silent skip."""
        (self.repo / "registry" / "catalog.json").unlink()
        code, out, err = self.evals_all("--json")
        found = self.ev20(out)
        self.assertEqual(1, code)
        self.assertEqual(1, len(found))
        self.assertIn("catalog.json", found[0]["message"])
        self.assertNotIn("Traceback", err)

    def test_missing_activation_tool_in_the_repository_is_ev20(self):
        """bắt-lỗi (red at 37fb2f9: exit 0): FR6.4 / RF26 a catalog but no evals/tools/activation.py -> EV20, exit 1, no traceback."""
        (self.repo / "evals" / "tools" / "activation.py").unlink()
        code, out, err = self.evals_all("--json")
        found = self.ev20(out)
        self.assertEqual(1, code)
        self.assertEqual(1, len(found))
        self.assertIn("activation.py", found[0]["message"])
        self.assertNotIn("Traceback", err)

    def test_activation_tool_in_the_working_directory_is_never_loaded(self):
        """bắt-lỗi (red at 37fb2f9: exit 0): FR6.4 the repository of the engine has no activation.py; one that waits in the cwd (and on PYTHONPATH) is not loaded: EV20 stays and the planted file leaves no mark."""
        (self.repo / "evals" / "tools" / "activation.py").unlink()
        planted = self.tmp / "elsewhere"
        (planted / "evals" / "tools").mkdir(parents=True)
        mark = self.tmp / "LOADED.txt"
        (planted / "evals" / "tools" / "activation.py").write_text(
            "from pathlib import Path\nPath(%r).write_text('loaded')\ndef summarize(runs_dir):\n    return {}\n" % str(mark), encoding="utf-8")
        code, out, _ = self.evals_all("--json", cwd=planted, env_extra={"PYTHONPATH": str(planted / "evals" / "tools")})
        self.assertEqual(1, code)
        self.assertEqual(1, len(self.ev20(out)))
        self.assertFalse(mark.exists(), "the planted activation.py was loaded")

    def test_activation_tool_in_the_working_directory_is_not_used_beside_the_real_one(self):
        """tương-đương: with the real tool in place, a planted one in the cwd still leaves no mark and the result stays green."""
        planted = self.tmp / "elsewhere"
        (planted / "evals" / "tools").mkdir(parents=True)
        mark = self.tmp / "LOADED.txt"
        (planted / "evals" / "tools" / "activation.py").write_text(
            "from pathlib import Path\nPath(%r).write_text('loaded')\ndef summarize(runs_dir):\n    return {}\n" % str(mark), encoding="utf-8")
        code, out, _ = self.evals_all("--json", cwd=planted)
        self.assertEqual(0, code)
        self.assertEqual([], self.ev20(out))
        self.assertFalse(mark.exists())

    def test_engine_outside_a_repository_skips_the_gate(self):
        """tương-đương: FR6.2 an engine copied out of any repository (a loose skill, a ZIP) does not run the gate: exit 0, no EV20, even where the eval root has a broken catalog beside it."""
        loose = self.tmp / "loose" / "skill-creator-studio"
        shutil.copytree(self.repo / "skills" / "skill-creator-studio", loose, ignore=IGNORE)
        (self.repo / "registry" / "catalog.json").write_text("{not json", encoding="utf-8")
        code, out, _ = run_studio(loose / "scripts" / "studio.py", "evals", "--all", "--json", "--eval-root", str(self.repo / "evals"), cwd=self.tmp / "loose")
        self.assertEqual(0, code)
        self.assertEqual([], self.ev20(out))


class CatalogProblemsUnitTests(CatalogGateBase):
    def test_engine_repo_root_is_the_repository_of_the_engine_not_the_cwd(self):
        """đơn-vị-hàm-mới: `engine_repo_root` follows the engine file, whatever the working directory is."""
        old = Path.cwd()
        try:
            os.chdir(str(self.tmp))
            self.assertEqual(ROOT, E.evals.engine_repo_root())
        finally:
            os.chdir(str(old))

    def test_catalog_problems_empty_for_the_live_repository(self):
        """tương-đương: FR6.3 `catalog_problems(root)` is empty for the live repository (old test_model_evaluated_requires_counted_evidence)."""
        self.assertEqual([], E.evals.catalog_problems(ROOT))

    def _spy_activation(self):
        spy = mock.Mock(return_value={})
        return mock.patch.object(E.evals, "_load_activation", return_value=mock.Mock(summarize=spy)), spy

    def test_cloud_placeholder_in_runs_is_ev20_and_summarize_is_not_called(self):
        """bắt-lỗi (red at 37fb2f9: `catalog_problems` does not exist): FR6.4 / RF23 an entry that Windows marks as cloud under runs/ -> «runs dir not safe to count», `summarize` never called (mock: every listed entry is cloud)."""
        patch, spy = self._spy_activation()
        with patch, mock.patch.object(E.fs, "entry_is_cloud", return_value=True):
            problems = E.evals.catalog_problems(self.repo)
        self.assertTrue(any("runs dir not safe to count" in p for p in problems), problems)
        spy.assert_not_called()

    def test_runs_walk_over_the_limit_is_ev20_and_summarize_is_not_called(self):
        """bắt-lỗi (red at 37fb2f9: `catalog_problems` does not exist): FR6.4 a runs tree larger than the walk limit is not counted (limit lowered to 2 entries)."""
        patch, spy = self._spy_activation()
        with patch, mock.patch.object(E.const, "DOCTOR_MAX_FILES_PER_SKILL", 2):
            problems = E.evals.catalog_problems(self.repo)
        self.assertTrue(any("runs dir not safe to count" in p for p in problems), problems)
        spy.assert_not_called()

    @unittest.skipUnless(can_symlink(), "cannot create a symlink here")
    def test_symlinked_log_in_runs_is_ev20_and_summarize_is_not_called(self):
        """bắt-lỗi (red at 37fb2f9: `catalog_problems` does not exist; exit 0 by command line): FR6.4 / RF23 a run log that is a symlink -> «runs dir not safe to count», `summarize` never called."""
        runs = self.repo / "evals" / "data-quality-audit" / "runs" / "SPR-18"
        target = self.tmp / "outside.json"
        target.write_text("{}", encoding="utf-8")
        os.symlink(str(target), str(runs / "planted-link.json"))
        patch, spy = self._spy_activation()
        with patch:
            problems = E.evals.catalog_problems(self.repo)
        self.assertTrue(any("runs dir not safe to count" in p for p in problems), problems)
        spy.assert_not_called()
        code, out, _ = self.evals_all("--json")
        self.assertEqual(1, code)
        self.assertTrue(any("runs dir not safe to count" in f["message"] for f in self.ev20(out)))

    def test_safe_runs_dir_reaches_summarize(self):
        """tương-đương: with a plain runs tree `summarize` is called, so the safety check does not turn the gate off."""
        patch, spy = self._spy_activation()
        with patch:
            E.evals.catalog_problems(self.repo)
        spy.assert_called()

    def test_run_log_is_read_without_following_a_link(self):
        """đơn-vị-hàm-mới: `_ran_logs` reads through the no-follow opener (spy), so a link raced in after the walk is refused, not read."""
        runs = self.tmp / "runs"
        runs.mkdir()
        (runs / "a.json").write_text(json.dumps({"runtime": "codex", "with_skill": True, "status": "ran"}), encoding="utf-8")
        real = E.fs.open_nofollow_read
        with mock.patch.object(E.fs, "open_nofollow_read", side_effect=real) as spy:
            logs = E.evals._ran_logs(runs)
        self.assertEqual(1, len(logs["codex"]["with"]))
        spy.assert_called()


if __name__ == "__main__":
    unittest.main()
