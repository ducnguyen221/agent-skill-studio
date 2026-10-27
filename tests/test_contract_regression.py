"""Contract regression suite for the studio.py command line (SPR-02, FR11).

The answers in tests/fixtures/contract/golden.json were generated from `git archive 1211bfa` before any engine change.
Every later sprint task must keep them green; a deliberate change carries `changed_by` in cases.json and is answered
by the `after` field of its golden entry.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_runner as runner  # noqa: E402


class ContractRegression(unittest.TestCase):
    results: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.results = runner.run_all(runner.REPO_ROOT)

    def test_every_case_matches_its_frozen_answer(self):
        """tương-đương: each case (exit code, normalised stdout, stderr prefix, file tree, ZIP names) equals the 1211bfa answer."""
        golden = runner.load_golden()
        for case in runner.load_cases():
            cid = case["id"]
            with self.subTest(case=cid):
                self.assertIn(cid, self.results)
                self.assertIn(cid, golden)
                self.assertEqual(runner.dumps(runner.expected_result(golden[cid])), runner.dumps(self.results[cid]))

    def test_cases_and_golden_describe_the_same_suite(self):
        """tương-đương: cases.json and golden.json list the same ids, cover the five ways of calling the engine, mark changes alike."""
        cases = runner.load_cases()
        golden = runner.load_golden()
        ids = [c["id"] for c in cases]
        self.assertEqual(len(ids), len(set(ids)), "duplicate case id")
        self.assertEqual(set(ids), set(golden))
        self.assertTrue({"R", "C", "E", "S", "Z"} <= {c["via"] for c in cases})
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(bool(case.get("changed_by")), "changed_by" in golden[case["id"]])
                if case.get("changed_by"):
                    self.assertEqual(case["changed_by"], golden[case["id"]]["changed_by"])
                    self.assertIn("after", golden[case["id"]])

    def test_frozen_inputs_are_not_the_live_engine_skill(self):
        """tương-đương: the frozen inputs hold no engine script, so a sprint edit of the live skill cannot move their answers."""
        self.assertFalse(list(runner.INPUTS_DIR.rglob("studio.py")))
        self.assertTrue((runner.INPUTS_DIR / "skills" / "data-quality-audit" / "SKILL.md").is_file())
        self.assertFalse((runner.INPUTS_DIR / "skills" / "creator-frozen" / "scripts").exists())


if __name__ == "__main__":
    unittest.main()
