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
        return studio.validate_skill(folder) if target is None else studio.validate_skill(folder, target=target)


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
        meta, parse_findings, _ = studio.parse_frontmatter(folder.joinpath("SKILL.md").read_text(encoding="utf-8"), folder / "SKILL.md",
                                                           studio.CLAUDE_CODE_KEYS)
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
        content = toc_file(["Real"], ["Real"], 101) + "\n```\n## Fake\n```"
        self.assertEqual(of(self.ref_findings(content), "ST5"), [])

    def body_findings(self, body, name="body-skill"):
        return self.validate(make_skill(self.tmp, name, front(name), body))

    def test_st7_body_101_no_contents_warn(self):
        found = of(self.body_findings("\n".join(["# Skill"] + ["line"] * 100)), "ST7")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        self.assertEqual(found[0]["line"], 5)

    def test_st7_body_100_ok(self):
        self.assertEqual(of(self.body_findings("\n".join(["# Skill"] + ["line"] * 99)), "ST7"), [])

    def test_st7_body_contents_mismatch_and_overflow(self):
        found = of(self.body_findings(toc_file(["Nowhere"], ["Real"], 40)), "ST7")
        self.assertEqual([f["level"] for f in found], ["WARN"])
        names = ["S%d" % i for i in range(13)]
        found = of(self.body_findings(toc_file(names, names, 60), "many-skill"), "ST7")
        self.assertEqual(len(found), 1)
        self.assertEqual(self.body_findings(toc_file(["Real"], ["Real"], 120), "good-skill") and of(self.body_findings(toc_file(["Real"], ["Real"], 120), "good2-skill"), "ST7"), [])


class RepoStaysCleanTest(StudioCase):
    def test_validate_all_has_no_errors_or_warnings(self):
        for folder in studio.skill_dirs(ROOT):
            findings = studio.validate_skill(folder, eval_root=ROOT / "evals", require_evals=True)
            self.assertEqual([(f["code"], f["level"]) for f in findings], [], str(folder))


if __name__ == "__main__":
    unittest.main()
