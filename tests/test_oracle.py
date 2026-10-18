import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("oracle", ROOT / "evals" / "tools" / "oracle.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)

DQA = ROOT / "evals" / "data-quality-audit"
SCRIPT = ROOT / "skills" / "data-quality-audit" / "scripts" / "validate_csv.py"

# case id -> (fixture, script args exactly as the case prompt implies, baseline-style answer, numbered by data row)
CASES = {
    "csv-clean": ("clean.csv", ["--required", "id,amount", "--keys", "id", "--numeric", "amount"],
                  "I checked the file. It has 3 rows, id is unique and amount is numeric in every row, so the checks I ran passed."),
    "csv-duplicate": ("duplicates.csv", ["--required", "id,amount", "--keys", "id", "--numeric", "amount"],
                      "Row 2 has a blank amount (id 2). The id 1 appears twice, in rows 1 and 3, so that is a duplicate id."),
    "csv-invalid-numeric": ("invalid_numeric.csv", ["--required", "id,amount", "--keys", "id", "--numeric", "amount"],
                            "Row 2 has the amount 'hello', which is not a number. The other rows are fine."),
    "data-quality-audit-edge-2": ("order_lines.csv", ["--required", "order_id,line_no", "--keys", "order_id,line_no", "--numeric", "amount"],
                                  "Using order_id plus line_no as the key, the pair (1, 1) appears in rows 1 and 3, so that row repeats."),
    "data-quality-audit-input-error": ("missing_column.csv", ["--required", "customer_id,id", "--keys", "id"],
                                       "This file has no customer_id column (only id and amount), so I cannot check it."),
}


def load(case_id):
    return json.loads((DQA / "expected" / (case_id + ".json")).read_text(encoding="utf-8"))


class OracleTests(unittest.TestCase):
    def script_output(self, fixture, args):
        p = subprocess.run([sys.executable, "-I", "-X", "utf8", str(SCRIPT), "--file", str(DQA / "fixtures" / fixture), *args],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.assertIn(p.returncode, (0, 1), p.stderr)
        return p.stdout

    def test_real_script_output_passes_oracle(self):
        for cid, (fx, args, _) in CASES.items():
            r = oracle.grade(self.script_output(fx, args), load(cid))
            self.assertTrue(r["pass"], (cid, r))

    def test_baseline_style_answer_passes_oracle(self):
        """A correct answer that numbers by data row and uses plain words must not lose to the skill (no fake 'better')."""
        for cid, (_, _, answer) in CASES.items():
            r = oracle.grade(answer, load(cid))
            self.assertTrue(r["pass"], (cid, r))

    def test_wrong_or_empty_answers_fail(self):
        for cid in CASES:
            self.assertFalse(oracle.grade("Everything looks fine, no problems found.", load(cid))["pass"], cid)
        self.assertFalse(oracle.grade("Duplicate id found in rows 7 and 9, amount blank.", load("csv-duplicate"))["pass"])

    def test_near_miss_wrong_answers_fail(self):
        dup, edge, inv = load("csv-duplicate"), load("data-quality-audit-edge-2"), load("csv-invalid-numeric")
        for bad in ("No duplicates. amount blank row 3", "Duplicate id found, amount is blank.", "No duplicate ids; the amount is blank in row 4.",
                    "Row 3 has a blank amount. The ids are unique, duplicates: none."):
            self.assertFalse(oracle.grade(bad, dup)["pass"], bad)
        for bad in ("Order 1 has 3 lines; order_id and line_no look fine.", "No duplicates by order_id and line_no, row 4 checked.",
                    "The composite key order_id + line_no repeats, but I cannot say where."):
            self.assertFalse(oracle.grade(bad, edge)["pass"], bad)
        for bad in ("All amounts are numeric; row 3 is fine.", "Row 3 is empty but nothing is wrong with the amount numbers... all numeric."):
            self.assertFalse(oracle.grade(bad, inv)["pass"], bad)
        self.assertTrue(oracle.grade("Duplicate id on rows 1 and 3; blank amount in row 2.", dup)["pass"])
        self.assertTrue(oracle.grade("The key order_id+line_no repeats: rows 1 and 3.", edge)["pass"])

    def test_input_error_phrasings(self):
        o = load("data-quality-audit-input-error")
        for ok in ("'customer_id' is not in CSV header", "no customer_id column", "customer_id doesn't exist in this file", "the file lacks a customer_id"):
            self.assertTrue(oracle.grade(ok, o)["pass"], ok)
        self.assertTrue(oracle.grade("customer_id is missing, so the check could not be passed", o)["pass"])
        for bad in ("every row has a customer_id present", "the customer_id check passed"):
            self.assertFalse(oracle.grade(bad, o)["pass"], bad)

    def test_numbering_in_both_conventions(self):
        o = load("csv-duplicate")
        tail = " duplicate id, amount blank."
        for loc in ('"row": 4', "Row #4", "rows 2 and 4", "rows 1 and 3", "line 3"):
            self.assertTrue(oracle.grade(loc + tail, o)["pass"], loc)


if __name__ == "__main__":
    unittest.main()
