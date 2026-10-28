"""Offline tests for the SPR-33 TK7 content kit (examples/, once content/: description pairs, eval cases, two exemplar skills).

Run: python -X utf8 -m pytest tests/test_content.py -q -p no:cacheprovider
"""
import importlib.util
import json
import re
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "skills" / "skill-creator-studio" / "scripts" / "studio.py"
_SPEC = importlib.util.spec_from_file_location("studio_content_impl", CODE)
studio = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(studio)
studio_const = sys.modules["studio_const"]  # sibling modules the engine just imported (SPR-02 TK4a)
studio_fs = sys.modules["studio_fs"]
studio_evals = sys.modules["studio_evals"]
studio_lint = sys.modules["studio_lint"]
studio_validate = sys.modules["studio_validate"]

CONTENT = ROOT / "examples"
EXEMPLAR = CONTENT / "exemplar" / "writing-commit-messages"
EXEMPLAR_VI = CONTENT / "exemplar-vi" / "writing-release-notes"

PAIR_KEYS = ("Bad", "Good", "Why", "Source")
CASE_KEYS = {"id", "kind", "prompt", "should_trigger", "expected_behaviors", "fixtures"}
CASE_KINDS = {"typical", "edge", "near-miss"}
EXPORT_EVAL_KEYS = {"id", "prompt", "expected_output", "files", "assertions"}
ALLOWED_URL_RE = re.compile(r"https://(platform\.claude\.com|code\.claude\.com|agentskills\.io)/")
ANY_URL_RE = re.compile(r"https?://[^\s)\]\"'`,;]+")
INTERNAL_TAG = unicodedata.normalize("NFC", "[nội bộ]")
# Mã mà validator phải báo cho Bad của các cặp đã chốt (Bad cô lập đúng lỗi chính của cặp):
# cặp 1 mơ hồ không có "Use when" -> DS3; cặp 2 ngôi thứ nhất -> DS2; cặp 3 cụm kích hoạt quá muộn -> DS4;
# cặp 4 (thiếu phạm vi âm) và cặp 5 (chữ ép buộc) không vấp mã DS nào.
EXPECTED_BAD_CODES = {1: ["DS3"], 2: ["DS2"], 3: ["DS4"], 4: [], 5: []}
VI_BODY = "Đọc yêu cầu của người dùng, rồi làm từng bước và kiểm lại kết quả trước khi báo xong."


def read(path: Path) -> str:
    return unicodedata.normalize("NFC", path.read_text(encoding="utf-8"))


def blocks(text: str, label: str) -> list:
    """Blocks that open with '### <label> N — <title>' and end at the next Markdown heading."""
    out, cur = [], None
    for line in text.splitlines():
        opened = re.match(r"^### %s (\d+) — (.+)$" % label, line)
        if opened:
            cur = {"n": int(opened.group(1)), "title": opened.group(2), "lines": []}
            out.append(cur)
        elif re.match(r"^#{1,3} ", line):
            cur = None
        elif cur is not None:
            cur["lines"].append(line)
    return out


def pair_field(block: dict, key: str) -> list:
    pattern = re.compile(r"^- \*\*%s:\*\* (.*\S)\s*$" % key)
    return [m.group(1) for m in (pattern.match(line) for line in block["lines"]) if m]


def source_problems(source: str) -> list:
    problems = []
    urls = ANY_URL_RE.findall(source)
    for url in urls:
        if not ALLOWED_URL_RE.match(url):
            problems.append("URL is not an official source: " + url)
    if not any(ALLOWED_URL_RE.match(u) for u in urls) and INTERNAL_TAG not in source:
        problems.append("Source has neither an official URL nor " + INTERNAL_TAG)
    return problems


def pair_problems(block: dict) -> list:
    problems = []
    for key in PAIR_KEYS:
        found = pair_field(block, key)
        if len(found) != 1:
            problems.append("Pair %s has %d '- **%s:**' lines (need exactly 1)" % (block["n"], len(found), key))
    sources = pair_field(block, "Source")
    if len(sources) == 1:
        problems += source_problems(sources[0])
    return problems


def description_of(value: str) -> str:
    value = value.strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def validate_description(desc: str, tmp: Path) -> list:
    folder = tmp / "pair-test"
    folder.mkdir(exist_ok=True)
    text = "---\nname: pair-test\ndescription: %s\n---\n\n# Pair test\n\n%s\n" % (json.dumps(desc, ensure_ascii=False), VI_BODY)
    (folder / "SKILL.md").write_text(text, encoding="utf-8")
    return studio_validate.validate_skill(folder)


