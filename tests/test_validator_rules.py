"""Offline tests for the validator rules added in SPR-33 TK2.

Covers FM5, --target, FM6, CT10 (SK-14), DS4, DS5, ST2, FM8 and the Contents rules ST5/ST7.
Run: python -X utf8 -m pytest tests/test_validator_rules.py -q -p no:cacheprovider
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "skills" / "skill-creator-studio" / "scripts" / "studio.py"
_SPEC = importlib.util.spec_from_file_location("studio_rules_impl", CODE)
studio = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(studio)
studio_const = sys.modules["studio_const"]  # sibling modules the engine just imported (SPR-02 TK4a)
studio_fs = sys.modules["studio_fs"]
studio_lint = sys.modules["studio_lint"]
studio_validate = sys.modules["studio_validate"]

GOOD_DESC = "Does a small job. Use when testing the validator."


def make_skill(tmp: Path, name: str, frontmatter_lines: list, body: str, refs: dict = None) -> Path:
    """Write tmp/<name>/SKILL.md (+ references/<file>) and return the skill folder."""
    folder = tmp / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text("---\n" + "\n".join(frontmatter_lines) + "\n---\n" + body + "\n", encoding="utf-8")
    for filename, content in (refs or {}).items():
        (folder / "references").mkdir(exist_ok=True)
        (folder / "references" / filename).write_text(content, encoding="utf-8")
    return folder


def front(name: str, *extra: str, desc: str = GOOD_DESC) -> list:
    return ["name: " + name, "description: " + json.dumps(desc, ensure_ascii=False), *extra]


def codes(findings, level=None):
    return [f["code"] for f in findings if level is None or f["level"] == level]


def of(findings, code):
    return [f for f in findings if f["code"] == code]


def toc_file(entries, headings, total_lines, heading="## Contents"):
    """A reference/body with a Contents block, `## ` sections for `headings`, padded to `total_lines`."""
    lines = ["# Title", "", heading, 'Tìm mục: `grep -n "^## " <file>` rồi đọc từ dòng đó.']
    lines += ["- %s — khi nào đọc" % e for e in entries] + [""]
    for h in headings:
        lines += ["## " + h, "Body text."]
    while len(lines) < total_lines:
        lines.append("filler line")
    return "\n".join(lines[:total_lines])


class StudioCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), *map(str, args)], cwd=ROOT, text=True,
                              encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def validate(self, folder, target=None):
        """target=None calls the pre-TK2 signature (portable default)."""
        return studio_validate.validate_skill(folder) if target is None else studio_validate.validate_skill(folder, target=target)


class ReservedNameTest(StudioCase):
    def test_fm5_name_contains_claude(self):
        folder = make_skill(self.tmp, "claude-helper", front("claude-helper"), "# Claude Helper\n\nDoes work.")
        found = of(self.validate(folder), "FM5")
        self.assertEqual([f["level"] for f in found], ["ERROR"])
        self.assertEqual(self.run_cli("validate", folder).returncode, 1)

    def test_fm5_name_contains_anthropic(self):
        folder = make_skill(self.tmp, "anthropic-tools", front("anthropic-tools"), "# Tools\n\nDoes work.")
        self.assertIn("FM5", codes(self.validate(folder), "ERROR"))

    def test_fm5_absent_for_valid_name(self):
        folder = make_skill(self.tmp, "data-quality-audit", front("data-quality-audit"), "# Audit\n\nDoes work.")
        self.assertNotIn("FM5", codes(self.validate(folder)))

    def test_target_claude_code_reserved_synced(self):
        folder = make_skill(self.tmp, "synced", front("synced"), "# Synced\n\nDoes work.")
        self.assertIn("FM5", codes(self.validate(folder, "claude-code"), "ERROR"))
        self.assertNotIn("FM5", codes(self.validate(folder)))


class TargetTest(StudioCase):
    def test_target_portable_rejects_when_to_use(self):
        folder = make_skill(self.tmp, "wtu-skill", front("wtu-skill", 'when_to_use: "Also when asked for a review."'), "# Skill\n\nDoes work.")
        found = of(self.validate(folder), "FM4")
        self.assertEqual([f["level"] for f in found], ["ERROR"])
        self.assertIn("allowed keys", found[0]["message"])
        self.assertNotIn("when_to_use", found[0]["message"].split("allowed keys:")[1])
        self.assertEqual(self.run_cli("validate", folder).returncode, 1)

    def test_target_claude_code_accepts_when_to_use(self):
        folder = make_skill(self.tmp, "wtu-skill", front("wtu-skill", 'when_to_use: "Also when asked for a review."'), "# Skill\n\nDoes work.")
        findings = self.validate(folder, "claude-code")
        self.assertNotIn("FM4", codes(findings))
        self.assertEqual([f["level"] for f in of(findings, "FM6")], ["WARN"])
        self.assertEqual(of(findings, "FM6")[0]["line"], 4)
        run = self.run_cli("validate", folder, "--target", "claude-code")
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertIn("FM6", run.stdout)

    def test_target_claude_code_rejects_unknown_key(self):
        folder = make_skill(self.tmp, "trig-skill", front("trig-skill", 'triggers: "x"'), "# Skill\n\nDoes work.")
        found = of(self.validate(folder, "claude-code"), "FM4")
        self.assertEqual([f["level"] for f in found], ["ERROR"])
        self.assertIn("when_to_use", found[0]["message"])  # allowed list is per target

    def test_target_claude_code_hooks_block_no_fm1(self):
        lines = front("hooks-skill", "hooks:", "  PreToolUse:", "    - matcher: Bash", "      hooks: [x]", "metadata:", '  version: "1.0"')
        folder = make_skill(self.tmp, "hooks-skill", lines, "# Skill\n\nDoes work.")
        findings = self.validate(folder, "claude-code")
        self.assertNotIn("FM1", codes(findings))
        self.assertEqual([f["code"] for f in findings if f["level"] == "ERROR"], [])
        meta, parse_findings, _ = studio_fs.parse_frontmatter(folder.joinpath("SKILL.md").read_text(encoding="utf-8"), folder / "SKILL.md",
                                                           studio_const.CLAUDE_CODE_KEYS)
        self.assertEqual(parse_findings, [])
        self.assertEqual(meta["metadata"]["version"], "1.0")
        self.assertIn("PreToolUse:", meta["hooks"])
        # without the opaque set the nested block is still an FM1 error (portable default unchanged)
        self.assertIn("FM1", codes(self.validate(folder, "portable"), "ERROR"))

    def test_target_invalid_value_exit2(self):
        folder = make_skill(self.tmp, "any-skill", front("any-skill"), "# Skill\n\nDoes work.")
        run = self.run_cli("validate", folder, "--target", "codex")
        self.assertEqual(run.returncode, 2)
        self.assertIn("invalid choice: 'codex'", run.stderr)
        self.assertEqual(run.stdout, "")

    def test_audit_accepts_target_and_mentions_sk14(self):
        folder = make_skill(self.tmp, "wtu-skill", front("wtu-skill", 'when_to_use: "Also when asked."'), "# Skill\n\nDoes work.")
        run = self.run_cli("audit", folder, "--target", "claude-code")
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertIn("12/14", run.stdout)
        self.assertIn("CT10", run.stdout)


class ExistingChecksMutationTest(StudioCase):
    def test_ds1_xml_in_description(self):
        folder = make_skill(self.tmp, "xml-skill", front("xml-skill", desc="Parses <b>CSV</b>. Use when reading CSV files."), "# Skill\n\nDoes work.")
        self.assertEqual([f["level"] for f in of(self.validate(folder), "DS1")], ["ERROR"])

    def _compat(self, size):
        folder = make_skill(self.tmp, "compat-skill-%d" % size, front("compat-skill-%d" % size, 'compatibility: "%s"' % ("x" * size)), "# Skill\n\nDoes work.")
        return [f for f in of(self.validate(folder), "FM4") if "compatibility" in f["message"]]

    def test_fm4_compatibility_501(self):
        self.assertEqual([f["level"] for f in self._compat(501)], ["ERROR"])

    def test_fm4_compatibility_500_ok(self):
        self.assertEqual(self._compat(500), [])


class ForcingWordsTest(StudioCase):
    def ct10(self, body, name="force-skill"):
        folder = make_skill(self.tmp, name, front(name), body)
        text = (folder / "SKILL.md").read_text(encoding="utf-8").splitlines()
        return of(self.validate(folder), "CT10"), text

    def test_ct10_flags_unreasoned_must(self):
        found, text = self.ct10("# Skill\n\nIntro line.\nYou MUST run the script.\nNEVER skip it\nok")
        self.assertEqual([f["level"] for f in found], ["WARN", "WARN"])
        self.assertEqual([f["line"] for f in found], [text.index("You MUST run the script.") + 1, text.index("NEVER skip it") + 1])
        self.assertTrue(all(f["path"].endswith("SKILL.md") for f in found))

    def test_ct10_reason_english(self):
        body = "# Skill\n\nYou MUST run the script because it only reads.\nALWAYS dry-run first, otherwise data is lost.\nNEVER push, Since the repo is shared."
        self.assertEqual(self.ct10(body)[0], [])

    def test_ct10_reason_vietnamese(self):
        body = "# Skill\n\nMUST chạy script vì nó chỉ đọc.\nALWAYS dry-run để tránh mất dữ liệu.\nNEVER push nếu không có lệnh."
        self.assertEqual(self.ct10(body)[0], [])
        nfd = unicodedata.normalize("NFD", "MUST chạy script vì nó chỉ đọc.")
        self.assertEqual(self.ct10("# Skill\n\n" + nfd, "nfd-skill")[0], [])

    def test_ct10_skips_code_fence(self):
        body = "# Skill\n\n```\nYou MUST run this\n```\n~~~text\nNEVER do this\n~~~\nfine."
        self.assertEqual(self.ct10(body)[0], [])

    def test_ct10_after_fence_flagged_again(self):
        found, text = self.ct10("# Skill\n\n```\nYou MUST run this\n```\nNEVER skip it\n")
        self.assertEqual([f["line"] for f in found], [text.index("NEVER skip it") + 1])

    def test_ct10_skips_strict_block(self):
        body = "# Skill\n\n<!-- studio:strict -->\nYou MUST run this exact step.\nNEVER vary it.\n<!-- /studio:strict -->\nALWAYS check."
        found, text = self.ct10(body)
        self.assertEqual([f["line"] for f in found], [text.index("ALWAYS check.") + 1])

    def test_ct10_skips_inline_code(self):
        self.assertEqual(self.ct10("# Skill\n\nPass the `MUST` flag.\nUse `NEVER` and `ALWAYS` options.")[0], [])
        found, text = self.ct10("# Skill\n\nUse `x` and then MUST run.")
        self.assertEqual([f["line"] for f in found], [text.index("Use `x` and then MUST run.") + 1])

    def test_ct10_skips_link_text_and_url(self):
        body = "# Skill\n\nSee [ALWAYS](https://example.com/NEVER) here.\nVisit https://example.com/MUST/path now."
        self.assertEqual(self.ct10(body)[0], [])
        found, text = self.ct10("# Skill\n\nSee [docs](x.md) and MUST run.")
        self.assertEqual([f["line"] for f in found], [text.index("See [docs](x.md) and MUST run.") + 1])

    def test_ct10_skips_table_rows(self):
        body = "# Skill\n\n| Word | Meaning |\n|---|---|\n| MUST | required |\n  | NEVER | forbidden |"
        self.assertEqual(self.ct10(body)[0], [])
        found, text = self.ct10("# Skill\n\nChoose a | MUST here")
        self.assertEqual([f["line"] for f in found], [text.index("Choose a | MUST here") + 1])

    def test_ct10_skips_html_comment(self):
        self.assertEqual(self.ct10("# Skill\n\n<!-- MUST review later -->\nfine.")[0], [])
        found, text = self.ct10("# Skill\n\n<!-- note --> MUST run it")
        self.assertEqual([f["line"] for f in found], [text.index("<!-- note --> MUST run it") + 1])

    def test_ct10_skips_indented_code_block(self):
        body = "# Skill\n\nExample:\n\n    You MUST run this\n    NEVER vary\n\nBack to text."
        self.assertEqual(self.ct10(body)[0], [])
        tabbed = "# Skill\n\nExample:\n\n\tNEVER vary\n\nBack."
        self.assertEqual(self.ct10(tabbed, "tab-skill")[0], [])

    def test_ct10_indented_line_is_not_code_without_blank_or_inside_list(self):
        found, text = self.ct10("# Skill\n\nText line\n    MUST continue")
        self.assertEqual([f["line"] for f in found], [text.index("    MUST continue") + 1])
        found, text = self.ct10("# Skill\n\n- item\n\n    MUST continue it", "list-skill")
        self.assertEqual([f["line"] for f in found], [text.index("    MUST continue it") + 1])

    def test_ct10_fence_closes_only_on_matching_fence(self):
        # a ```python inside an open fence does not close it; the bare ``` does
        body = "# Skill\n\n```python\nYou MUST x\n```python\nNEVER y\n```\nALWAYS z"
        found, text = self.ct10(body)
        self.assertEqual([f["line"] for f in found], [text.index("ALWAYS z") + 1])
        # a longer opening fence is not closed by a shorter one
        body = "# Skill\n\n````\nMUST a\n```\nMUST b\n````\nNEVER c"
        found, text = self.ct10(body, "long-fence")
        self.assertEqual([f["line"] for f in found], [text.index("NEVER c") + 1])
        # a ~~~ fence is not closed by ```
        body = "# Skill\n\n~~~\nMUST a\n```\nMUST b\n~~~\nNEVER c"
        found, text = self.ct10(body, "tilde-fence")
        self.assertEqual([f["line"] for f in found], [text.index("NEVER c") + 1])

    def test_ct10_unclosed_strict_block_warns(self):
        found, text = self.ct10("# Skill\n\n<!-- studio:strict -->\nYou MUST run this exact step.\nmore text")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertIn("strict block not closed", found[0]["message"])
        self.assertEqual(found[0]["line"], text.index("<!-- studio:strict -->") + 1)
        closed, _ = self.ct10("# Skill\n\n<!-- studio:strict -->\nYou MUST run this.\n<!-- /studio:strict -->\nok", "closed-strict")
        self.assertEqual(closed, [])

    def test_ct10_heading_is_prose_and_flagged(self):
        # Verdict: a heading is prose, so '## MUST read' is flagged like any other line.
        found, text = self.ct10("# Skill\n\n## MUST read first")
        self.assertEqual([f["line"] for f in found], [text.index("## MUST read first") + 1])

    def test_ct10_reason_word_hidden_in_code_link_url_or_comment_does_not_count(self):
        # the reason must sit in the same prose the forcing word is read from (code span, link, URL and HTML comment are not prose)
        for number, line in enumerate(("You MUST run `because`", "MUST (see [because](x))", "NEVER skip https://example.com/because/x",
                                       "ALWAYS check <!-- because --> it", "MUST run `to avoid` it", "NEVER push [vì](y.md)")):
            found, text = self.ct10("# Skill\n\n" + line, "hid-%d" % number)
            self.assertEqual([f["line"] for f in found], [text.index(line) + 1], line)
        for number, line in enumerate(("You MUST run `x` because it only reads.", "NEVER push [docs](x.md) vì repo dùng chung.")):
            self.assertEqual(self.ct10("# Skill\n\n" + line, "ok-%d" % number)[0], [], line)

    def test_ct10_ignores_lowercase_and_substrings(self):
        self.assertEqual(self.ct10("# Skill\n\nYou must run it. MUSTARD and ALWAYSON are words.")[0], [])


class DescriptionBudgetTest(StudioCase):
    def test_ds4_trigger_after_500(self):
        desc = "Handles a long list of related jobs for the team. " * 10
        desc = desc[:510] + "Use when the team asks."
        folder = make_skill(self.tmp, "late-skill", front("late-skill", desc=desc), "# Skill\n\nDoes work.")
        self.assertEqual([f["level"] for f in of(self.validate(folder), "DS4")], ["WARN"])
        early = make_skill(self.tmp, "early-skill", front("early-skill", desc="Use when the team asks. " + desc[:480]), "# Skill\n\nDoes work.")
        self.assertNotIn("DS4", codes(self.validate(early)))

    def test_ds5_listing_overflow_claude_code(self):
        desc = ("Use when long. " + "word " * 300)[:1000]
        extra = 'when_to_use: "%s"' % ("more " * 120)
        folder = make_skill(self.tmp, "list-skill", front("list-skill", extra, desc=desc), "# Skill\n\nDoes work.")
        self.assertEqual([f["level"] for f in of(self.validate(folder, "claude-code"), "DS5")], ["WARN"])
        self.assertNotIn("DS5", codes(self.validate(folder, "portable")))
        small = make_skill(self.tmp, "small-skill", front("small-skill", 'when_to_use: "short"'), "# Skill\n\nDoes work.")
        self.assertNotIn("DS5", codes(self.validate(small, "claude-code")))


class BudgetTest(StudioCase):
    def test_st2_body_over_5000_tokens(self):
        body = "# Skill\n\n" + "\n".join(["a" * 99] * 200)[:20004 - 9]
        self.assertGreater(len(body), 20000)
        folder = make_skill(self.tmp, "big-skill", front("big-skill"), body)
        found = self.validate(folder)
        self.assertEqual([f["level"] for f in of(found, "ST2")], ["WARN"])
        self.assertNotIn("ST1", codes(found))
        small = make_skill(self.tmp, "ok-skill", front("ok-skill"), "# Skill\n\n" + "\n".join(["a" * 99] * 190)[:19000])
        self.assertNotIn("ST2", codes(self.validate(small)))

    def test_st2_vietnamese_body_counts_more(self):
        line = "Hướng dẫn chạy tập lệnh và kiểm tra kết quả đầu ra của công việc. " * 2
        body = "# Skill\n\n" + "\n".join([line] * 140)
        self.assertLess(len(body) / 4, 5000)
        folder = make_skill(self.tmp, "vi-skill", front("vi-skill"), body)
        self.assertIn("ST2", codes(self.validate(folder)))

    def test_fm8_frontmatter_over_1024_outside_description_warn(self):
        lines = front("fat-skill", "metadata:", '  note: "%s"' % ("n" * 1100))
        folder = make_skill(self.tmp, "fat-skill", lines, "# Skill\n\nDoes work.")
        self.assertEqual([f["level"] for f in of(self.validate(folder), "FM8")], ["WARN"])

    def test_fm8_long_description_only_ok(self):
        desc = "Use when " + "x" * 1000
        folder = make_skill(self.tmp, "wide-skill", front("wide-skill", desc=desc), "# Skill\n\nDoes work.")
        self.assertNotIn("FM8", codes(self.validate(folder)))
        folded = ["name: fold-skill", "description: >", "  Use when " + "a" * 440, "  " + "b" * 440]
        folder = make_skill(self.tmp, "fold-skill", folded + ["metadata:", '  version: "1"'], "# Skill\n\nDoes work.")
        self.assertNotIn("FM8", codes(self.validate(folder)))


class ContentsTest(StudioCase):
    def ref_findings(self, content, name="ref-skill"):
        folder = make_skill(self.tmp, name, front(name), "# Skill\n\nRead [the ref](references/REF.md) when needed.", {"REF.md": content})
        return [f for f in self.validate(folder) if f["path"].endswith("REF.md")]

    def test_st5_reference_101_lines_no_contents_error(self):
        found = of(self.ref_findings("\n".join(["line"] * 101)), "ST5")
        self.assertEqual([f["level"] for f in found], ["ERROR"])
        self.assertEqual(self.run_cli("validate", self.tmp / "ref-skill").returncode, 1)

    def test_st5_contents_after_line_25_still_missing(self):
        content = "\n".join(["line"] * 30 + ["## Contents", "- A — x", "", "## A"] + ["line"] * 70)
        self.assertEqual([f["level"] for f in of(self.ref_findings(content), "ST5")], ["ERROR"])

    def test_st5_reference_100_lines_ok(self):
        self.assertEqual(of(self.ref_findings("\n".join(["line"] * 100)), "ST5"), [])

    def test_st5_accepts_muc_luc_heading(self):
        content = toc_file(["Cách dùng"], ["Cách dùng"], 101, heading="## Mục lục")
        self.assertEqual(of(self.ref_findings(content), "ST5"), [])
        nfd = unicodedata.normalize("NFD", content)
        self.assertEqual(of(self.ref_findings(nfd, "nfd-ref"), "ST5"), [])

    def test_st5_contents_entry_mismatch_warn(self):
        content = toc_file(["Usage", "Setup"], ["Setup"], 101)
        found = of(self.ref_findings(content), "ST5")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertIn("'Usage'", found[0]["message"])

    def test_st5_contents_over_12_warn(self):
        names = ["Section %d" % i for i in range(13)]
        found = of(self.ref_findings(toc_file(names, names, 101)), "ST5")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertIn("13 entries", found[0]["message"])
        ok = ["Section %d" % i for i in range(12)]
        self.assertEqual(of(self.ref_findings(toc_file(ok, ok, 101), "twelve-ref"), "ST5"), [])

    def test_st5_ignores_headings_inside_code_fence(self):
        # 'Fake' exists only as a heading inside a code fence, so the Contents entry must not match it
        content = toc_file(["Real", "Fake"], ["Real"], 101) + "\n```\n## Fake\n```"
        found = of(self.ref_findings(content), "ST5")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertIn("'Fake'", found[0]["message"])

    def test_st5_accepts_table_of_contents_and_lowercase_heading(self):
        for i, heading in enumerate(("## Table of Contents", "## contents", "## TABLE OF CONTENTS", "## MỤC LỤC")):
            content = toc_file(["Usage"], ["Usage"], 101, heading=heading)
            self.assertEqual(of(self.ref_findings(content, "toc-ref-%d" % i), "ST5"), [], heading)

    def test_st5_contents_heading_must_be_level_two(self):
        for i, heading in enumerate(("### Contents", "# Contents")):
            content = toc_file(["Usage"], ["Usage"], 101, heading=heading)
            self.assertEqual([f["level"] for f in of(self.ref_findings(content, "lvl-ref-%d" % i), "ST5")], ["ERROR"], heading)

    def test_st5_link_style_entries_match_headings(self):
        for i, entry in enumerate(("[Real](#real)", "[Real](REF.md#real)")):
            content = toc_file([entry], ["Real"], 101)
            self.assertEqual(of(self.ref_findings(content, "link-ref-%d" % i), "ST5"), [], entry)

    def test_st5_link_entry_to_missing_heading_still_warns(self):
        content = toc_file(["[Ghost](#ghost)", "[Real](#real)"], ["Real"], 101)
        found = of(self.ref_findings(content), "ST5")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertIn("'Ghost'", found[0]["message"])

    def body_findings(self, body, name="body-skill"):
        return self.validate(make_skill(self.tmp, name, front(name), body))

    def test_st7_body_101_no_contents_warn(self):
        found = of(self.body_findings("\n".join(["# Skill"] + ["line"] * 100)), "ST7")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertEqual(found[0]["line"], 5)

    def test_st7_link_style_entries(self):
        ok = of(self.body_findings(toc_file(["[Real](#real)"], ["Real"], 40), "linkok-skill"), "ST7")
        self.assertEqual(ok, [])
        bad = of(self.body_findings(toc_file(["[Ghost](#ghost)"], ["Real"], 40), "linkbad-skill"), "ST7")
        self.assertEqual([f["level"] for f in bad], ["WARN"])
        self.assertIn("'Ghost'", bad[0]["message"])

    def test_st7_body_100_ok(self):
        self.assertEqual(of(self.body_findings("\n".join(["# Skill"] + ["line"] * 99)), "ST7"), [])

    def test_st7_body_contents_mismatch_and_overflow(self):
        found = of(self.body_findings(toc_file(["Nowhere"], ["Real"], 40)), "ST7")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        names = ["S%d" % i for i in range(13)]
        found = of(self.body_findings(toc_file(names, names, 60), "many-skill"), "ST7")
        self.assertEqual(len(found), 1)
        self.assertEqual(self.body_findings(toc_file(["Real"], ["Real"], 120), "good-skill") and of(self.body_findings(toc_file(["Real"], ["Real"], 120), "good2-skill"), "ST7"), [])


VI_BODY_LINE = "Việc này giúp người dùng kiểm tra dữ liệu trước khi báo cáo."


def vi_body(*extra: str) -> str:
    """A Vietnamese body (title, blank, one clean sentence = body lines 1-3) followed by `extra` lines."""
    return "\n".join(["# Kiểm dữ liệu", "", VI_BODY_LINE, *extra])


class VietnameseLintTest(StudioCase):
    """SPR-33 TK4: VI1-VI5 (FR16, SPEC 9.10). All WARN, Vietnamese bodies only.
    With a two-key frontmatter the body starts at file line 5, so body line r is file line 4 + r."""

    def vi(self, body, name="vi-skill", desc=GOOD_DESC, extra=()):
        folder = make_skill(self.tmp, name, front(name, *extra, desc=desc), body)
        return self.validate(folder)

    def test_vi_detect_lang_threshold(self):
        def ratio_body(accented, total=1000):
            return "a" * (total - accented) + "ế" * accented
        self.assertEqual(studio_lint.detect_lang(ratio_body(29)), "en")  # 2.9 %
        self.assertEqual(studio_lint.detect_lang(ratio_body(30)), "vi")  # 3.0 %
        self.assertEqual(studio_lint.detect_lang(""), "en")
        nfd = unicodedata.normalize("NFD", ratio_body(30))
        self.assertNotEqual(nfd, ratio_body(30))
        self.assertEqual(studio_lint.detect_lang(nfd), "vi", "an NFD body must still be recognised as Vietnamese")
        padded = "```\n" + "ế" * 500 + "\n```\n| " + "ế" * 500 + " |\n`" + "ế" * 500 + "` " + "a" * 100
        self.assertEqual(studio_lint.detect_lang(padded), "en", "code, table rows and backtick spans are not counted")

    def test_vi_lint_nfd_flags_vi1(self):
        nfd_line = unicodedata.normalize("NFD", "Việc kiểm dữ liệu cần làm trước khi gửi.")
        found = of(self.vi(vi_body("", nfd_line)), "VI1")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertEqual(found[0]["line"], 9)  # body line 5
        later = unicodedata.normalize("NFD", "Dòng thứ hai cũng lệch.")
        self.assertEqual([f["line"] for f in of(self.vi(vi_body("", nfd_line, later), "vi-two"), "VI1")], [9], "only the first deviating line")
        nfc = unicodedata.normalize("NFC", nfd_line)
        self.assertEqual(of(self.vi(vi_body("", nfc), "vi-nfc"), "VI1"), [])

    def test_vi_lint_non_iso_date_vi2(self):
        found = of(self.vi(vi_body("", "Sprint đóng vào ngày 22/10/2026 theo kế hoạch.")), "VI2")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertEqual(found[0]["line"], 9)
        iso = self.vi(vi_body("", "Sprint đóng vào ngày 2026-10-22 theo kế hoạch."), "vi-iso")
        self.assertEqual(of(iso, "VI2"), [])
        version = self.vi(vi_body("", "Bản v1.0 và mục 3.5 chưa đổi, xem standards/README.md."), "vi-ver")
        self.assertEqual(of(version, "VI2"), [])

    def test_vi_lint_sentence_41_words_vi3(self):
        sentence = " ".join(["việc"] * 41) + "."
        found = of(self.vi(vi_body("", sentence)), "VI3")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertEqual(found[0]["line"], 9)
        self.assertIn("41", found[0]["message"])

    def test_vi_lint_sentence_40_words_ok(self):
        sentence = " ".join(["việc"] * 40) + "."
        self.assertEqual(of(self.vi(vi_body("", sentence)), "VI3"), [])
        two = " ".join(["việc"] * 30) + ". " + " ".join(["việc"] * 30) + "."
        self.assertEqual(of(self.vi(vi_body("", two), "vi-two"), "VI3"), [], "sentences are counted separately")
        long = " ".join(["việc"] * 41) + "."  # control: one word more is reported, at its own line only
        self.assertEqual([f["line"] for f in of(self.vi(vi_body("", sentence, long), "vi-ctl"), "VI3")], [10])

    def test_vi_lint_frontmatter_diacritics_vi4(self):
        found = of(self.vi(vi_body(), extra=("metadata:", '  author: "Đức"')), "VI4")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertEqual(found[0]["line"], 5)  # the 'author' line
        self.assertIn("metadata.author", found[0]["message"])
        # a plain-ASCII value is clean; an English body never reaches VI4
        self.assertEqual(of(self.vi(vi_body(), "vi-clean", extra=("metadata:", '  author: "Duc"')), "VI4"), [])
        en = self.vi("# Audit\n\nChecks the data.", "en-front", extra=("metadata:", '  author: "Đức"'))
        self.assertEqual(of(en, "VI4"), [])

    def test_vi_lint_description_vietnamese_primary_vi4(self):
        found = of(self.vi(vi_body(), desc="Kiểm tra"), "VI4")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertEqual(found[0]["line"], 3)
        self.assertIn("Use when", found[0]["message"])

    def test_vi_lint_description_en_with_vi_phrase_ok(self):
        desc = "Checks CSV. Use when validating a file; kiểm dữ liệu CSV"
        self.assertEqual(of(self.vi(vi_body(), desc=desc), "VI4"), [])
        self.assertEqual(of(self.vi(vi_body(), "vi-this", desc="Kiểm CSV. Use this skill when kiểm dữ liệu."), "VI4"), [])
        self.assertEqual(len(of(self.vi(vi_body(), "vi-ctl", desc="Checks CSV; kiểm dữ liệu CSV"), "VI4")), 1, "control: no trigger phrase")

    def test_vi_lint_mixed_section_vi5(self):
        english = ("This section explains in plain English how the report is assembled from the raw data "
                   "and which checks run before the final numbers are published to the team.")
        body = vi_body("", "## Mục tiêu", "Việc kiểm dữ liệu giúp báo cáo đúng hơn.", "", "## Quy trình", english)
        found = of(self.vi(body), "VI5")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertEqual(found[0]["line"], 12)  # the '## Quy trình' heading = body line 8
        self.assertEqual(of(self.vi(vi_body("", "## Quy trình", english[:60]), "vi-short"), "VI5"), [], "<80 letters: no VI5")
        vietnamese = vi_body("", "## Quy trình", "Việc này mô tả cách ráp báo cáo từ dữ liệu thô và những bước kiểm trước khi công bố số liệu cuối cùng cho cả nhóm.")
        self.assertEqual(of(self.vi(vietnamese, "vi-whole"), "VI5"), [])

    ENGLISH_SECTION = ("This section explains in plain English how the report is assembled from the raw data "
                       "and which checks run before the final numbers are published to the team.")

    def test_vi5_skips_english_body(self):
        """SPR-03 TK11 / FR14.1 (RQ-012): a body that is mostly English (diacritics under VI5_ACCENT_MIN of ALL its letters,
        code included) gets no VI5 per section, even when its prose alone passes the 3 % Vietnamese gate."""
        code = "\n".join(["```text"] + ["print the whole report and check every single column of the table"] * 60 + ["```"])
        body = vi_body("", "## Steps", self.ENGLISH_SECTION, "", code)
        self.assertEqual(studio_lint.detect_lang(body), "vi", "precondition: the prose still counts as Vietnamese")
        letters, accents = studio_lint._vi_counts(body)
        self.assertLess(accents / letters, studio_const.VI5_ACCENT_MIN, "precondition: the whole body is under the VI5 share")
        self.assertEqual(of(self.vi(body, "en-label"), "VI5"), [])

    def test_vi5_still_flags_english_section_in_vietnamese_body(self):
        """FR14.1 second half: a Vietnamese body keeps VI5 for a long English section (control for the test above)."""
        body = vi_body("", "## Mục tiêu", "Việc kiểm dữ liệu giúp báo cáo đúng hơn.", "", "## Quy trình", self.ENGLISH_SECTION)
        letters, accents = studio_lint._vi_counts(body)
        self.assertGreaterEqual(accents / letters, studio_const.VI5_ACCENT_MIN)
        self.assertEqual([f["code"] for f in of(self.vi(body, "vi-mixed"), "VI5")], ["VI5"])

    def test_vi_lint_english_body_no_vi_codes(self):
        body = ("# Audit\n\nThe date 22/10/2026 is in the body. " + " ".join(["word"] * 60) + ".\n\n## Steps\n"
                + "Run the check and read the result carefully before you report anything to the team lead.")
        findings = self.vi(body, "en-skill", desc="Kiểm tra")  # even a Vietnamese description: the body decides
        self.assertEqual([c for c in codes(findings) if c.startswith("VI")], [])
        control = self.vi(vi_body("", "Ngày 22/10/2026 theo kế hoạch."), "vi-ctl")  # the same date in a Vietnamese body is reported
        self.assertEqual(len(of(control, "VI2")), 1)
        # 'ë' and 'ï' are not Vietnamese letters, so an NFD English body stays English
        nfd_body = unicodedata.normalize("NFD", "# Zoë\n\nA short English note about naïve users.")
        folder = make_skill(self.tmp, "en-nfd", front("en-nfd"), nfd_body)
        self.assertEqual([c for c in codes(self.validate(folder)) if c.startswith("VI")], [])

    def test_vi_lint_skips_code_table_and_vi_ok(self):
        long_line = " ".join(["việc"] * 50) + "."
        nfd = unicodedata.normalize("NFD", "Việc cũ giữ nguyên.")
        body = vi_body(
            "", "```", long_line, "22/10/2026 " + nfd, "```",
            "| ngày | giá trị |", "| 22/10/2026 | " + long_line + " |",
            "Mã `22/10/2026` và `" + long_line + "` nằm trong backtick.",
            long_line + " <!-- studio:vi-ok -->",
            "Ngày 22/10/2026 đã miễn. <!-- studio:vi-ok -->",
            nfd + " <!-- studio:vi-ok -->",
        )
        findings = self.vi(body)
        self.assertEqual([c for c in codes(findings) if c.startswith("VI")], [])
        # control: the same text without the exemption is reported
        bare = self.vi(vi_body("", long_line, "Ngày 22/10/2026 đã miễn.", nfd), "vi-bare")
        self.assertEqual({"VI1", "VI2", "VI3"}, {c for c in codes(bare) if c.startswith("VI")})

    # Extra checks on the helpers (names avoid the 'test_vi_' selector so the TK4 gate stays at 12 tests).
    def test_lint_vi_wrapped_sentence_and_list_items(self):
        wrapped = vi_body("", " ".join(["việc"] * 20), " ".join(["việc"] * 21) + ".")
        self.assertEqual([f["line"] for f in of(self.vi(wrapped), "VI3")], [9], "41 words over two lines: one hit at the first line")
        item = "- " + " ".join(["việc"] * 30) + "."
        items = vi_body("", item, item, "## " + " ".join(["việc"] * 30), " ".join(["việc"] * 30) + ".")
        self.assertEqual(of(self.vi(items, "vi-items"), "VI3"), [], "list items and headings end a sentence")

    def test_lint_vi_abbreviations_decimals_and_paths_stay_whole(self):
        text = "Bản v1.0 và e.g. mục 3.5 " + " ".join(["việc"] * 35) + " xong."
        self.assertEqual(studio_lint._vi_sentences(studio_lint.prose_lines(text)), [(1, 42)], "'e.g.', 'v1.0' and '3.5' do not split")
        paths = "Xem standards/README.md. Rồi chạy studio.py validate. Hết."
        self.assertEqual([w for _, w in studio_lint._vi_sentences(studio_lint.prose_lines(paths))], [2, 4, 1])

    def test_lint_vi_indented_code_and_link_targets_skipped(self):
        body = vi_body("", "    22/10/2026 " + " ".join(["việc"] * 45) + ".", "", "Xem [tài liệu](docs/22/10/2026) để biết thêm.")
        self.assertEqual([c for c in codes(self.vi(body)) if c.startswith("VI")], [])
        self.assertEqual(studio_lint.prose_lines("a\n\n```\nb\n```\nc\n| t |\n\n    d\n    e"), [(1, "a"), (6, "c")])

    def test_lint_vi_missing_manifest_uses_default_lines(self):
        meta = {"name": "x", "description": "Kiểm tra", "metadata": {"author": "Đức"}}
        found = studio_lint.lint_vietnamese(meta, vi_body(), 4, self.tmp / "none" / "SKILL.md")
        self.assertEqual(sorted((f["code"], f["line"]) for f in found), [("VI4", 2), ("VI4", 3)])

    def test_lint_vi_frontmatter_vi_ok_and_cli_exit_zero(self):
        body = vi_body("", " ".join(["việc"] * 41) + ".")
        folder = make_skill(self.tmp, "vi-cli", front("vi-cli", "metadata:", "  author: Đức <!-- studio:vi-ok -->"), body)
        self.assertEqual(of(self.validate(folder), "VI4"), [], "a vi-ok mark exempts that frontmatter line")
        run = self.run_cli("validate", folder)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)  # VI* are WARN only
        self.assertIn("VI3", run.stdout)


    # Round 2 (review of ffc6aa7): boundaries, sentence splitting, comments and frontmatter shapes.
    def test_lint_vi_vi5_letter_and_accent_boundaries(self):
        def section(text):
            return vi_body("", "## Quy trình", text)
        self.assertEqual(of(self.vi(section("a" * 79)), "VI5"), [], "79 letters: below the minimum")
        self.assertEqual(len(of(self.vi(section("a" * 80), "vi-80"), "VI5")), 1, "80 letters: reported")
        self.assertEqual(of(self.vi(section("a" * 99 + "ế"), "vi-100"), "VI5"), [], "1 accent in 100 letters = 1 %: not under")
        self.assertEqual(len(of(self.vi(section("a" * 100 + "ế"), "vi-101"), "VI5")), 1, "1 accent in 101 letters is under 1 %")

    def test_lint_vi_vi2_two_digit_year_and_short_day(self):
        found = of(self.vi(vi_body("", "Họp vào ngày 22/10/26 theo kế hoạch.")), "VI2")
        self.assertEqual([f["line"] for f in found], [9])
        self.assertEqual(len(of(self.vi(vi_body("", "Họp vào ngày 5/3/2026 theo kế hoạch."), "vi-short"), "VI2")), 1)
        self.assertEqual(of(self.vi(vi_body("", "Tỉ lệ 1/2/3 là nhãn nội bộ."), "vi-nodate"), "VI2"), [], "a one-digit year is not a date")

    def test_lint_vi_vi3_semicolon_and_unpunctuated_items(self):
        halves = " ".join(["việc"] * 21) + "; " + " ".join(["việc"] * 21) + "."
        self.assertEqual(of(self.vi(vi_body("", halves)), "VI3"), [], "';' ends a sentence: 21 + 21 words")
        bare = " ".join(["việc"] * 30)
        items = vi_body("", bare, "- " + bare, "- " + bare, "## " + bare, bare, "## " + bare, bare + ".")
        self.assertEqual(of(self.vi(items, "vi-bare"), "VI3"), [], "items and headings without a final stop still end a sentence")
        self.assertEqual(len(of(self.vi(vi_body("", bare, bare + "."), "vi-ctl"), "VI3")), 1, "control: two plain lines are one 60-word sentence")

    def test_lint_vi_urls_and_comments_leave_prose_lines(self):
        self.assertEqual(studio_lint.prose_lines("Xem https://example.com/22/10/2026 xong."), [(1, "Xem   xong.")])
        self.assertEqual(studio_lint.prose_lines("A <!-- 22/10/2026 --> B"), [(1, "A   B")])
        multi = "Đầu.\n<!--\nNgày 22/10/2026 trong ghi chú\n-->\nCuối."
        self.assertEqual(studio_lint.prose_lines(multi), [(1, "Đầu."), (5, "Cuối.")])
        self.assertEqual(studio_lint.prose_lines("Trước <!-- mở\nđóng --> sau."), [(1, "Trước "), (2, " sau.")])
        self.assertEqual(studio_lint.prose_lines("Trước `<!--` giữa\nvẫn là văn xuôi."), [(1, "Trước   giữa"), (2, "vẫn là văn xuôi.")], "backticked '<!--' opens nothing")
        body = vi_body("", "<!--", "Ngày 22/10/2026 trong ghi chú nhiều dòng.", "-->", "Ngày 22/10/2026 nằm ngoài.", "Xem https://example.com/22/10/2026 thôi.")
        self.assertEqual([f["line"] for f in of(self.vi(body), "VI2")], [12], "only the date outside the comment and the URL is reported")

    def test_lint_vi_frontmatter_list_dict_and_comments(self):
        meta = {"name": "x", "description": "Does a job. Use when testing.", "tags": ["ok", "Đức"], "metadata": {"deep": {"who": "Đức"}, "plain": "ok"}}
        found = of(studio_lint.lint_vietnamese(meta, vi_body(), 4, self.tmp / "none" / "SKILL.md"), "VI4")
        self.assertEqual(sorted(f["message"].split("'")[1] for f in found), ["metadata.deep.who", "tags[1]"])
        clean = {"name": "x", "description": "Does a job. Use when testing.", "tags": ["ok"], "metadata": {"deep": {"who": "ok"}}}
        self.assertEqual(studio_lint.lint_vietnamese(clean, vi_body(), 4, self.tmp / "none" / "SKILL.md"), [])
        listed = of(self.vi(vi_body(), "vi-list", extra=('tags: ["Đức"]',)), "VI4")
        self.assertEqual([f["line"] for f in listed], [4], "a flow-list value with diacritics is reported")
        # a comment on a frontmatter line is not part of the value
        noted = self.vi(vi_body(), "vi-note", extra=("metadata:", "  author: Duc <!-- ghi chú của Đức -->"))
        self.assertEqual(of(noted, "VI4"), [], "diacritics inside a comment are not the value")
        value = self.vi(vi_body(), "vi-value", extra=("metadata:", "  author: Đức <!-- note -->"))
        self.assertEqual(len(of(value, "VI4")), 1, "diacritics in the value are still reported")
        desc = self.vi(vi_body(), "vi-desc", desc="Does a job. Use when testing. <!-- studio:vi-ok -->")
        self.assertEqual(of(desc, "VI4"), [])
        trick = self.vi(vi_body(), "vi-trick", desc="Kiểm tra <!-- Use when testing -->")
        self.assertEqual(len(of(trick, "VI4")), 1, "a trigger phrase hidden in a comment does not count")


class RepoStaysCleanTest(StudioCase):
    def test_validate_all_has_no_errors_or_warnings(self):
        for folder in studio_fs.skill_dirs(ROOT):
            findings = studio_validate.validate_skill(folder, eval_root=ROOT / "evals", require_evals=True)
            self.assertEqual([(f["code"], f["level"]) for f in findings], [], str(folder))


if __name__ == "__main__":
    unittest.main()
