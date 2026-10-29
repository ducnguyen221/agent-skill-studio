"""SPR-02 fix round 1 after review: RF-S1 (the EV20 gate never runs code from a tree), RF-S2 (catalog paths stay in the tree), RF-S3 (`check` on a
file in a secret zone), RF-T1 (`doctor --roots` on a cloud root). Each test is a catcher that was red at df4043b.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402
from test_catalog_gate import CatalogGateBase, copy_repo, run_studio  # noqa: E402

ROOT = E.ROOT
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".git")
MARK_PAYLOAD = "from pathlib import Path\nPath(%r).write_text('executed')\ndef summarize(runs_dir):\n    return {}\n"


def foreign_repo(base: Path, mark: Path) -> Path:
    """A tree that looks like a Studio repository (two marker files, a catalog, evidence/) with a hostile evals/tools/activation.py."""
    x = base / "X"
    (x / ".claude-plugin").mkdir(parents=True)
    (x / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (x / "standards").mkdir()
    (x / "standards" / "SKILL_AUTHORING_STANDARD.md").write_text("# standard\n", encoding="utf-8")
    (x / "evals").mkdir()
    catalog = {"skills": [{"name": "x", "targets": ["claude-code"], "evals": "evals/x", "status": "candidate", "model_evaluated": False,
                           "evaluated": {"result": "not_run", "batch_sha": "0" * 40, "batch_sha_kind": "commit", "sprint": "S", "evidence": "evals/x/evidence/S.json",
                                         "harnesses": {"claude-code": "not_run:none"}}}]}
    (x / "evals" / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    (x / "evals" / "x" / "evidence").mkdir(parents=True)
    (x / "evals" / "x" / "cases.json").write_text('{"skill": "x", "cases": []}', encoding="utf-8")
    (x / "evals" / "tools").mkdir()
    (x / "evals" / "tools" / "activation.py").write_text(MARK_PAYLOAD % str(mark), encoding="utf-8")
    return x


class Rfs1GateNeverRunsTreeCode(CatalogGateBase):
    def test_installed_engine_in_a_foreign_repo_does_not_run_its_activation_py(self):
        """bắt-lỗi (red at df4043b: the mark file appears): RF-S1 `install` into a hostile repo, then `evals --all` from the installed copy runs no code of that repo."""
        mark = self.tmp / "EXECUTED.txt"
        x = foreign_repo(self.tmp, mark)
        code, _out, err = run_studio(ROOT / "studio.py", "install", "skills/skill-creator-studio", "--agent", "claude", "--workspace", str(x), cwd=ROOT)
        self.assertEqual((0, ""), (code, err))
        installed = x / ".claude" / "skills" / "skill-creator-studio" / "scripts" / "studio.py"
        self.assertTrue(installed.is_file())
        run_studio(installed, "evals", "--all", "--json", cwd=self.tmp)
        self.assertFalse(mark.exists(), "evals --all executed evals/tools/activation.py of the tree")

    def test_engine_never_imports_code_from_the_tree(self):
        """bắt-lỗi (red at df4043b: importlib is imported and used): RF-S1 the engine source has no importlib and no dynamic import."""
        source = E.engine_source()
        self.assertNotIn("importlib", source)

    def test_repo_without_evals_dir_skips_the_gate(self):
        """bắt-lỗi (red at df4043b: EV20 for a missing activation.py, exit 1): RF-S1 an engine whose repository has no evals/ does not run the gate."""
        shutil.rmtree(self.repo / "evals")
        code, out, _ = self.evals_all("--json", "--eval-root", str(self.tmp / "nowhere"))
        self.assertEqual(0, code)
        self.assertEqual([], self.ev20(out))

    def test_repo_with_evals_but_without_catalog_is_still_ev20(self):
        """tương-đương: RF-S1 a repository with evals/ and no evals/catalog.json keeps its EV20."""
        (self.repo / "evals" / "catalog.json").unlink()
        code, out, _ = self.evals_all("--json")
        self.assertEqual(1, code)
        self.assertEqual(1, len(self.ev20(out)))

    def test_summarize_of_the_engine_is_the_one_source_of_activation_py(self):
        """bắt-lỗi (red at df4043b: the engine has no `summarize`): RF-S1 engine and tool count the same logs to the same table."""
        runs = self.tmp / "runs"
        runs.mkdir()
        rows = [{"runtime": "codex", "with_skill": True, "status": "ran", "triggered": True},
                {"runtime": "codex", "with_skill": True, "status": "ran", "triggered": True, "kind": "near-miss"},
                {"runtime": "codex", "with_skill": False, "status": "ran", "triggered": True},
                {"runtime": "claude-code", "with_skill": True, "status": "ran", "triggered": False}]
        for index, row in enumerate(rows):
            (runs / ("%d.json" % index)).write_text(json.dumps(row), encoding="utf-8")
        (runs / "bad.json").write_text("{not json", encoding="utf-8")
        import importlib.util as iu  # the test may load the tool; the engine may not
        spec = iu.spec_from_file_location("activation_under_test", ROOT / "evals" / "tools" / "activation.py")
        tool = iu.module_from_spec(spec)
        spec.loader.exec_module(tool)
        expected = {"codex": {"pos": 1, "pos_trig": 1, "neg": 1, "neg_trig": 1}, "claude-code": {"pos": 1, "pos_trig": 0, "neg": 0, "neg_trig": 0}}
        self.assertEqual(expected, E.evals.summarize(runs))
        self.assertEqual(expected, tool.summarize(runs))


class Rfs2CatalogPathsStayInTree(CatalogGateBase):
    def _set(self, **changes):
        def edit(catalog):
            for skill in catalog["skills"]:
                if skill["name"] == "data-quality-audit":
                    if "evals" in changes:
                        skill["evals"] = changes["evals"]
                    if "sprint" in changes:
                        skill["evaluated"]["sprint"] = changes["sprint"]
        self.edit_catalog(edit)

    def test_sprint_and_evals_that_leave_the_tree_are_ev20_and_nothing_outside_is_read(self):
        """bắt-lỗi (red at df4043b: the log outside the tree is counted, no «relative» message): RF-S2 `sprint`/`evals` must be plain relative names."""
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "r.json").write_text(json.dumps({"runtime": "codex", "with_skill": True, "status": "ran", "triggered": True}), encoding="utf-8")
        cases = [("sprint", "../../../../outside"), ("sprint", str(outside)), ("sprint", "a:b"), ("sprint", "CON"), ("sprint", "x/../.."),
                 ("evals", "../outside"), ("evals", str(outside)), ("evals", "evals/x:y")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                with mock.patch.object(E.evals, "summarize_logs", create=True, return_value={}) as spy:
                    self.setUp()  # fresh copy per case
                    self._set(**{key: value})
                    problems = E.evals.catalog_problems(self.repo)
                self.assertTrue(any("relative" in p and key in p for p in problems), problems)
                spy.assert_not_called()

    def test_date_that_is_not_a_plain_date_is_ev20_and_no_file_outside_is_read(self):
        """bắt-lỗi (red at 698f552: the file ab-<date>.json outside runs_dir is read, no «YYYY-MM-DD» message): RF-S2 `evaluated.date` must be YYYY-MM-DD; since SPR-03 it only picks a block inside the compact evidence, and no file outside the repository is opened."""
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "x.json").write_text(json.dumps({"per_runtime": {}}), encoding="utf-8")
        for value in ("../../x", "..", "2026-10-18/../../x", "2026-1-18", "2026-10-18\n", 20261018, None):
            with self.subTest(date=value):
                self.setUp()
                def edit(catalog, value=value):
                    for skill in catalog["skills"]:
                        if skill["name"] == "data-quality-audit":
                            skill["evaluated"]["date"] = value
                self.edit_catalog(edit)
                reads = []
                real = E.evals._load_json
                with mock.patch.object(E.evals, "_load_json", side_effect=lambda p: (reads.append(Path(p)), real(p))[1]):
                    problems = E.evals.catalog_problems(self.repo)
                self.assertTrue(any("YYYY-MM-DD" in p for p in problems), problems)
                self.assertFalse([r for r in reads if self.repo not in r.parents and r != self.repo], reads)

    def test_evidence_dir_is_walked_before_it_is_counted(self):
        """bắt-lỗi (red at 3cc1bd3: no evidence folder is walked): RF-S2 / FR3.2 the evidence folder itself goes through the safe walk before any file in it is read."""
        seen = []
        real = E.fs.walk_files

        def spy_walk(base, *a, **k):
            seen.append(Path(base))
            return real(base, *a, **k)
        with mock.patch.object(E.fs, "walk_files", side_effect=spy_walk):
            E.evals.catalog_problems(self.repo)
        self.assertIn(self.repo / "evals" / "data-quality-audit" / "evidence", seen)


class Rfs3CheckRefusesSecretZone(unittest.TestCase):
    def test_check_on_a_file_in_a_secret_zone_exits_2_without_reading(self):
        """bắt-lỗi (red at df4043b: «check for type workflow is not available yet» proves the file was parsed): RF-S3 `check` refuses the file before opening it."""
        with tempfile.TemporaryDirectory() as t:
            zone = Path(t) / ".secret"
            zone.mkdir()
            note = zone / "note.md"
            note.write_text("---\ntype: workflow\n---\n# note\n", encoding="utf-8")
            code, out, err = run_studio(E.ENGINE_PATH, "check", str(note), cwd=ROOT)
        self.assertEqual(2, code)
        self.assertIn("not read", err)
        self.assertNotIn("not available yet", err + out)

    def test_check_on_a_plain_file_still_reads_its_type(self):
        """tương-đương: RF-S3 outside a zone `check note.md` with `type: workflow` reads its type and checks it as a workflow (SPR-04 TK8; it said `not available yet` before)."""
        with tempfile.TemporaryDirectory() as t:
            note = Path(t) / "note.md"
            note.write_text("---\ntype: workflow\n---\n# note\n", encoding="utf-8")
            code, out, err = run_studio(E.ENGINE_PATH, "check", str(note), cwd=ROOT)
        self.assertEqual(1, code, err)  # a workflow with no Kết luận, no Bước and no Xong khi
        self.assertIn("WC1", out)


class Rft1DoctorCloudRoot(unittest.TestCase):
    def test_cloud_root_with_a_plain_name_is_skipped_as_cloud_exit_0(self):
        """bắt-lỗi (red at df4043b: exit 2 «root not found or not a directory»): RF-T1 a --roots folder with cloud attributes is skipped (reason cloud), exit 0, as at 1211bfa."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "plainname"
            root.mkdir()
            real = E.fs.path_is_cloud
            flagged = os.path.normcase(os.path.abspath(str(root)))
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(E.fs, "path_is_cloud", lambda p: os.path.normcase(os.path.abspath(os.fspath(p))) == flagged or real(p)):
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = E.engine.main(["doctor", "--roots", str(root), "--json"])
        self.assertEqual((0, ""), (code, err.getvalue()))
        report = json.loads(out.getvalue())
        self.assertIn("cloud", [s["reason"] for s in report["skipped"]])

    def test_missing_root_is_still_not_found(self):
        """tương-đương: RF-T1 a root that does not exist keeps exit 2 «root not found»."""
        with tempfile.TemporaryDirectory() as t:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = E.engine.main(["doctor", "--roots", str(Path(t) / "absent"), "--json"])
        self.assertEqual(2, code)
        self.assertIn("root not found", err.getvalue())


if __name__ == "__main__":
    unittest.main()