def json_block(lines: list) -> dict:
    match = re.search(r"```json\n(.*?)\n```", "\n".join(lines), re.S)
    if not match:
        raise AssertionError("no ```json block")
    return json.loads(match.group(1))


def expected_export(skill_name: str, cases: list) -> dict:
    """Agentskills export that SPEC 9.6 prescribes for parsed cases.json cases (should_trigger true only, ids 1..n)."""
    evals = []
    for case in (c for c in cases if c["should_trigger"]):
        evals.append({
            "id": len(evals) + 1,
            "prompt": case["prompt"],
            "expected_output": "; ".join(case["expected_behaviors"]),
            "files": ["evals/files/" + Path(rel).name for rel in case["fixtures"]],
            "assertions": list(case["expected_behaviors"]),
        })
    return {"skill_name": skill_name, "evals": evals}


def skill_body(path: Path) -> str:
    text = read(path / "SKILL.md")
    _meta, _findings, body_start = studio_fs.parse_frontmatter(text, path / "SKILL.md")
    return "\n".join(text.splitlines()[body_start:])


class ContentKitTests(unittest.TestCase):
    def test_content_kit_counts(self):
        self.assertTrue((CONTENT / "README.md").is_file(), "examples/README.md missing")
        # description pairs
        pairs = blocks(read(CONTENT / "descriptions.md"), "Pair")
        self.assertGreaterEqual(len(pairs), 7)
        with tempfile.TemporaryDirectory() as t:
            for pair in pairs:
                self.assertEqual([], pair_problems(pair), "Pair %d" % pair["n"])
                good = description_of(pair_field(pair, "Good")[0])
                bad = description_of(pair_field(pair, "Bad")[0])
                findings = validate_description(good, Path(t))
                bad_codes = [f["code"] for f in findings if f["code"].startswith("DS") or f["code"] == "VI4"]
                self.assertEqual([], bad_codes, "Pair %d Good vấp %s" % (pair["n"], bad_codes))
                self.assertNotEqual(good, bad)
                bad_findings = [f["code"] for f in validate_description(bad, Path(t))]
                if pair["n"] in EXPECTED_BAD_CODES:
                    self.assertEqual(EXPECTED_BAD_CODES[pair["n"]], bad_findings, "Pair %d Bad must show exactly its own error" % pair["n"])
                if pair["n"] == 5:
                    self.assertRegex(bad, studio_const.FORCE_RE, "Pair 5 Bad must carry the forcing words")
                if pair["n"] == 4:
                    self.assertNotRegex(bad, r"(?i)(?:^|[^a-z])not for(?:[^a-z]|$)", "Pair 4 Bad must keep the near-miss gap (no 'not for')")
                if pair["n"] == 3:
                    self.assertGreaterEqual(len(bad), 600)
                    self.assertGreaterEqual(studio_const.TRIGGER_RE.search(bad).start(), 600, "Bad trigger must sit after 600 chars")
                    self.assertLess(studio_const.TRIGGER_RE.search(good).start(), 500)
        self.assertEqual(studio_lint.detect_lang(VI_BODY), "vi", "VI_BODY must be Vietnamese so VI4 is really checked")
        # eval cases
        text = read(CONTENT / "eval-cases.md")
        cases = blocks(text, "Case")
        self.assertGreaterEqual(len(cases), 3)
        parsed = []
        for case in cases:
            obj = json_block(case["lines"])
            self.assertTrue(CASE_KEYS <= set(obj), "Case %d keys %s" % (case["n"], sorted(obj)))
            self.assertIn(obj["kind"], CASE_KINDS)
            self.assertEqual(case["title"], obj["kind"], "heading kind must equal JSON kind")
            parsed.append(obj)
        self.assertEqual(CASE_KINDS, {c["kind"] for c in parsed})
        self.assertTrue(any(c["should_trigger"] is False for c in parsed))
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t) / "writing-commit-messages"
            for c in parsed:
                for rel in c["fixtures"]:
                    (folder / rel).parent.mkdir(parents=True, exist_ok=True)
                    (folder / rel).write_text("sample\n", encoding="utf-8")
            folder.mkdir(exist_ok=True)
            (folder / "rubric.md").write_text("rubric\n", encoding="utf-8")
            (folder / "cases.json").write_text(json.dumps({"skill_name": "writing-commit-messages", "cases": parsed}), encoding="utf-8")
            errors = [f for f in studio_evals.check_evals(folder) if f["level"] == "ERROR"]
            self.assertEqual([], errors)
        # hand-written agentskills export example
        marker = re.search(r"(?im)^## Agentskills export.*$", text)
        self.assertIsNotNone(marker, "eval-cases.md needs a '## Agentskills export' section")
        exported = json_block(text[marker.end():].splitlines())
        self.assertEqual({"skill_name", "evals"}, set(exported))
        for item in exported["evals"]:
            self.assertEqual(EXPORT_EVAL_KEYS, set(item))
        self.assertEqual(expected_export("writing-commit-messages", parsed), exported)
        # exemplars
        self.assertTrue((EXEMPLAR / "SKILL.md").is_file())
        self.assertTrue((EXEMPLAR_VI / "SKILL.md").is_file())

    def test_content_outside_skills(self):
        self.assertFalse(any(p.name == "examples" for p in (ROOT / "skills").rglob("*")), "examples/ must not live under skills/")
        self.assertFalse((ROOT / "content").exists(), "content/ moved to examples/ (SPR-03 TK2)")

    def test_exemplar_validates_clean(self):
        findings = studio_validate.validate_skill(EXEMPLAR)
        self.assertEqual([], [f for f in findings if f["level"] in ("ERROR", "WARN")], findings)
        text = read(EXEMPLAR / "SKILL.md")
        self.assertLessEqual(len(text.splitlines()), 40)
        self.assertIn("## Gotchas", text)
        self.assertRegex(text, r'(?m)^  version: "1\.0\.0"$')
        self.assertTrue(EXEMPLAR.name.startswith("writing-"), "gerund name")

    def test_exemplar_vi_validates_clean(self):
        findings = studio_validate.validate_skill(EXEMPLAR_VI)
        self.assertEqual([], [f for f in findings if f["level"] in ("ERROR", "WARN")], findings)
        text = read(EXEMPLAR_VI / "SKILL.md")
        self.assertLessEqual(len(text.splitlines()), 40)
        self.assertEqual(text, (EXEMPLAR_VI / "SKILL.md").read_text(encoding="utf-8"), "body must be NFC")
        self.assertEqual("vi", studio_lint.detect_lang(skill_body(EXEMPLAR_VI)))
        self.assertIn("## Gotchas", text)
        self.assertRegex(text, r'(?m)^  version: "1\.0\.0"$')


