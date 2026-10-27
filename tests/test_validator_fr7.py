"""SPR-01 TK6 (FR7): validate/doctor report what is true. One `bắt-lỗi` test per FR7 item, red on df875ce.

`STUDIO_UNDER_TEST` (a repo root) points the tests at another tree, for the red run on a copy of df875ce.
Run: python -X utf8 -m pytest tests/test_validator_fr7.py -q -p no:cacheprovider
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(os.environ.get("STUDIO_UNDER_TEST") or Path(__file__).resolve().parents[1])
CODE = ROOT / "skills" / "skill-creator-studio" / "scripts" / "studio.py"
_SPEC = importlib.util.spec_from_file_location("studio_fr7_impl", CODE)
studio = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(studio)

GOOD_DESC = "Does a small job. Use when testing the validator."
VI_LINE = "Bước này kiểm tra dữ liệu đầu vào và ghi kết quả ra bảng."


def make_skill(tmp: Path, name: str, body: str, extra=(), desc: str = GOOD_DESC) -> Path:
    folder = tmp / name
    folder.mkdir(parents=True, exist_ok=True)
    head = ["name: " + name, "description: " + json.dumps(desc, ensure_ascii=False), *extra]
    (folder / "SKILL.md").write_text("---\n" + "\n".join(head) + "\n---\n" + body + "\n", encoding="utf-8")
    return folder


def of(findings, code):
    return [f for f in findings if f["code"] == code]


def doctor(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = studio.main(["doctor", *argv])
    return code, out.getvalue(), err.getvalue()


class Fr7Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def validate(self, folder, **kw):
        return studio.validate_skill(folder, **kw)


class IndentedFenceTest(Fr7Case):
    def test_fr71_fence_indented_four_in_list_item_is_a_fence(self):
        """bắt-lỗi: FR7.1 a code fence indented 4+ inside a list item hides its MUST line from CT10."""
        body = "# T\n\n- step one\n\n    ```\n    You MUST do this now\n    ```\n\n1. next\n   ~~~\n   NEVER skip\n   ~~~\n"
        self.assertEqual(of(self.validate(make_skill(self.tmp, "fence-list", body)), "CT10"), [])

    def test_fr71_indented_code_outside_list_unchanged(self):
        """tương-đương: FR7.1 outside a list a 4-space fence line is indented code, and a bare MUST is still flagged."""
        body = "# T\n\nPlain.\n\n    ```\n    still code\n\nYou MUST do it now\n"
        self.assertEqual(len(of(self.validate(make_skill(self.tmp, "fence-plain", body)), "CT10")), 1)


class UnclosedCommentTest(Fr7Case):
    def test_fr72_unclosed_html_comment_warns(self):
        """bắt-lỗi: FR7.2 a `<!--` with no `-->` is reported, with the line where it opens."""
        body = "# T\n\nFine line.\n<!-- never closed\nmore text\n"
        found = of(self.validate(make_skill(self.tmp, "open-comment", body)), "CT11")
        self.assertEqual([(f["level"], f["line"]) for f in found], [("WARN", 8)])

    def test_fr72_closed_and_fenced_comment_quiet(self):
        """tương-đương: FR7.2 closed comments (one or several lines) and a `<!--` in a fence or code span are not reported."""
        body = "# T\n\n<!-- one -->\n<!-- two\nlines -->\n\n```\n<!-- in a fence\n```\n\nUse `<!--` in text.\n"
        self.assertEqual(of(self.validate(make_skill(self.tmp, "closed-comment", body)), "CT11"), [])


class NestedKeyLineTest(Fr7Case):
    def test_fr73_vi4_label_points_at_metadata_line(self):
        """bắt-lỗi: FR7.3 `metadata.license` with Vietnamese letters is reported on its own line, not on the root `license:`."""
        folder = make_skill(self.tmp, "vi-nested", "# Kiểm dữ liệu\n\n" + VI_LINE, extra=("license: MIT", "metadata:", "  license: Đức"))
        found = of(self.validate(folder), "VI4")
        self.assertEqual([f["line"] for f in found], [6])


class St8Test(Fr7Case):
    def test_fr74_st8_folder_names_ignore_case(self):
        """bắt-lỗi: FR7.4 `Evals/`, `EVALS/` and `Tests/` are judged like `evals/` and `tests/` (quiet); `docs/` is still ST8."""
        folder = make_skill(self.tmp, "st8-case", "# T\n\nShort.")
        for name in ("Evals", "EVALS", "Tests", "TESTS", "docs"):
            (folder / name).mkdir(exist_ok=True)
        flagged = sorted(Path(f["path"]).name.lower() for f in of(self.validate(folder), "ST8"))
        self.assertEqual(flagged, ["docs"])


class NewReservedNameTest(Fr7Case):
    def test_fr75_new_refuses_reserved_words_like_fm5(self):
        """bắt-lỗi: FR7.5 `new` with claude/anthropic in the name exits 2 and creates nothing."""
        for name in ("claude-helper", "my-anthropic-tool"):
            before = (ROOT / "evals" / name).exists()
            self.addCleanup(lambda n=name, b=before: None if b else shutil.rmtree(ROOT / "evals" / n, ignore_errors=True))
            res = subprocess.run([sys.executable, "-X", "utf8", str(CODE), "new", name, "--description", "Does X. Use when testing.",
                                  "--output", str(self.tmp / "out")], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertIn("reserved word", res.stderr)
            self.assertFalse((self.tmp / "out" / name).exists())


class Fm4LineTest(Fr7Case):
    def test_fr76_fm4_reports_the_key_line(self):
        """bắt-lỗi: FR7.6 an unknown frontmatter key is reported on its own line."""
        folder = make_skill(self.tmp, "fm4-line", "# T\n\nShort.", extra=("foo: 1", "bar: 2"))
        found = of(self.validate(folder), "FM4")
        self.assertEqual(sorted((f["line"], "foo" in f["message"]) for f in found), [(4, True), (5, False)])


class OutBeforeScanTest(Fr7Case):
    def test_fr77_foreign_json_refused_before_the_scan(self):
        """bắt-lỗi: FR7.7 `--out` on an existing .json that is not a doctor report exits 2 and nothing is scanned."""
        root = self.tmp / "roots"
        make_skill(root, "one-skill", "# T\n\nShort.")
        out = self.tmp / "keep" / "data.json"
        out.parent.mkdir()
        out.write_text('{"mine": 1}\n', encoding="utf-8")
        with mock.patch.object(studio, "iter_skill_dirs", side_effect=AssertionError("scanned before --out was checked")):
            code, _, err = doctor("--roots", str(root), "--out", str(out))
        self.assertEqual(code, 2, err)
        self.assertIn("not a doctor report", err)
        self.assertEqual(out.read_text(encoding="utf-8"), '{"mine": 1}\n')


class LinkParenTest(Fr7Case):
    def test_fr78_link_target_with_parentheses(self):
        """bắt-lỗi: FR7.8 `[a](x(1).md)` is checked: present is quiet, missing is ST6."""
        folder = make_skill(self.tmp, "paren-link", "# T\n\nSee [a](references/x(1).md) and [b](references/gone(2).md).")
        (folder / "references").mkdir()
        (folder / "references" / "x(1).md").write_text("# X\n", encoding="utf-8")
        st6 = of(self.validate(folder), "ST6")
        self.assertEqual([("gone(2).md" in f["message"]) for f in st6], [True])


class WorktreesTest(Fr7Case):
    def test_fr79_ads_worktrees_excluded_like_worktrees(self):
        """bắt-lỗi: FR7.9 the scan leaves out `.ads-worktrees`."""
        self.assertTrue(studio._is_excluded((".ads-worktrees",), False))
        root = self.tmp / "plugins"
        make_skill(root / ".ads-worktrees" / "copy", "dup-skill", "# T\n\nShort.")
        make_skill(root, "real-skill", "# T\n\nShort.")
        code, out, err = doctor("--roots", str(root), "--json")
        names = [Path(s["path"]).name for s in json.loads(out)["skills"]]
        self.assertEqual(names, ["real-skill"], err)


@unittest.skipUnless(os.name == "nt", "8.3 short names exist on Windows only")
class ShortNameZoneTest(Fr7Case):
    def short_of(self, folder: Path) -> str:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetShortPathNameW(str(folder), buf, len(buf)):
            self.skipTest("cannot ask for a short name")
        return buf.value

    def test_fr710_cloud_zone_seen_through_an_8_3_name(self):
        """bắt-lỗi: FR7.10 a path that reaches a cloud-named folder by its 8.3 name is still a `cloud` zone."""
        cloud = self.tmp / "OneDrive - Test Company"
        cloud.mkdir()
        short = self.short_of(cloud)
        if "~" not in Path(short).name:
            self.skipTest("this volume has no 8.3 names")
        self.assertEqual(studio.zone_reason(Path(short) / "skills" / "x"), "cloud")
        self.assertIsNone(studio.zone_reason(self.tmp / "plain" / "x"))


if __name__ == "__main__":
    unittest.main()
