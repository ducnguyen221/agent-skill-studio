"""Shape checks for the documents under standards/ (SPR-33)."""
import re
import unittest
from pathlib import Path

STANDARDS_DIR = Path(__file__).resolve().parent.parent / "standards"
ROOT_DIR = STANDARDS_DIR.parent

SOURCE_TAGS: tuple[str, ...] = (
    "spec", "bp", "cc", "ab", "ae", "pb", "fable-5", "sonnet-5.5",
)

# Cụm then chốt của rule hành vi (SPEC 9.2 "Không được cắt"): thiếu cụm nào là rule đã rơi.
BEHAVIOR_PHRASES: dict[str, tuple[str, ...]] = {
    "SK-03": ("tự do", "rủi ro"),
    "SK-04": ("A/B", "trực giác"),
    "SK-06": ("bước",),
    "SK-07": ("validate",),
    "SK-08": ("Strict", "Flexible"),
    "SK-09": ("đường dẫn",),
    "SK-10": ("hook",),
    "SK-11": ("baseline",),
    "SK-12": ("5 000",),
    "SK-13": ("reasoning_extraction",),
}

NEW_SOURCE_URLS: tuple[str, ...] = (
    "https://agentskills.io/skill-creation/best-practices",
    "https://agentskills.io/skill-creation/evaluating-skills",
    "https://code.claude.com/docs/en/plugin-evals",
    "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices",
    "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5",
    "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5",
)

SK_HEAD_RE = re.compile(r"^### (SK-\d\d)\b")
SK_TITLE_RE = re.compile(r"\[[^\]]+\] · kiểm: \S")


def read_std(name: str) -> str:
    return (STANDARDS_DIR / name).read_text(encoding="utf-8")


def sk_blocks(text: str) -> dict:
    """Map 'SK-NN' -> text of its '### SK-NN' block (up to the next '#' heading)."""
    blocks: dict = {}
    current = None
    for line in text.splitlines():
        m = SK_HEAD_RE.match(line)
        if m:
            current = m.group(1)
            blocks[current] = line + "\n"
        elif re.match(r"^#{1,3} ", line):
            current = None
        elif current:
            blocks[current] += line + "\n"
    return blocks


class StandardsTest(unittest.TestCase):
    def test_memo_v0_shape(self):
        p = STANDARDS_DIR / "MEMO-SKILL-V0.md"
        self.assertTrue(p.exists(), "standards/MEMO-SKILL-V0.md is missing")
        text = read_std("MEMO-SKILL-V0.md")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), 60)
        self.assertTrue(
            any(re.fullmatch(r"Date: 2026-10-2\d", ln) for ln in lines),
            "no standalone 'Date: 2026-10-2x' line",
        )
        allowed = {f"[{t}]" for t in SOURCE_TAGS} | {"[nội bộ]"}
        rows = [ln for ln in lines if ln.startswith(("| (a", "| (b"))]
        self.assertEqual(len(rows), 18, "expected 9 (a) rows and 9 (b) rows")
        for ln in rows:
            last_cell = ln.rstrip().rstrip("|").rsplit("|", 1)[-1]
            self.assertTrue(
                any(tag in last_cell for tag in allowed),
                f"row has no source tag in its last cell: {ln[:40]}",
            )
        self.assertIn("SPR-31", text)
        self.assertIn("SPR-32", text)

    def test_authoring_standard_one_form(self):
        text = read_std("SKILL_AUTHORING_STANDARD.md")
        for n in range(16):
            code = "SK-%02d" % n
            heads = re.findall(r"^### %s\b.*$" % code, text, re.M)
            self.assertEqual(len(heads), 1, "%s must have exactly one '### ' block" % code)
            self.assertRegex(heads[0], SK_TITLE_RE, "%s title needs [mức] and 'kiểm:'" % code)
        self.assertIsNone(re.search(r"^\| ID \| Quy tắc", text, re.M), "summary rule table must be gone")
        for needle in ("Gotchas", "Server:tool", "1 536", "5 000", "25 000"):
            self.assertIn(needle, text)
        self.assertIn("hai tầng", sk_blocks(text).get("SK-02", ""), "SK-02 needs the three cutting questions")
        self.assertLessEqual(len(text), 5600)

    def test_authoring_standard_keeps_behavior_rules(self):
        blocks = sk_blocks(read_std("SKILL_AUTHORING_STANDARD.md"))
        for code, phrases in BEHAVIOR_PHRASES.items():
            self.assertIn(code, blocks, "%s block is missing" % code)
            for phrase in phrases:
                self.assertIn(phrase, blocks[code], "%s lost its key phrase %r" % (code, phrase))

    def test_authoring_standard_contents_rule_self_applied(self):
        lines = read_std("SKILL_AUTHORING_STANDARD.md").splitlines()
        if len(lines) < 100:
            return
        self.assertIn("## Contents", lines, "standard has %d lines (>=100) but no '## Contents'" % len(lines))
        start = lines.index("## Contents")
        headings = {ln[3:].strip() for ln in lines if ln.startswith("## ")}
        entries = []
        for ln in lines[start + 1:]:
            if ln.startswith("#"):
                break
            if ln.startswith("- "):
                entries.append(ln[2:].split(" — ")[0].strip())
        self.assertTrue(entries)
        for name in entries:
            self.assertIn(name, headings, "Contents entry %r matches no '## ' heading" % name)

    def test_source_traceability_new_urls(self):
        text = read_std("SOURCE_TRACEABILITY.md")
        for url in NEW_SOURCE_URLS:
            self.assertIn(url, text)
        self.assertIn("measure-skill-budget.py", text)
        for code in ("A10", "A15", "A16", "SK-14", "SK-15"):
            self.assertIn(code, text)

    def test_audit_checklist_has_sk14_sk15(self):
        text = (ROOT_DIR / "skills" / "skill-creator-studio" / "references" / "AUDIT_CHECKLIST.md").read_text(encoding="utf-8")
        self.assertIn("SK-14", text)
        self.assertIn("SK-15", text)
        self.assertIn("hai tầng", text, "AUDIT_CHECKLIST needs the three cutting questions")


if __name__ == "__main__":
    unittest.main()
