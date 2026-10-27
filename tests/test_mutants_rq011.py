"""SPR-02 TK8 (RQ-011, FR8): tests written to kill the 19 mutants registered before the work began.

Groups: C = the forcing-word lint (CT10) and the comment/prose scanners; D = doctor (folder scan limits, de-duplication,
baseline diff, case folding); F = the three RQ-009 link fixes (covered in tests/test_link_holes.py; the notes below say which).
Every test is labelled `bắt-lỗi` and names the mutant it kills (ids as in the sprint's evidence/mutants.md).
The tests call the engine through its modules and read no engine source.
"""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

lint, fs, doctor, const = E.lint, E.fs, E.doctor, E.const

MANIFEST = Path("SKILL.md")


def ct10(body: str) -> list:
    """Line numbers (1-based, body_start 0) of the CT10 findings in `body`."""
    return [f["line"] for f in lint.lint_forcing_words(body, 0, MANIFEST) if f["code"] == "CT10"]


class ForcingWordLintMutants(unittest.TestCase):
    def test_c1_list_context_ends_with_the_list(self):
        """bắt-lỗi (giết C1): after a list a plain paragraph ends the list context, so a later indented block is code and is not linted."""
        self.assertEqual(ct10("- item\n\nPlain paragraph.\n\n    MUST do this\n"), [])

    def test_c2_indented_code_state_ends_at_a_plain_line(self):
        """bắt-lỗi (giết C2): an indented line that follows a plain line is a continuation, not code, even after an earlier code block."""
        body = "Intro.\n\n    code block\n\nPlain text.\n    MUST lazily continued\n"
        self.assertEqual(ct10(body), [6])

    def test_c3_indented_paragraph_in_a_list_item_is_prose(self):
        """bắt-lỗi (giết C3): a blank line and four spaces inside a list item is a continuation paragraph, so it is linted."""
        self.assertEqual(ct10("- item\n\n    MUST continue the item\n"), [3])

    def test_c3_control_indented_block_outside_a_list_is_code(self):
        """bắt-lỗi (giết C3): the same shape outside a list is code and stays unlinted (guards against over-linting the other way)."""
        self.assertEqual(ct10("Intro.\n\n    MUST be code\n"), [])

    def test_c4_reason_hidden_in_a_code_span_does_not_count(self):
        """bắt-lỗi (giết C4): a reason word inside inline code or a link is not prose, so the forcing word still has no reason."""
        self.assertEqual(ct10("NEVER run this `because`.\n"), [1])
        self.assertEqual(ct10("ALWAYS check [because](https://example.com/since).\n"), [1])
        self.assertEqual(ct10("NEVER run this because it deletes data.\n"), [])

    def test_c5_a_fence_closes_only_with_at_least_as_many_marks(self):
        """bắt-lỗi (giết C5): inside a four-backtick fence a three-backtick line does not close it; the forcing word inside stays unlinted."""
        body = "````\n```\nMUST do it\n````\nAfter.\n"
        self.assertEqual(ct10(body), [])
        self.assertEqual(ct10("````\n```\nMUST do it\n`````\nNEVER skip\n"), [5], "a longer closing run does close it")

    def test_c6_two_comments_on_one_line_leave_the_text_between(self):
        """bắt-lỗi (giết C6): each comment closes at the nearest '-->'; the words between two comments are prose and are linted."""
        self.assertEqual(fs.strip_html_comments("<!-- a --> MUST <!-- b -->"), "  MUST  ")
        self.assertEqual(ct10("<!-- a --> MUST do x <!-- b -->\n"), [1])

    def test_c7_text_after_a_closing_comment_is_judged_by_itself(self):
        """bắt-lỗi (giết C7): after the '-->' that ends a multi-line comment, the rest of the line is re-trimmed; a table row there is not prose."""
        self.assertEqual(lint.prose_lines("<!--\nx\n--> | a | b |\n"), [])
        self.assertEqual(lint.prose_lines("<!--\nx\n-->   \n    indented\nword\n"), [(5, "word")], "a blank rest is a blank line, so the next indented line is code")


