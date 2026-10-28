"""The sharper half of the contract suite (SPR-04 TK1, RQ-024): strict.json holds the whole normalised stderr and the line end of every file a case writes,
so a changed message or a changed line end of a generated file is caught even when the old comparison (stderr prefix, CRLF-folded hashes) stays blind.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_runner as runner  # noqa: E402

ROOT = Path("/zz-no-such-root")
OTHER_EOL = "\n" if os.linesep == "\r\n" else "\r\n"  # the line end this OS does not write by default


class MutatedEngineTests(unittest.TestCase):
    """A copy of the engine with one deliberate change, run through the real runner for one case."""

    def mutated_run(self, rel: str, old: str, new: str, case_id: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        engine = Path(tmp.name) / "engine"
        runner.build_repo(runner.REPO_ROOT, engine)
        target = engine / rel
        text = target.read_text(encoding="utf-8")
        self.assertIn(old, text, "the mutation anchor moved: update this test")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        strict: dict = {}
        results = runner.run_all(engine, case_id, exact=True, strict=strict)
        return results, strict

    def test_strict_catches_message_change(self):
        """bắt-lỗi (red at 53c2d76: no strict comparison): the words of a stderr line change after its prefix `ERROR` -> only strict reports it."""
        results, strict = self.mutated_run("skills/skill-creator-studio/scripts/studio.py", "provide a skill path or --all",
                                           "name a skill path or --all", "R-validate-no-argument")
        self.assertEqual([], runner.compare(results, runner.load_golden()), "the old comparison keeps only the prefix, so it must stay blind here")
        problems = runner.compare_strict(strict, runner.load_strict())
        self.assertEqual(1, len(problems), problems)
        self.assertIn("R-validate-no-argument: strict stderr differs", problems[0])

    def test_strict_catches_eol_change(self):
        """bắt-lỗi (red at 53c2d76): `new` writes SKILL.md with the other line end -> the CRLF-folded hash is unchanged, only strict reports it."""
        old = 'p.write_text(content, encoding="utf-8")'
        new = 'p.write_bytes(content.replace("\\n", %r).encode("utf-8"))' % OTHER_EOL
        results, strict = self.mutated_run("skills/skill-creator-studio/scripts/studio_scaffold.py", old, new, "R-new-en")
        self.assertEqual([], runner.compare(results, runner.load_golden()), "the old comparison folds CRLF to LF, so it must stay blind here")
        problems = runner.compare_strict(strict, runner.load_strict())
        self.assertEqual(1, len(problems), problems)
        self.assertIn("R-new-en: strict line ends differ", problems[0])

    def test_unmutated_engine_passes_strict_for_every_case_with_an_entry(self):
        """tương-đương: the engine under test answers strict.json exactly (the recording is stable run to run)."""
        strict: dict = {}
        runner.run_all(runner.REPO_ROOT, strict=strict)
        self.assertEqual([], runner.compare_strict(strict, runner.load_strict()))


class StderrAndEolTests(unittest.TestCase):
    def test_stderr_norm_folds_root_separators_and_crlf(self):
        """tương-đương: the root (any spelling, one or several) becomes <ROOT>, backslashes become slashes, CRLF becomes LF; the words stay."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            other = root / "b"
            other.mkdir()
            text = "ERROR: %s is bad\r\nsee %s\\x\r\n" % (str(root).replace("/", "\\"), other)
            got = runner.stderr_norm(text, [root, other])
            self.assertEqual("ERROR: <ROOT> is bad\nsee <ROOT>/x\n", got)
            self.assertEqual("at <ROOT>/q\n", runner.stderr_norm("at %s/q\n" % str(root).replace("\\", "/").upper(), root))

    def test_stderr_norm_hides_the_argparse_wording_of_python_3_9_and_3_12_but_keeps_the_error_line(self):
        """bắt-lỗi (red at 5a24145: CI python 3.9 differed from the 3.12 recording): usage block and `choose from` list are folded; the error line of Studio's parser is not."""
        py312 = ("usage: studio.py [-h] [--version]\n                 {new,check}\n                 ...\n"
                 "studio.py: error: argument command: invalid choice: 'x' (choose from new, check)\n")
        py39 = ("usage: studio.py [-h] [--version]\n                 {new,check}\n                 ...\n"
                "studio.py: error: argument command: invalid choice: 'x' (choose from 'new', 'check')\n")
        self.assertEqual(runner.stderr_norm(py312, ROOT), runner.stderr_norm(py39, ROOT))
        self.assertIn("studio.py: error: argument command: invalid choice: 'x' (choose from <CHOICES>)", runner.stderr_norm(py39, ROOT))
        self.assertNotEqual(runner.stderr_norm(py312, ROOT), runner.stderr_norm(py312.replace("invalid choice", "unknown choice"), ROOT))

    def test_eol_map_names_lf_crlf_mixed_and_ignores_missing(self):
        """tương-đương: one word per file, folders skipped, a missing path is empty."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            (root / "a.txt").write_bytes(b"x\ny\n")
            (root / "sub" / "b.txt").write_bytes(b"x\r\ny\r\n")
            (root / "c.txt").write_bytes(b"x\r\ny\n")
            (root / "d.txt").write_bytes(b"no line end")
            self.assertEqual({"a.txt": "lf", "c.txt": "mixed", "d.txt": "lf", "sub/b.txt": "crlf"}, runner.eol_map(root))
            self.assertEqual({}, runner.eol_map(root / "nope"))

    def test_native_matches_the_default_line_end_of_this_os_only(self):
        """tương-đương: "native" equals whatever this OS writes by default; an explicit word must match exactly; the key sets must match."""
        native = runner.native_eol()
        self.assertTrue(runner.eol_equal({"f": "native"}, {"f": native}))
        self.assertFalse(runner.eol_equal({"f": "native"}, {"f": "mixed"}))
        self.assertFalse(runner.eol_equal({"f": "lf"}, {"f": "crlf"}))
        self.assertFalse(runner.eol_equal({"f": "lf"}, {"f": "lf", "g": "lf"}))
        self.assertEqual({"f": "native", "g": "mixed"}, runner.to_native({"f": native, "g": "mixed"}))

    def test_a_case_without_a_strict_entry_is_only_compared_the_old_way(self):
        """tương-đương: FR10 a new case that strict.json does not list produces no strict problem."""
        self.assertEqual([], runner.compare_strict({"new-case": {"stderr": "anything", "eol": {"f": "lf"}}}, {}))

    def test_strict_json_is_recorded_at_the_frozen_commit_and_covers_the_original_suite(self):
        """tương-đương: recorded_at_commit is the commit the strict answers were taken at, and every case of golden.json that existed then has an entry."""
        raw = json.loads(runner.STRICT_FILE.read_text(encoding="utf-8"))
        self.assertEqual("53c2d76", raw["recorded_at_commit"])
        for cid, entry in raw["cases"].items():  # every entry: flat {stderr, eol}, or wrapped {changed_by, before: {stderr, eol}, after}
            with self.subTest(case=cid):
                if "changed_by" in entry:
                    self.assertEqual({"changed_by", "before", "after"}, set(entry))
                    self.assertEqual({"stderr", "eol"}, set(entry["before"]))
                else:
                    self.assertEqual({"stderr", "eol"}, set(entry))
        self.assertLessEqual(len(raw["cases"]), len(runner.load_golden()))
        self.assertGreaterEqual(len(raw["cases"]), 96)


class FileBackedTests(unittest.TestCase):
    """--add-case, --record-after and --record-strict on throw-away copies of the three files; the engine run is faked."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.golden_file, self.cases_file, self.strict_file = (self.tmp / n for n in ("golden.json", "cases.json", "strict.json"))
        self.old = {"exit": 0, "stderr": "ERROR"}
        self.new = {"exit": 1, "stderr": "ERROR"}
        self.entry = {"stderr": "ERROR: old\n", "eol": {"<TMP>/out/f.md": "native"}}
        self.write(self.golden_file, {"schema": 1, "source": "t", "cases": {"old-case": copy.deepcopy(self.old)}})
        self.write(self.strict_file, {"recorded_at_commit": "abc1234", "cases": {"old-case": copy.deepcopy(self.entry)}})
        cases = [{"id": "old-case", "via": "R", "args": ["x"], "compare": ["exit"]}, {"id": "fresh-case", "via": "R", "args": ["y"], "compare": ["exit"]}]
        self.write(self.cases_file, {"cases": cases})
        self.fake_strict = {"stderr": "ERROR: new\n", "eol": {"<TMP>/out/f.md": runner.native_eol(), "<TMP>/out/g.md": "mixed"}}

    @staticmethod
    def write(path: Path, value) -> None:
        path.write_text(json.dumps(value, indent=1) + "\n", encoding="utf-8")

    def read(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def fake_run_all(self, result):
        def run(engine, only="", exact=False, strict=None):
            if strict is not None:
                strict[only] = copy.deepcopy(self.fake_strict)
            return {only: copy.deepcopy(result)}
        return run

    def call(self, fn, *args, result=None):
        patches = [mock.patch.object(runner, "GOLDEN_FILE", self.golden_file), mock.patch.object(runner, "CASES_FILE", self.cases_file),
                   mock.patch.object(runner, "STRICT_FILE", self.strict_file), mock.patch.object(runner, "run_all", self.fake_run_all(result or self.new))]
        err = io.StringIO()
        with contextlib.ExitStack() as stack, contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            for patch in patches:
                stack.enter_context(patch)
            code = fn(*args)
        return code, err.getvalue()

    def test_add_case_refuses_existing_id(self):
        """bắt-lỗi (red at 53c2d76: no --add-case): an id that already has a golden answer exits 2 and neither file moves; an id missing from cases.json too."""
        golden, strict = self.golden_file.read_bytes(), self.strict_file.read_bytes()
        code, err = self.call(runner.cmd_add_case, "old-case", self.tmp)
        self.assertEqual(2, code)
        self.assertIn("--record-after", err)
        code, err = self.call(runner.cmd_add_case, "not-a-case", self.tmp)
        self.assertEqual(2, code)
        self.assertIn("cases.json", err)
        self.assertEqual((golden, strict), (self.golden_file.read_bytes(), self.strict_file.read_bytes()))

    def test_add_case_writes_before_and_a_strict_entry_without_touching_the_rest(self):
        """bắt-lỗi (red at 53c2d76): the new case gets its answer in golden.json and its stderr + line ends in strict.json; the old entries stay byte for byte; the OS-default line end is stored as native."""
        code, _err = self.call(runner.cmd_add_case, "fresh-case", self.tmp)
        self.assertEqual(0, code)
        golden, strict = self.read(self.golden_file)["cases"], self.read(self.strict_file)
        self.assertEqual({"old-case": self.old, "fresh-case": self.new}, golden)
        self.assertEqual("abc1234", strict["recorded_at_commit"])
        self.assertEqual(self.entry, strict["cases"]["old-case"])
        self.assertEqual({"stderr": "ERROR: new\n", "eol": {"<TMP>/out/f.md": "native", "<TMP>/out/g.md": "mixed"}}, strict["cases"]["fresh-case"])

    def test_record_after_updates_strict(self):
        """bắt-lỗi (red at 53c2d76: strict untouched): --record-after wraps the strict entry like golden: `before` stays, `after` is the new stderr and line ends."""
        code, _err = self.call(runner.cmd_record_after, "old-case", "SPR-04/TK9", self.tmp)
        self.assertEqual(0, code)
        self.assertEqual({"changed_by": "SPR-04/TK9", "before": self.old, "after": self.new}, self.read(self.golden_file)["cases"]["old-case"])
        after = {"stderr": "ERROR: new\n", "eol": {"<TMP>/out/f.md": "native", "<TMP>/out/g.md": "mixed"}}  # f.md was native before and is still the OS default: stays native
        self.assertEqual({"changed_by": "SPR-04/TK9", "before": self.entry, "after": after}, self.read(self.strict_file)["cases"]["old-case"])
        self.assertEqual(after, runner.expected_result({"changed_by": "x", "before": self.entry, "after": after}))

    def test_record_after_stores_a_pinned_line_end_raw(self):
        """bắt-lỗi (red at 5a24145): RF-1.1 a file that was native and now has the line end this OS does NOT write by default is stored raw, not native; one that was not native is never turned into native."""
        other = "lf" if runner.native_eol() == "crlf" else "crlf"
        self.fake_strict["eol"] = {"<TMP>/out/f.md": other, "<TMP>/out/h.md": runner.native_eol()}
        self.entry["eol"]["<TMP>/out/h.md"] = "lf" if runner.native_eol() == "crlf" else "crlf"  # h.md was pinned, f.md was native
        self.write(self.strict_file, {"recorded_at_commit": "abc1234", "cases": {"old-case": copy.deepcopy(self.entry)}})
        self.call(runner.cmd_record_after, "old-case", "SPR-04/TK9", self.tmp)
        eol = self.read(self.strict_file)["cases"]["old-case"]["after"]["eol"]
        self.assertEqual({"<TMP>/out/f.md": other, "<TMP>/out/h.md": runner.native_eol()}, eol)

    def test_record_strict_is_refused_when_the_file_exists_and_needs_a_commit(self):
        """bắt-lỗi (red at 53c2d76): --record-strict never rewrites strict.json; `main` demands --at-commit."""
        original = self.strict_file.read_bytes()
        code, err = self.call(runner.cmd_record_strict, "def5678", self.tmp)
        self.assertEqual(2, code)
        self.assertIn("exists", err)
        self.assertEqual(original, self.strict_file.read_bytes())
        with mock.patch.object(runner, "STRICT_FILE", self.strict_file), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            runner.main(["--record-strict"])
        self.assertEqual(2, ctx.exception.code)

    def test_record_strict_creates_the_file_with_native_line_ends(self):
        """tương-đương: with no strict.json the run is stored with the commit label and the OS-default line end written as native."""
        self.strict_file.unlink()
        self.fake_strict["eol"] = {"f": runner.native_eol(), "g": "mixed"}
        patches = [mock.patch.object(runner, "STRICT_FILE", self.strict_file),
                   mock.patch.object(runner, "run_all", lambda engine, only="", exact=False, strict=None: strict.update({"c1": self.fake_strict}) or {})]
        strict = {}
        with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
            for patch in patches:
                stack.enter_context(patch)
            code = runner.cmd_record_strict("def5678", self.tmp)
        self.assertEqual(0, code)
        self.assertEqual({"recorded_at_commit": "def5678", "cases": {"c1": {"stderr": "ERROR: new\n", "eol": {"f": "native", "g": "mixed"}}}}, self.read(self.strict_file))


if __name__ == "__main__":
    unittest.main()
