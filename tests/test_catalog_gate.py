"""The `model_evaluated` gate inside the engine (SPR-02 TK6, FR6, RQ-018): `evals --all` checks `evals/catalog.json` and the compact evidence files it names (SPR-03 TK1).

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
from _batches import COMPACT, RAW, activation, write_compact  # noqa: E402
from _gate_mutations import FIXTURE as GATE_FIXTURE, GOLDEN as GATE_GOLDEN, MUTATIONS, new_catalog, norm_new  # noqa: E402

ROOT = E.ROOT
REPO_PARTS = ("studio.py", ".claude-plugin", "standards", "evals", "skills")
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
        path = self.repo / "evals" / "catalog.json"
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
        self.assertTrue(all(f["path"].replace("\\", "/").endswith("evals/catalog.json") for f in found), found)
        code_text, out_text, _ = self.evals_all()
        self.assertEqual(1, code_text)
        self.assertIn("EV20", out_text)

    def test_catalog_that_is_not_json_exits_1_without_traceback(self):
        """bắt-lỗi (red at 37fb2f9: exit 0): FR6.2 a catalog that is not JSON is an EV20, not a traceback."""
        (self.repo / "evals" / "catalog.json").write_text("{not json", encoding="utf-8")
        code, out, err = self.evals_all("--json")
        self.assertEqual(1, code)
        self.assertEqual(1, len(self.ev20(out)))
        self.assertNotIn("Traceback", err)

    def test_missing_catalog_in_the_repository_is_ev20(self):
        """bắt-lỗi (red at 37fb2f9: exit 0): FR6.2 / RF14 inside the repository a missing evals/catalog.json is an ERROR, never a silent skip."""
        (self.repo / "evals" / "catalog.json").unlink()
        code, out, err = self.evals_all("--json")
        found = self.ev20(out)
        self.assertEqual(1, code)
        self.assertEqual(1, len(found))
        self.assertIn("catalog.json", found[0]["message"])
        self.assertNotIn("Traceback", err)

    def test_missing_activation_tool_is_not_a_problem_any_more(self):
        """tương-đương: SPR-02 fix round 1 (RF-S1) the gate counts logs in the engine, so a repository without evals/tools/activation.py gives no EV20."""
        (self.repo / "evals" / "tools" / "activation.py").unlink()
        code, out, err = self.evals_all("--json")
        self.assertEqual((0, ""), (code, err))
        self.assertEqual([], self.ev20(out))

    def test_activation_tool_in_the_working_directory_is_never_loaded(self):
        """tương-đương: FR6.4 a planted activation.py waiting in the cwd (and on PYTHONPATH) is never loaded, with or without the real one in the repository."""
        (self.repo / "evals" / "tools" / "activation.py").unlink()
        planted = self.tmp / "elsewhere"
        (planted / "evals" / "tools").mkdir(parents=True)
        mark = self.tmp / "LOADED.txt"
        (planted / "evals" / "tools" / "activation.py").write_text(
            "from pathlib import Path\nPath(%r).write_text('loaded')\ndef summarize(runs_dir):\n    return {}\n" % str(mark), encoding="utf-8")
        code, out, _ = self.evals_all("--json", cwd=planted, env_extra={"PYTHONPATH": str(planted / "evals" / "tools")})
        self.assertEqual(0, code)
        self.assertEqual([], self.ev20(out))
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
        (self.repo / "evals" / "catalog.json").write_text("{not json", encoding="utf-8")
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

    def _spy_count(self):
        spy = mock.Mock(return_value={})
        return mock.patch.object(E.evals, "summarize_logs", spy), spy

    def test_cloud_placeholder_in_evidence_is_ev20_and_nothing_is_counted(self):
        """bắt-lỗi (red at 3cc1bd3: no evidence folder is read): FR3.2 / FR6.4 an entry that Windows marks as cloud under evidence/ -> «evidence dir not safe to read», `summarize_logs` never called (mock: every listed entry is cloud)."""
        patch, spy = self._spy_count()
        with patch, mock.patch.object(E.fs, "entry_is_cloud", return_value=True):
            problems = E.evals.catalog_problems(self.repo)
        self.assertTrue(any("evidence dir not safe to read" in p for p in problems), problems)
        spy.assert_not_called()

    def test_evidence_walk_over_the_limit_is_ev20_and_nothing_is_counted(self):
        """bắt-lỗi (red at 3cc1bd3): FR3.2 an evidence folder larger than the walk limit is not counted (limit lowered to 1 entry)."""
        patch, spy = self._spy_count()
        with patch, mock.patch.object(E.const, "DOCTOR_MAX_FILES_PER_SKILL", 1):
            problems = E.evals.catalog_problems(self.repo)
        self.assertTrue(any("evidence dir not safe to read" in p for p in problems), problems)
        spy.assert_not_called()

    @unittest.skipUnless(can_symlink(), "cannot create a symlink here")
    def test_symlinked_file_in_evidence_is_ev20_and_nothing_is_counted(self):
        """bắt-lỗi (red at 3cc1bd3): FR3.2 / RF23 a file that is a symlink under evidence/ -> «evidence dir not safe to read», `summarize_logs` never called."""
        evidence = self.repo / "evals" / "data-quality-audit" / "evidence"
        target = self.tmp / "outside.json"
        target.write_text("{}", encoding="utf-8")
        os.symlink(str(target), str(evidence / "planted-link.json"))
        patch, spy = self._spy_count()
        with patch:
            problems = E.evals.catalog_problems(self.repo)
        self.assertTrue(any("evidence dir not safe to read" in p for p in problems), problems)
        spy.assert_not_called()
        code, out, _ = self.evals_all("--json")
        self.assertEqual(1, code)
        self.assertTrue(any("evidence dir not safe to read" in f["message"] for f in self.ev20(out)))

    def test_safe_evidence_dir_reaches_the_count(self):
        """tương-đương: with plain evidence files `summarize_logs` is called, so the safety check does not turn the gate off."""
        patch, spy = self._spy_count()
        with patch:
            E.evals.catalog_problems(self.repo)
        spy.assert_called()

    def test_evidence_file_is_read_without_following_a_link(self):
        """đơn-vị-hàm-mới: `load_batch` reads through the no-follow opener (spy), so a link raced in after the walk is refused, not read."""
        path = self.repo / "evals" / "data-quality-audit" / "evidence" / "SPR-18.json"
        real = E.fs.open_nofollow_read
        with mock.patch.object(E.fs, "open_nofollow_read", side_effect=real) as spy:
            batch = E.evals.load_batch(path, self.repo, "data-quality-audit", "SPR-18")
        self.assertEqual("SPR-18", batch["batch"])
        spy.assert_called()

    def test_read_logs_reads_a_raw_folder_without_following_a_link(self):
        """đơn-vị-hàm-mới: `read_logs` keeps the no-follow read of the old `_ran_logs`; an unreadable file is skipped and named."""
        runs = self.tmp / "runs"
        runs.mkdir()
        (runs / "a.json").write_text(json.dumps({"runtime": "codex", "with_skill": True, "status": "ran"}), encoding="utf-8")
        (runs / "bad.json").write_text("{not json", encoding="utf-8")
        (runs / "list.json").write_text("[]", encoding="utf-8")
        real = E.fs.open_nofollow_read
        skipped = []
        with mock.patch.object(E.fs, "open_nofollow_read", side_effect=real) as spy:
            logs = E.evals.read_logs(runs, skipped)
        self.assertEqual(["a.json"], [name for name, _ in logs])
        self.assertEqual(["bad.json", "list.json"], skipped)
        self.assertEqual({"codex": {"with": [logs[0][1]], "base": []}}, E.evals.ran_logs([log for _, log in logs]))
        spy.assert_called()


class CatalogMovedTests(CatalogGateBase):
    def test_catalog_moved(self):
        """bắt-lỗi (red at 3cc1bd3: the old registry/catalog.json is still read): FR2.1 / FR2.2 a repository with evals/ and only registry/catalog.json -> exactly one EV20 naming evals/catalog.json; the old path is no fallback."""
        (self.repo / "registry").mkdir()
        shutil.move(str(self.repo / "evals" / "catalog.json"), str(self.repo / "registry" / "catalog.json"))
        code, out, err = self.evals_all("--json")
        found = self.ev20(out)
        self.assertEqual(1, code)
        self.assertEqual(1, len(found), found)
        self.assertIn("evals/catalog.json is missing", found[0]["message"])
        self.assertNotIn("Traceback", err)


class BatchRejectTests(CatalogGateBase):
    """FR3.2: a compact evidence file that is missing, a link, unreadable or against the schema is exactly one gate line and never a pass."""
    SKILL, BATCH = "data-quality-audit", "SPR-18"

    @property
    def evidence(self) -> Path:
        return self.repo / "evals" / self.SKILL / "evidence" / (self.BATCH + ".json")

    def edit_evidence(self, change):
        data = json.loads(self.evidence.read_text(encoding="utf-8"))
        change(data)
        self.evidence.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def only(self, needle):
        problems = E.evals.catalog_problems(self.repo)
        self.assertEqual(1, len(problems), problems)
        self.assertIn(needle, problems[0])

    def test_live_evidence_is_clean(self):
        """tương-đương: the copy of the repository starts with no problem, so each case below adds exactly its own line."""
        self.assertEqual([], E.evals.catalog_problems(self.repo))

    def test_batch_rejects(self):
        def padded(data):
            data["ab"]["2026-10-18"]["pad"] = "x" * 1_000_001

        def dup_file(data):
            data["logs"].append(dict(data["logs"][0]))

        def move_evidence(catalog):
            for skill in catalog["skills"]:
                if skill["name"] == self.SKILL:
                    skill["evaluated"]["evidence"] = "evals/other/evidence/SPR-18.json"
                    skill["evaluated"]["ab_report"] = "evals/other/evidence/SPR-18.json"

        def bad_trigger(data):
            data["logs"][0]["triggered"] = "yes"

        edits = [("missing file", "is missing", lambda: self.evidence.unlink()),
                 ("schema 2", "schema", lambda: self.edit_evidence(lambda d: d.update(schema=2))),
                 ("unknown top key", "unknown key", lambda: self.edit_evidence(lambda d: d.update(extra=1))),
                 ("triggered is a string", "triggered has the wrong type", lambda: self.edit_evidence(bad_trigger)),
                 ("over 1 000 000 bytes", "larger than", lambda: self.edit_evidence(padded)),
                 ("logs is not a list", "must be lists", lambda: self.edit_evidence(lambda d: d.update(logs={}))),
                 ("duplicate file", "appears twice", lambda: self.edit_evidence(dup_file)),
                 ("skill differs from the catalog", "skill 'other' is not", lambda: self.edit_evidence(lambda d: d.update(skill="other"))),
                 ("evidence outside <evals>/evidence/", "evaluated.evidence", lambda: self.edit_catalog(move_evidence))]
        for label, needle, change in edits:
            with self.subTest(label):
                self.setUp()
                change()
                self.only(needle)
                code, out, _ = self.evals_all("--json")
                self.assertEqual(1, code)
                self.assertEqual(1, len(self.ev20(out)))

    def test_batch_rejects_a_link_to_the_file(self):
        """bắt-lỗi (red at 3cc1bd3): FR3.2 the evidence file is a link (the check is mocked: a symlink needs a privilege on Windows) -> one line, file not read."""
        target = self.evidence
        real = E.fs.is_link
        with mock.patch.object(E.fs, "is_link", side_effect=lambda p: Path(p) == target or real(p)):
            self.only("link")

    def test_batch_rejects_a_link_in_the_directory_chain(self):
        """bắt-lỗi (red at 3cc1bd3): FR3.2 the evidence folder is a link -> one line «not safe to read», nothing inside is opened."""
        folder = self.evidence.parent
        real = E.fs.is_link
        opened = []
        real_load = E.evals._load_json
        with mock.patch.object(E.fs, "is_link", side_effect=lambda p: Path(p) == folder or real(p)), \
                mock.patch.object(E.evals, "_load_json", side_effect=lambda p: (opened.append(Path(p)), real_load(p))[1]):
            self.only("evidence dir not safe to read")
        self.assertFalse([p for p in opened if p.parent == folder], opened)

    def test_evidence_folder_without_a_catalog_entry_is_a_line(self):
        """bắt-lỗi (red at 3cc1bd3): FR3.1b an evals/<x>/evidence/ whose skill the catalog does not name is reported, not skipped."""
        stray = self.repo / "evals" / "stray-skill" / "evidence"
        stray.mkdir(parents=True)
        (stray / "B.json").write_text("{}", encoding="utf-8")
        self.only("evals/stray-skill/evidence has no catalog entry")

    def test_evaluated_block_needs_the_evidence_key(self):
        """bắt-lỗi (red at 3cc1bd3): FR3.1 the `evaluated` block names its evidence file; without the key the gate says so (one line)."""
        def drop(catalog):
            for skill in catalog["skills"]:
                if skill["name"] == self.SKILL:
                    del skill["evaluated"]["evidence"]
        self.edit_catalog(drop)
        self.only("evaluated.evidence")

    def test_ab_report_must_equal_the_evidence(self):
        """bắt-lỗi (red at 3cc1bd3): FR3.1 `ab_report`, when present, is the same path as `evidence`."""
        def other(catalog):
            for skill in catalog["skills"]:
                if skill["name"] == self.SKILL:
                    skill["evaluated"]["ab_report"] = "evals/data-quality-audit/evidence/SPR-33.json"
        self.edit_catalog(other)
        self.only("ab_report")

    def test_runtime_checked_on_every_batch(self):
        """bắt-lỗi (red at 3cc1bd3): FR3.1b a skill without an `evaluated` block still has every compact file checked: a log with runtime «x» -> one runtime line."""
        path = self.repo / "evals" / "skill-creator-studio" / "evidence" / "SPR-18.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["logs"][0]["runtime"] = "x"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        problems = E.evals.catalog_problems(self.repo)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("runtime 'x' not in targets", problems[0])
        self.assertIn("skill-creator-studio", problems[0])

    def test_runtime_checked_in_smoke_entries(self):
        """tương-đương: the old runs/*/smoke/*.json check -> the `smoke` entries of a compact file are checked against the targets too."""
        def smoke(data):
            data["smoke"].append({"file": "smoke/z.json", "runtime": "gemini-cli", "with_skill": True})
        self.edit_evidence(smoke)
        problems = E.evals.catalog_problems(self.repo)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("gemini-cli", problems[0])


    def test_batch_problem_names_each_schema_break(self):
        """bắt-lỗi (red at 3cc1bd3: no `_batch_problem`): FR3.2 every way a parsed compact file can break the schema has its own reason, so the line the gate prints says what to fix."""
        good = json.loads(self.evidence.read_text(encoding="utf-8"))

        def with_(**changes):
            return lambda d: dict(d, **changes)

        def drop(key):
            return lambda d: {k: v for k, v in d.items() if k != key}

        def log_edit(change):
            def edit(d):
                d = json.loads(json.dumps(d))
                change(d["logs"])
                return d
            return edit

        breaks = [("not an object", lambda d: [], "not a JSON object"),
                  ("a key is missing", drop("ab"), "lacks key"),
                  ("batch differs", with_(batch="other"), "batch 'other'"),
                  ("source is not the ledger folder", with_(source="evals/x/"), "does not name the ledger folder"),
                  ("source_sha256 is short", with_(source_sha256="abc"), "source_sha256"),
                  ("log entry is not an object", log_edit(lambda logs: logs.append("x")), "not an object"),
                  ("log entry has an unknown key", log_edit(lambda logs: logs[0].update(extra=1)), "unknown key"),
                  ("log entry lacks a required key", log_edit(lambda logs: logs[0].pop("runtime")), "lacks key"),
                  ("log file leaves the batch", log_edit(lambda logs: logs[0].update(file="../x.json")), "not a path inside the batch"),
                  ("log file has a folder", log_edit(lambda logs: logs[0].update(file="sub/x.json")), "expected x.json"),
                  ("smoke file has no smoke/ prefix", lambda d: dict(d, smoke=[{"file": "x.json", "runtime": "codex", "with_skill": True}]), "expected smoke/x.json"),
                  ("ab is not an object", with_(ab=[]), "ab must be an object"),
                  ("ab key is not a date", with_(ab={"yesterday": {}}), "YYYY-MM-DD"),
                  ("per_runtime row is not an object", with_(ab={"2026-10-18": {"per_runtime": {"codex": 3}}}), "object of objects")]
        for label, change, needle in breaks:
            with self.subTest(label):
                reason = E.evals._batch_problem(change(good), self.SKILL, self.BATCH)
                self.assertIsNotNone(reason)
                self.assertIn(needle, reason)
        self.assertIsNone(E.evals._batch_problem(good, self.SKILL, self.BATCH))

    def test_load_batch_refuses_a_cloud_placeholder_and_an_unreadable_file(self):
        """bắt-lỗi (red at 3cc1bd3): FR3.2 / FR6.4 a placeholder is never opened (it would be downloaded); a path that cannot be opened is a reason, not a traceback."""
        with mock.patch.object(E.fs, "path_is_cloud", return_value=True), mock.patch.object(E.evals, "_load_json") as opened:
            with self.assertRaises(ValueError) as caught:
                E.evals.load_batch(self.evidence, self.repo, self.SKILL, self.BATCH)
        self.assertIn("cloud placeholder", str(caught.exception))
        opened.assert_not_called()
        with self.assertRaises(ValueError) as caught:
            E.evals.load_batch(self.repo / "evals" / "absent.json", self.repo, self.SKILL, self.BATCH)
        self.assertIn("cannot be read", str(caught.exception))

    def test_harness_missing_from_the_ab_block_and_missing_ab_report(self):
        """tương-đương: the old per-harness checks survive the move: a ran harness absent from the ab block, and `ab_report` missing when the flag is true."""
        def codex_gone(data):
            del data["ab"]["2026-10-18"]["per_runtime"]["codex"]
        self.edit_evidence(codex_gone)
        self.assertTrue(any("is ran but absent from ab-2026-10-18.json" in p for p in E.evals.catalog_problems(self.repo)))

        def claim_true(catalog):
            for skill in catalog["skills"]:
                if skill["name"] == self.SKILL:
                    skill.update(model_evaluated=True, status="model-evaluated")
                    del skill["evaluated"]["ab_report"]
        self.setUp()
        self.edit_catalog(claim_true)
        self.assertTrue(any("needs evaluated.ab_report" in p for p in E.evals.catalog_problems(self.repo)))


class GateMatchesOldGateTests(unittest.TestCase):
    """FR3.1: over the compact files the gate prints the list of problems the gate of 3cc1bd3 printed over the raw `runs/` folders (RK1).

    tests/fixtures/gate/golden.json was produced once by the OLD gate (`git archive 3cc1bd3`) under the 13 catalog edits of tests/_gate_mutations.py;
    nothing here calls the old gate, and nothing derives the expected lines from the code under test.
    """
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        shutil.copytree(GATE_FIXTURE / "evals", self.root / "evals")
        self.base = json.loads((self.root / "evals" / "catalog.json").read_text(encoding="utf-8"))
        self.golden = json.loads(GATE_GOLDEN.read_text(encoding="utf-8"))["cases"]

    def problems_for(self, mutate) -> list:
        catalog = new_catalog(self.base, mutate)
        path = self.root / "evals" / "edited.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return sorted(norm_new(p) for p in E.evals.model_evaluated_problems(path, self.root))

    def test_raw_and_compact_gate_equal(self):
        """tương-đương: SC6 / RK1 each of the 13 edits gives EXACTLY the set of lines the old gate gave on raw logs (paths spelled alike)."""
        self.assertEqual(sorted(label for label, _ in MUTATIONS), sorted(self.golden))
        for label, mutate in MUTATIONS:
            with self.subTest(label):
                self.assertEqual(self.golden[label], self.problems_for(mutate))

    def test_golden_is_not_trivial(self):
        """tương-đương: the golden answers cover both an empty list and edits that really make the gate speak (a golden of empty lists would pass a gate that checks nothing)."""
        sizes = {label: len(lines) for label, lines in self.golden.items()}
        self.assertEqual(0, sizes["as committed"])
        self.assertGreaterEqual(sum(1 for n in sizes.values() if n), 11)
        self.assertEqual(18, sizes["dqa targets claude-code only"])

    def test_the_fixture_is_the_committed_evidence(self):
        """tương-đương: the frozen fixture catalog and evidence files are the ones the repository ships today, so the golden answers describe the real data."""
        for rel in ("catalog.json", "data-quality-audit/evidence/SPR-18.json", "skill-creator-studio/evidence/studio-SPR-02.json"):
            self.assertEqual((ROOT / "evals" / rel).read_bytes(), (GATE_FIXTURE / "evals" / rel).read_bytes(), rel)


class BatchFixtureTests(unittest.TestCase):
    SKILL, BATCH = "fixture-skill", "B1"

    def test_fixture_compact_file_is_read_by_the_gate(self):
        """tương-đương: the committed tests/fixtures/batch/compact.json is a file the loader accepts for the fixture skill and batch."""
        batch = E.evals.load_batch(COMPACT, ROOT, self.SKILL, self.BATCH)
        self.assertEqual(6, len(batch["logs"]))
        self.assertEqual(1, len(batch["smoke"]))
        self.assertEqual(["2026-10-18"], sorted(batch["ab"]))

    def test_compact_file_loads_back_to_what_the_raw_folder_gives(self):
        """tương-đương: the file `compact` writes is read back by `load_batch` as the very dict `raw_batch` built from the raw folder (serialisation loses nothing)."""
        with tempfile.TemporaryDirectory() as t:
            out = write_compact(RAW, self.SKILL, self.BATCH, Path(t) / "evals" / "x" / "evidence" / "B1.json")
            self.assertEqual(activation.raw_batch(RAW, self.SKILL, self.BATCH), E.evals.load_batch(out, Path(t), self.SKILL, self.BATCH))


if __name__ == "__main__":
    unittest.main()