def make_skill(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text("---\nname: %s\ndescription: Toy. Use when testing.\n---\n\n# T\n" % path.name, encoding="utf-8")
    return path


class DoctorScanMutants(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "root"
        self.root.mkdir()
        E.clear_caches()
        self.addCleanup(E.clear_caches)

    def names(self, skills):
        return sorted(p.relative_to(self.root).as_posix() for p in skills)

    def reasons(self, skipped):
        return sorted(item["reason"] for item in skipped)

    def test_d1_the_folder_limit_allows_exactly_that_many_folders(self):
        """bắt-lỗi (giết D1): a tree of exactly DOCTOR_MAX_DIRS folders is scanned whole; only the folder after the limit is skipped."""
        make_skill(self.root / "a")
        make_skill(self.root / "b")  # listed: root, a, b = 3
        with mock.patch.object(const, "DOCTOR_MAX_DIRS", 3):
            skills, skipped = doctor.iter_skill_dirs([self.root])
        self.assertEqual(self.names(skills), ["a", "b"])
        self.assertEqual(skipped, [])
        make_skill(self.root / "c")  # a fourth folder is over the limit
        with mock.patch.object(const, "DOCTOR_MAX_DIRS", 3):
            skills, skipped = doctor.iter_skill_dirs([self.root])
        self.assertEqual(self.reasons(skipped), ["limit"])

    def test_d2_the_skill_limit_stops_at_that_many_skills(self):
        """bắt-lỗi (giết D2): with DOCTOR_MAX_SKILLS = 2 and three skills, two are listed and the third is skipped as 'limit'."""
        for name in ("a", "b", "c"):
            make_skill(self.root / name)
        with mock.patch.object(const, "DOCTOR_MAX_SKILLS", 2):
            skills, skipped = doctor.iter_skill_dirs([self.root])
        self.assertEqual(self.names(skills), ["a", "b"])
        self.assertEqual(self.reasons(skipped), ["limit"])

    def test_d3_the_depth_limit_counts_the_folder_being_entered(self):
        """bắt-lỗi (giết D3): with DOCTOR_MAX_DEPTH = 2 a skill two levels down is found, one three levels down is skipped as 'limit'."""
        make_skill(self.root / "x" / "y")
        make_skill(self.root / "p" / "q" / "r")
        with mock.patch.object(const, "DOCTOR_MAX_DEPTH", 2):
            skills, skipped = doctor.iter_skill_dirs([self.root])
        self.assertEqual(self.names(skills), ["x/y"])
        self.assertEqual(self.reasons(skipped), ["limit"])
        self.assertTrue(skipped[0]["path"].endswith("p/q/r"), skipped)

    def test_d4_a_root_given_twice_is_scanned_once(self):
        """bắt-lỗi (giết D4): the same root listed twice is scanned once; with a limit of exactly its size no 'limit' skip appears."""
        make_skill(self.root / "a")
        make_skill(self.root / "b")
        with mock.patch.object(const, "DOCTOR_MAX_DIRS", 3):
            skills, skipped = doctor.iter_skill_dirs([self.root, self.root])
        self.assertEqual(self.names(skills), ["a", "b"])
        self.assertEqual(skipped, [])

    def test_d5_a_skill_reached_from_two_roots_is_listed_once(self):
        """bắt-lỗi (giết D5): a root and a skill folder inside it are different roots, yet the skill is reported once."""
        make_skill(self.root / "a")
        skills, _skipped = doctor.iter_skill_dirs([self.root, self.root / "a"])
        self.assertEqual(self.names(skills), ["a"])

    def test_d6_silent_prune_names_match_whatever_the_case(self):
        """bắt-lỗi (giết D6): a folder named '.GIT' is pruned silently like '.git': no skill from it and no skipped line."""
        make_skill(self.root / "ok")
        make_skill(self.root / ".GIT" / "hidden")
        skills, skipped = doctor.iter_skill_dirs([self.root])
        self.assertEqual(self.names(skills), ["ok"])
        self.assertEqual(skipped, [])


def report(codes, path="/r/s", roots=("/r",)):
    return {"roots": list(roots), "skills": [{"path": path, "codes": [{"level": lv, "code": c} for lv, c in codes]}]}


class DoctorBaselineMutants(unittest.TestCase):
    def test_d7_a_new_note_is_not_a_new_finding(self):
        """bắt-lỗi (giết D7): NOTE codes are information; one that appears since the baseline is not reported as new."""
        self.assertEqual(doctor.diff_baseline(report([("NOTE", "SZ9")]), report([])), [])
        found = doctor.diff_baseline(report([("WARN", "CT10"), ("NOTE", "SZ9")]), report([]))
        self.assertEqual([(x["code"], x["before"], x["after"]) for x in found], [("CT10", 0, 1)])

    def test_d8_an_equal_count_is_not_new_only_a_higher_one_is(self):
        """bắt-lỗi (giết D8): the same number of a code as in the baseline is not new; one more is."""
        same = [("WARN", "CT10"), ("ERROR", "FM1")]
        self.assertEqual(doctor.diff_baseline(report(same), report(same)), [])
        found = doctor.diff_baseline(report(same + [("WARN", "CT10")]), report(same))
        self.assertEqual([(x["code"], x["before"], x["after"]) for x in found], [("CT10", 1, 2)])

    def test_d9_on_windows_the_root_prefix_is_matched_without_case(self):
        """bắt-lỗi (giết D9): with Windows naming ('nt'), a path under 'c:/work' written 'C:/Work/...' is made relative; elsewhere case matters."""
        nt = types.SimpleNamespace(name="nt")
        posix = types.SimpleNamespace(name="posix")
        with mock.patch.object(doctor, "os", nt):
            self.assertEqual(doctor._under_roots("C:/Work/Skills/a", ["c:/work"]), "Skills/a")
        with mock.patch.object(doctor, "os", posix):
            self.assertEqual(doctor._under_roots("C:/Work/Skills/a", ["c:/work"]), "C:/Work/Skills/a")
            self.assertEqual(doctor._under_roots("c:/work/Skills/a", ["c:/work"]), "Skills/a")


if __name__ == "__main__":
    unittest.main()
