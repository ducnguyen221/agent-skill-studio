"""SPR-01 TK6 (FR7 "Nên có"): SZ1 as ERROR, `--roots-file` trailing comments, baseline keyed by the path under the root.

`STUDIO_UNDER_TEST` (a repo root) points the tests at another tree, for the red run on a copy of df875ce.
Run: python -X utf8 -m pytest tests/test_validator_fr7_should.py -q -p no:cacheprovider
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(os.environ.get("STUDIO_UNDER_TEST") or Path(__file__).resolve().parents[1])
CODE = ROOT / "skills" / "skill-creator-studio" / "scripts" / "studio.py"
_SPEC = importlib.util.spec_from_file_location("studio_fr7_should_impl", CODE)
studio = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(studio)

SKILL = "---\nname: %s\ndescription: Checks a toy example. Use when testing the doctor command.\n---\n\n# Title\n\nShort body.\n"


def make_skill(parent: Path, name: str) -> Path:
    folder = parent / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_bytes((SKILL % name).encode("utf-8"))  # bytes: write_text(newline=) needs Python 3.10
    return folder


def doctor(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = studio.main(["doctor", *argv])
    return code, out.getvalue(), err.getvalue()


class ShouldCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class OversizedSkillTest(ShouldCase):
    def test_sz1_oversized_skill_md_is_an_error(self):
        """bắt-lỗi: SZ1 a SKILL.md above the size cap is an ERROR (it was not linted, so it cannot pass)."""
        folder = make_skill(self.tmp / "roots", "big-skill")
        with open(folder / "SKILL.md", "a", encoding="utf-8", newline="\n") as handle:
            handle.write("More text.\n" * 40)
        found = [f for f in studio.validate_skill(folder, max_file_bytes=200) if f["code"] == "SZ1"]
        self.assertEqual([f["level"] for f in found], ["ERROR"])
        code, _, _ = doctor("--roots", str(self.tmp / "roots"), "--fail-on", "error")
        self.assertEqual(code, 0, "the doctor cap is 1 MB, far above this skill")


class RootsFileCommentTest(ShouldCase):
    def test_roots_file_trailing_comment(self):
        """bắt-lỗi: a `--roots-file` line may end with `  # note`; a `#` inside a name stays part of the path."""
        root = self.tmp / "my roots"
        make_skill(root, "one-skill")
        odd = self.tmp / "a#b"
        make_skill(odd, "two-skill")
        listing = self.tmp / "roots.txt"
        listing.write_text("# header\n%s   # my skills\n%s\n" % (root, odd), encoding="utf-8")
        code, out, err = doctor("--roots-file", str(listing), "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(Path(s["path"]).name for s in json.loads(out)["skills"]), ["one-skill", "two-skill"])


class BaselineRelativeTest(ShouldCase):
    def test_baseline_matches_after_the_tree_moves(self):
        """bắt-lỗi: a baseline taken in one checkout still matches the same skills in another (keyed under the root)."""
        first = self.tmp / "one" / "skills"
        (make_skill(first, "has-docs") / "docs").mkdir()
        report = self.tmp / "baseline.json"
        doctor("--roots", str(first), "--out", str(report))
        second = self.tmp / "two" / "skills"
        shutil.copytree(first, second)
        code, out, err = doctor("--roots", str(second), "--json", "--baseline", str(report), "--fail-on", "new")
        self.assertEqual((code, json.loads(out)["new_vs_baseline"]), (0, []), err)

    def test_baseline_still_reports_a_real_new_finding(self):
        """tương-đương: a skill that gained a finding since the baseline is still listed, with its current path."""
        first = self.tmp / "one" / "skills"
        make_skill(first, "later-docs")
        report = self.tmp / "baseline.json"
        doctor("--roots", str(first), "--out", str(report))
        (first / "later-docs" / "docs").mkdir()
        code, out, _ = doctor("--roots", str(first), "--json", "--baseline", str(report), "--fail-on", "new")
        listed = json.loads(out)["new_vs_baseline"]
        self.assertEqual((code, [(Path(x["path"]).name, x["code"]) for x in listed]), (1, [("later-docs", "ST8")]))


if __name__ == "__main__":
    unittest.main()