class PairCheckerNegativeTests(unittest.TestCase):
    """The checkers must reject bad input given as plain strings; no real file is edited."""

    GOOD = (
        "### Pair 1 — Demo\n"
        '- **Bad:** "Helps with documents."\n'
        '- **Good:** "Extracts text from PDF files. Use when the user mentions PDFs."\n'
        "- **Why:** vì sao.\n"
        "- **Source:** https://agentskills.io/specification\n"
    )

    def one(self, text: str) -> dict:
        return blocks(text, "Pair")[0]

    def test_complete_pair_passes(self):
        self.assertEqual([], pair_problems(self.one(self.GOOD)))
        self.assertEqual([], pair_problems(self.one(self.GOOD.replace("https://agentskills.io/specification", INTERNAL_TAG + " SK-05"))))

    def test_missing_source_fails(self):
        text = "\n".join(l for l in self.GOOD.splitlines() if not l.startswith("- **Source:**"))
        self.assertTrue(any("Source" in p for p in pair_problems(self.one(text))))

    def test_missing_other_lines_fail(self):
        for key in ("Bad", "Good", "Why"):
            text = "\n".join(l for l in self.GOOD.splitlines() if not l.startswith("- **%s:**" % key))
            self.assertTrue(any(key in p for p in pair_problems(self.one(text))), key)

    def test_foreign_source_url_fails(self):
        text = self.GOOD.replace("https://agentskills.io/specification", "https://example.com/blog/skills")
        self.assertTrue(pair_problems(self.one(text)))
        mixed = self.GOOD.replace("https://agentskills.io/specification", "https://agentskills.io/specification and https://example.com/x")
        self.assertTrue(pair_problems(self.one(mixed)))

    def test_source_without_url_or_internal_tag_fails(self):
        text = self.GOOD.replace("https://agentskills.io/specification", "trust me")
        self.assertTrue(pair_problems(self.one(text)))

    def test_good_that_breaks_ds_or_vi4_is_detected(self):
        with tempfile.TemporaryDirectory() as t:
            codes = [f["code"] for f in validate_description("Giúp xử lý tài liệu.", Path(t))]
            self.assertIn("VI4", codes)
            codes = [f["code"] for f in validate_description("Helps with documents.", Path(t))]
            self.assertIn("DS3", codes)


if __name__ == "__main__":
    unittest.main()
