"""The frozen half of the contract suite (SPR-03 TK1, RK2): no `before` of tests/fixtures/contract/golden.json moves, and the only way to change an answer
is `contract_runner.py --record-after <case-id> --by <task>`, which writes `after` and nothing else.

`BEFORE_DIGEST` is the SHA-256 of `json.dumps({case id: before}, sort_keys=True, ensure_ascii=False)` over the 96 golden answers of 3cc1bd3, where
`before` of a flat entry is the entry itself (measured at TK0, evidence/tk0-baseline.txt of SPR-03). It is taken over ORIGINAL_IDS, the 96 ids of that
suite, so a case added later (SPR-04 RQ-024: `--add-case`) does not move it. `STRICT_BEFORE_DIGEST` locks the same way the strict answers of those
96 cases (strict.json, recorded at 53c2d76).
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_runner as runner  # noqa: E402

BEFORE_DIGEST = "4b3c6d47713289adfaa1a0e20c374b30c57c7e587f966a6cf2dcc2f16c1b7c0d"
STRICT_BEFORE_DIGEST = "4715153c1ef0e740af5e96cad7c24566dfbadd9bf08c3828af5904793bcaa5bb"
ORIGINAL_IDS = (
    "C-audit-dqa-json", "C-audit-dqa-text", "C-audit-frozen-json", "C-audit-live-json", "C-doctor-fixture-json", "C-evals-all-json",
    "C-fmt-check-dqa-json", "C-fmt-check-live-json", "C-install-dqa-claude", "C-new-en", "C-new-full", "C-new-full-vi", "C-new-vi", "C-package-dqa",
    "C-sync-template-check", "C-validate-all-require-evals-json", "C-validate-broken-json", "C-validate-dqa-require-evals-json",
    "C-validate-frozen-require-evals-json", "C-validate-missing-path", "C-validate-no-argument", "C-version", "E-audit-dqa-json", "E-audit-dqa-text",
    "E-audit-frozen-json", "E-audit-live-json", "E-doctor-fixture-json", "E-evals-all-json", "E-fmt-check-dqa-json", "E-fmt-check-live-json",
    "E-install-dqa-claude", "E-new-default-output", "E-new-en", "E-new-full", "E-new-full-vi", "E-new-vi", "E-package-dqa", "E-sync-template-check",
    "E-validate-all-require-evals-json", "E-validate-broken-json", "E-validate-dqa-require-evals-json", "E-validate-frozen-require-evals-json",
    "E-validate-missing-path", "E-validate-no-argument", "E-version", "L-evals-all", "L-package-skill-creator-studio", "L-validate-all-require-evals",
    "R-audit-dqa-json", "R-audit-dqa-text", "R-audit-frozen-json", "R-audit-live-json", "R-doctor-fixture-json", "R-evals-all-json",
    "R-fmt-check-dqa-json", "R-fmt-check-live-json", "R-install-dqa-claude", "R-new-en", "R-new-full", "R-new-full-vi", "R-new-vi", "R-package-dqa",
    "R-sync-template-check", "R-validate-all-require-evals-json", "R-validate-broken-json", "R-validate-dqa-require-evals-json",
    "R-validate-frozen-require-evals-json", "R-validate-missing-path", "R-validate-no-argument", "R-version", "S-doctor-fixture-json",
    "S-doctor-self-parent-json", "S-evals-all-outside-repo", "S-fmt-check-dqa-json", "S-fmt-check-self-json", "S-new-en", "S-new-full", "S-new-vi",
    "S-validate-all-outside-repo", "S-validate-dqa-json", "S-validate-frozen-json", "S-validate-self-json", "S-version", "Z-doctor-fixture-json",
    "Z-doctor-self-parent-json", "Z-evals-all-outside-repo", "Z-fmt-check-dqa-json", "Z-fmt-check-self-json", "Z-new-en", "Z-new-full", "Z-new-vi",
    "Z-validate-all-outside-repo", "Z-validate-dqa-json", "Z-validate-frozen-json", "Z-validate-self-json", "Z-version"
)


def before_digest(cases: dict, only: tuple | None = None) -> str:
    """Digest of the `before` of every entry (of the ids in `only`, when given); a flat entry is its own `before`."""
    before = {cid: (entry["before"] if "changed_by" in entry else entry) for cid, entry in cases.items() if only is None or cid in only}
    return hashlib.sha256(json.dumps(before, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class GoldenBeforeFrozenTests(unittest.TestCase):
    def test_golden_before_frozen(self):
        """tương-đương: SC6 the `before` of every golden answer (flat entries count as their own `before`) is the one measured at 3cc1bd3."""
        golden = json.loads(runner.GOLDEN_FILE.read_text(encoding="utf-8"))["cases"]
        self.assertEqual(96, len(ORIGINAL_IDS))
        self.assertTrue(set(ORIGINAL_IDS) <= set(golden), "an original case left golden.json")
        self.assertEqual(BEFORE_DIGEST, before_digest(golden, ORIGINAL_IDS))

    def test_strict_before_frozen(self):
        """tương-đương: RQ-024 the strict answers (full stderr, line ends) of the 96 original cases are the ones recorded at 53c2d76; a deliberate change lives in `after`."""
        strict = json.loads(runner.STRICT_FILE.read_text(encoding="utf-8"))
        self.assertEqual("53c2d76", strict["recorded_at_commit"])
        self.assertTrue(set(ORIGINAL_IDS) <= set(strict["cases"]), "an original case left strict.json")
        self.assertEqual(STRICT_BEFORE_DIGEST, before_digest(strict["cases"], ORIGINAL_IDS))

    def test_a_changed_answer_has_exactly_changed_by_before_after(self):
        """tương-đương: SC6 a wrapped golden entry carries `changed_by`, `before` and `after` and no other key."""
        golden = json.loads(runner.GOLDEN_FILE.read_text(encoding="utf-8"))["cases"]
        for cid, entry in golden.items():
            if "changed_by" in entry:
                with self.subTest(cid):
                    self.assertEqual({"changed_by", "before", "after"}, set(entry))


class RecordAfterTests(unittest.TestCase):
    OLD = {"exit": 0, "stdout_text": "old\n"}
    NEW = {"exit": 1, "stdout_text": "new\n"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.golden_file = self.tmp / "golden.json"
        self.cases_file = self.tmp / "cases.json"
        self.golden = {"flat": copy.deepcopy(self.OLD), "other": {"exit": 2},
                       "wrapped": {"changed_by": "FR10", "before": copy.deepcopy(self.OLD), "after": None}}
        self.golden_file.write_text(json.dumps({"schema": 1, "source": "test", "cases": self.golden}, indent=2) + "\n", encoding="utf-8")
        cases = [{"id": "flat", "via": "R", "args": ["x"], "compare": ["exit"]}, {"id": "other", "via": "R", "args": ["y"], "compare": ["exit"]},
                 {"id": "wrapped", "via": "R", "args": ["z"], "compare": ["exit"], "changed_by": "FR10"}]
        self.cases_file.write_text(json.dumps({"cases": cases}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def run_main(self, *argv, results=None):
        patches = [mock.patch.object(runner, "GOLDEN_FILE", self.golden_file), mock.patch.object(runner, "CASES_FILE", self.cases_file),
                   mock.patch.object(runner, "run_all", return_value=results if results is not None else {k: copy.deepcopy(self.NEW) for k in self.golden})]
        err, out = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack, contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            for patch in patches:
                stack.enter_context(patch)
            try:
                code = runner.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def stored(self) -> dict:
        return json.loads(self.golden_file.read_text(encoding="utf-8"))["cases"]

    def test_record_after_wraps_a_flat_entry_and_keeps_its_before(self):
        """bắt-lỗi (red at 3cc1bd3: no --record-after): RK2 a flat answer becomes {changed_by, before: the old entry byte for byte, after: the new result}; cases.json learns the label too."""
        before_all = before_digest(self.golden)
        code, _out, err = self.run_main("--record-after", "flat", "--by", "SPR-03/TK1")
        self.assertEqual((0, ""), (code, err))
        stored = self.stored()
        self.assertEqual({"changed_by": "SPR-03/TK1", "before": self.OLD, "after": self.NEW}, stored["flat"])
        self.assertEqual({"exit": 2}, stored["other"])
        self.assertEqual(self.golden["wrapped"], stored["wrapped"])
        self.assertEqual(before_all, before_digest(stored))
        cases = {c["id"]: c for c in json.loads(self.cases_file.read_text(encoding="utf-8"))["cases"]}
        self.assertEqual("SPR-03/TK1", cases["flat"]["changed_by"])
        self.assertNotIn("changed_by", cases["other"])

    def test_record_after_on_a_wrapped_entry_writes_only_after(self):
        """bắt-lỗi (red at 3cc1bd3): RK2 an entry that is already wrapped keeps `changed_by` and `before`; only `after` is written."""
        code, _out, _err = self.run_main("--record-after", "wrapped", "--by", "SPR-03/TK2")
        self.assertEqual(0, code)
        self.assertEqual({"changed_by": "FR10", "before": self.OLD, "after": self.NEW}, self.stored()["wrapped"])
        again = {"exit": 3}
        code, _out, _err = self.run_main("--record-after", "wrapped", "--by", "SPR-03/TK2", results={"wrapped": again})
        self.assertEqual(0, code)
        self.assertEqual({"changed_by": "FR10", "before": self.OLD, "after": again}, self.stored()["wrapped"])

    def test_record_after_refuses_an_unknown_case_and_a_missing_label(self):
        """bắt-lỗi (red at 3cc1bd3): a case id that is not in the suite, or no --by, exits 2 and the golden file is untouched."""
        original = self.golden_file.read_bytes()
        code, _out, err = self.run_main("--record-after", "nope", "--by", "SPR-03/TK1", results={})
        self.assertEqual(2, code)
        self.assertIn("nope", err)
        code, _out, _err = self.run_main("--record-after", "flat")
        self.assertEqual(2, code)
        self.assertEqual(original, self.golden_file.read_bytes())

    def test_write_golden_is_refused_when_the_golden_file_exists(self):
        """bắt-lỗi (red at 3cc1bd3: the golden file is rewritten, `before` included): RK2 --write-golden exits 2 and says «use --record-after»."""
        original = self.golden_file.read_bytes()
        code, _out, err = self.run_main("--write-golden")
        self.assertEqual(2, code)
        self.assertIn("--record-after", err)
        self.assertEqual(original, self.golden_file.read_bytes())

    def test_write_golden_still_creates_a_missing_golden_file(self):
        """tương-đương: a tree without a golden file (a new suite) can still be started with --write-golden."""
        self.golden_file.unlink()
        code, _out, _err = self.run_main("--write-golden", results={"flat": self.OLD, "other": {"exit": 2}, "wrapped": self.OLD})
        self.assertEqual(0, code)
        self.assertEqual(self.OLD, self.stored()["flat"])


if __name__ == "__main__":
    unittest.main()
