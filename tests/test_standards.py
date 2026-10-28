"""Shape checks for the documents under standards/ (SPR-33)."""
import ast
import inspect
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402

STANDARDS_DIR = Path(__file__).resolve().parent.parent / "standards"
ROOT_DIR = STANDARDS_DIR.parent

SOURCE_TAGS: tuple[str, ...] = (
    "spec", "bp", "cc", "ab", "ae", "pb", "fable-5", "sonnet-5.5",
)

# Cụm then chốt của rule hành vi (SPEC 9.2 "Không được cắt"): thiếu cụm nào là rule đã rơi.
BEHAVIOR_PHRASES: dict[str, tuple[str, ...]] = {
    "SK-03": ("tự do", "rủi ro", "approval", "tổn thất", "Trộn mức trong cùng skill"),
    "SK-04": ("A/B", "trực giác", "không kém", "ghim `--model`", "ghi `not_run`"),
    "SK-06": ("bước", "plan-validate-execute", "`Done when`", "đường quay lại"),
    "SK-07": ("validate", "giá trị hợp lệ", "văn phong", "giới hạn số lần", "báo blocker"),
    "SK-08": ("Strict", "Flexible", "Một mặc định, một lối thoát"),
    "SK-09": ("đường dẫn", "asset nằm trong skill", "không mạng", "không secret"),
    "SK-10": ("hook", "`block`", "chỉ chạy sau khi skill được gọi", "policy runtime", "PreToolUse"),
    "SK-11": ("baseline", "ngoài `skills/`", "một negative trigger"),
    "SK-12": ("5 000", "sau frontmatter", "guardrail và Definition of Done"),
    "SK-13": ("reasoning_extraction", "kết luận"),
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


def emitted_codes(source: str) -> set:
    """Check codes a Python source really emits: string constants given as the code argument of `emit(...)`, or assigned
    to the variable passed there. Comments, docstrings and unrelated strings do not count."""
    tree = ast.parse(source)
    assigned: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(node.value)
    codes: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and len(node.args) > 1 and (
                (isinstance(node.func, ast.Name) and node.func.id == "emit")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "emit")):  # `fs.emit(...)` since the engine split (SPR-02 TK4a)
            arg = node.args[1]
            parts = assigned.get(arg.id, []) if isinstance(arg, ast.Name) else [arg]
            codes.update(c.value for part in parts for c in ast.walk(part) if isinstance(c, ast.Constant) and isinstance(c.value, str))
    return codes


SKIP_DIRS: frozenset = frozenset({".git", ".tmp", ".worktrees", "__pycache__", "dist", "node_modules"})


def repo_files() -> list:
    """Every file of the working tree outside tool folders, in no particular order."""
    found = []
    for base, dirs, files in os.walk(ROOT_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found.extend(Path(base) / name for name in files)
    return found


def frontmatter_keys(text: str) -> set:
    """Top-level keys of the first `---` block of a document (empty when it has none)."""
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return set(re.findall(r"^([A-Za-z_][\w-]*):", m.group(1), re.M)) if m else set()


def section(text: str, heading: str) -> str:
    """Body of the '## heading' block, up to the next '## ' heading (empty when absent)."""
    m = re.search(r"^## %s[ \t]*$(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    return m.group(1) if m else ""


def read_std(name: str) -> str:
    return (STANDARDS_DIR / name).read_text(encoding="utf-8")


def sk_blocks(text: str) -> dict:
    """Map 'SK-NN' -> BODY lines of its '### SK-NN' block (the heading line is excluded, so a
    key phrase repeated in the title cannot mask a deleted body; ends at the next '#' heading)."""
    blocks: dict = {}
    current = None
    for line in text.splitlines():
        m = SK_HEAD_RE.match(line)
        if m:
            current = m.group(1)
            blocks[current] = ""
        elif re.match(r"^#{1,3} ", line):
            current = None
        elif current:
            blocks[current] += line + "\n"
    return blocks


# Câu định nghĩa "không pass giả" cũ (file, chuỗi con nguyên văn) — SPR-33 TK5 đóng băng; phải biến khỏi tài liệu cấp repo.
OLD_NO_FAKE_PASS: list[tuple[str, str]] = [
    ("standards/EVALUATION_STANDARD.md",
     "**Không** dùng một agent tự nhận đã pass nếu không có log/artefact."),
    ("standards/EVALUATION_STANDARD.md",
     "Nếu chưa chạy model, ghi `not_run` và không gọi production-tested."),
    ("standards/EVALUATION_STANDARD.md",
     "Giữ những trường `null` và `not_run` cho đến khi có test thật; **không tự điền score/pass**."),
    ("standards/SKILL_AUTHORING_STANDARD.md",
     "Kết quả chưa thực thi phải gắn `not_run`."),
    ("README.md",
     'Evals được phép ghi "not_run" nếu chưa thực thi, tuyệt đối không ghi pass giả.'),
    ("evals/RUNBOOK.md",
     "nếu không chạy được, ghi `not_run` thay vì giả kết quả."),
    ("standards/README.md",
     "eval chưa chạy ghi `not_run`, không ghi pass giả."),
    ("standards/DOC_TYPES.md",
     "Nếu chưa chạy model, ghi `not_run` và không gọi production-tested."),
    ("standards/HARNESSES.md",
     "Nếu chưa chạy model, ghi `not_run` và không gọi production-tested."),
]

# DOC_TYPES.md and HARNESSES.md are new (SPR-03 TK5): they must not define the rule, and they replaced no sentence of it, so no link is required there.
NO_LINK_NEEDED: frozenset = frozenset({"standards/DOC_TYPES.md", "standards/HARNESSES.md"})


def github_slug(title: str) -> str:
    """Anchor kiểu GitHub: chữ thường, bỏ dấu câu (giữ chữ, số, gạch dưới, gạch nối), khoảng trắng thành gạch nối."""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


class StandardsTest(unittest.TestCase):
    def test_memo_v0_is_archived_not_in_repo(self):
        """FR4.5: the v0 memo lives in the OpcOS ledger archive (superseded); no copy stays in the repository."""
        found = [f.relative_to(ROOT_DIR).as_posix() for f in repo_files() if f.name == "MEMO-SKILL-V0.md"]
        self.assertEqual([], found, "MEMO-SKILL-V0.md must not be in the repository")

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
        # SPR-03 TK5: the standard took the live rules of CORE_STANDARD, RULES_AND_PRECEDENCE and SKILL_LIFECYCLE; budget = 5 599 chars * 1.3 (brief TK5), no more.
        self.assertLessEqual(len(text), 7278)
        self.assertIn("overlap", sk_blocks(text).get("SK-05", ""), "SK-05 needs the overlap idea between skill descriptions")
        self.assertIn("`check` đạt", sk_blocks(text).get("SK-07", ""), "SK-07 needs 'xong = `check` đạt'")
        self.assertIn("(EVALUATION_STANDARD.md#không-pass-giả-not_run)", text, "the not_run link must reach its section")
        self.assertIn("(EVALUATION_STANDARD.md)", text.split("## Definition of Done")[-1], "DoD must point to the model-eval standard")

    def test_sk_blocks_exclude_heading_line(self):
        blocks = sk_blocks("### SK-03 — Mức tự do theo rủi ro [MUST] · kiểm: review\nthân\n### SK-04 — x [SHOULD] · kiểm: review\n")
        self.assertEqual(blocks["SK-03"], "thân\n")

    def test_authoring_standard_check_codes_exist_in_validator(self):
        text = read_std("SKILL_AUTHORING_STANDARD.md")
        emitted = emitted_codes(_engine.engine_source())
        for head in re.findall(r"^### SK-\d\d .*kiểm: (.*)$", text, re.M):
            codes = set(re.findall(r"`([A-Z]{2}\d+|SEC)`", head))
            for pre, a, b in re.findall(r"`([A-Z]{2})(\d+)`–`[A-Z]{2}(\d+)`", head):
                codes.update("%s%s" % (pre, i) for i in range(int(a), int(b) + 1))
            for code in codes:
                self.assertIn(code, emitted, "%s is cited as a check but studio.py never emits it" % code)

    def test_emitted_codes_ignores_comments_and_docstrings(self):
        source = ('def f():\n    """Mentions "XX9"."""\n    # "XX8" in a comment\n    note = "XX7"\n'
                  '    code = "XX5" if note else "XX6"\n    return [emit("WARN", "XX1", p, 1, "m"), emit("ERROR", code, p, 2, "m")]\n')
        self.assertEqual(emitted_codes(source), {"XX1", "XX5", "XX6"}, "only codes passed to emit() count")

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
        self.assertIn("485", text, "skill-creator body measured at 485 lines")
        self.assertIn(">300", text, "skill-creator recommends a TOC for references >300 lines")
        self.assertIn("Studio chọn 100 dòng", text, "Studio keeps the 100-line TOC threshold")
        for code in ("A10", "A15", "A16", "SK-14", "SK-15"):
            self.assertIn(code, text)

    def test_audit_checklist_has_sk14_sk15(self):
        text = (ROOT_DIR / "skills" / "skill-creator-studio" / "references" / "AUDIT_CHECKLIST.md").read_text(encoding="utf-8")
        self.assertIn("SK-14", text)
        self.assertIn("SK-15", text)
        self.assertIn("two levels", text, "AUDIT_CHECKLIST needs the three cutting questions")
        self.assertNotIn("hai tầng", text, "AUDIT_CHECKLIST is an English file")

    def test_vi_standard_shape(self):
        p = STANDARDS_DIR / "VIETNAMESE_SKILL_WRITING.md"
        self.assertTrue(p.exists(), "standards/VIETNAMESE_SKILL_WRITING.md is missing")
        text = read_std("VIETNAMESE_SKILL_WRITING.md")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), 80)
        rules = {}
        for ln in lines:
            m = re.match(r"^- \*\*(V\d\d)\*\*", ln)
            if m:
                rules.setdefault(m.group(1), []).append(ln)
        self.assertEqual(sorted(rules), ["V%02d" % n for n in range(1, 15)], "need V01..V14")
        for code, found in rules.items():
            self.assertEqual(len(found), 1, "%s must appear once as a rule line" % code)
            self.assertTrue("[máy: VI" in found[0] or "[review]" in found[0], "%s has no check label" % code)
        machine = {"V03": "VI3", "V09": "VI1", "V11": "VI2", "V13": "VI4", "V14": "VI5"}
        for code, line in ((c, r[0]) for c, r in rules.items()):
            if code in machine:
                self.assertIn("[máy: %s]" % machine[code], line, "%s must map to %s" % (code, machine[code]))
            else:
                self.assertIn("[review]", line, "%s is review-only" % code)
        start = lines.index("## Thuật ngữ")
        table = []
        for ln in lines[start + 1:]:
            if ln.startswith("#"):
                break
            if ln.startswith("|"):
                table.append(ln)
        rows = [ln for ln in table if not re.match(r"^\|\s*(Thuật ngữ|-+)", ln)]
        self.assertTrue(rows, "glossary table is empty")
        self.assertLessEqual(len(rows), 20)
        self.assertIn("multilingual-support", text)
        self.assertIn("SKILL_AUTHORING_STANDARD.md", text)

    def test_no_fake_pass_defined_once(self):
        md_files = [
            f for f in ROOT_DIR.rglob("*.md")
            if not any(part in (".git", ".tmp", ".worktrees", "dist", "runs") for part in f.relative_to(ROOT_DIR).parts)
        ]
        heading = re.compile(r"^## Không pass giả", re.M)
        defining = sorted(
            f.relative_to(ROOT_DIR).as_posix() for f in md_files
            if heading.search(f.read_text(encoding="utf-8"))
        )
        self.assertEqual(
            defining, ["standards/EVALUATION_STANDARD.md"],
            "'## Không pass giả' must be defined exactly once, in EVALUATION_STANDARD.md; found in %s" % defining,
        )
        problems = []
        for rel, old in OLD_NO_FAKE_PASS:
            text = (ROOT_DIR / rel).read_text(encoding="utf-8")
            if old in text:
                problems.append("%s: old definition still present: %r" % (rel, old))
        self.assertFalse(problems, "; ".join(problems))
        # file đã thay câu định nghĩa phải có link tới mục duy nhất: đường tương đối theo vị trí file phải
        # trỏ tới file có thật (kể cả evals/RUNBOOK.md mà test_docs_links bỏ qua) và anchor phải bằng
        # slug kiểu GitHub tính từ tiêu đề thật.
        standard = ROOT_DIR / "standards" / "EVALUATION_STANDARD.md"
        title = next(
            ln[3:].strip() for ln in standard.read_text(encoding="utf-8").splitlines()
            if ln.startswith("## Không pass giả")
        )
        slug = github_slug(title)
        link = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
        for rel in sorted({r for r, _ in OLD_NO_FAKE_PASS} - {"standards/EVALUATION_STANDARD.md"} - NO_LINK_NEEDED):
            file = ROOT_DIR / rel
            ok = False
            for raw in link.findall(file.read_text(encoding="utf-8")):
                target, _, anchor = raw.strip("<>").partition("#")
                if not target.endswith("EVALUATION_STANDARD.md"):
                    continue
                resolved = (file.parent / target).resolve()
                if resolved == standard.resolve() and anchor == slug:
                    ok = True
            self.assertTrue(
                ok,
                "%s lacks a link that resolves to standards/EVALUATION_STANDARD.md#%s" % (rel, slug),
            )

    # --- SPR-03 TK5: standards/ shrinks from 11 to 8 files (FR4, FR1.3) ---

    EIGHT = ["DOC_TYPES.md", "EVALUATION_STANDARD.md", "HARNESSES.md", "README.md", "SECURITY_AND_PERMISSIONS.md",
             "SKILL_AUTHORING_STANDARD.md", "SOURCE_TRACEABILITY.md", "VIETNAMESE_SKILL_WRITING.md"]

    def test_standards_eight_files(self):
        """FR4.1: standards/ holds exactly these 8 files and each has title, status and updated."""
        self.assertEqual(self.EIGHT, sorted(p.name for p in STANDARDS_DIR.iterdir()))
        for name in self.EIGHT:
            with self.subTest(file=name):
                self.assertGreaterEqual(frontmatter_keys(read_std(name)), {"title", "status", "updated"})

    def test_frontmatter_keys_helper(self):
        self.assertEqual({"title", "status"}, frontmatter_keys('---\ntitle: "x"\nstatus: active\n---\n# h\n'))
        self.assertEqual(set(), frontmatter_keys("# no frontmatter\ntitle: x\n"))

    def test_no_thirteen_rules(self):
        """FR4.3: the old '13 rules' count is gone from every document (the changelog keeps the history)."""
        hits = []
        for f in repo_files():
            rel = f.relative_to(ROOT_DIR).as_posix()
            if f.suffix != ".md" or rel == "CHANGELOG.md" or rel.startswith("tests/fixtures/"):
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\b13 (rules|quy tắc|luật)\b", line):
                    hits.append("%s:%d" % (rel, n))
        self.assertEqual([], hits)

    def test_harnesses_keeps_checked_lines(self):
        """FR4.3: HARNESSES.md keeps the 4 `Checked:` lines the 4 adapters had (count measured in TK0, evidence/tk0-baseline.txt)."""
        text = read_std("HARNESSES.md")
        lines = [ln for ln in text.splitlines() if ln.startswith("Checked:")]
        self.assertEqual(4, len(lines), lines)
        for ln in lines:
            self.assertRegex(ln, r"^Checked: 2026-10-23 · nguồn")
        for needle in ("Claude Code", "Codex", "Antigravity", "`not_run:chưa mở lại`", "codex-cli 0.163.0"):
            self.assertIn(needle, text)

    def test_harnesses_antigravity_reads_agents_md_through_gemini_md(self):
        """Review TK4: one wording across HARNESSES.md and templates/starter-project: Antigravity gets AGENTS.md through GEMINI.md."""
        text = read_std("HARNESSES.md")
        self.assertIn("`GEMINI.md` trỏ về `AGENTS.md`", text)
        self.assertNotIn("`AGENTS.md` hoặc `GEMINI.md`", text)

    def test_evaluated_block_documented(self):
        """FR4.4: every key the gate reads from the `evaluated` block is in the table of EVALUATION_STANDARD, and the table invents none."""
        source = inspect.getsource(_engine.evals.model_evaluated_problems)
        self.assertNotIn("ev[", source, "the gate reads `evaluated` keys another way than ev.get(...): update the pattern below")
        read_by_gate = set(re.findall(r'\bev\.get\("(\w+)"\)', source))
        self.assertGreaterEqual(read_by_gate, {"result", "batch_sha", "batch_sha_kind", "sprint", "date", "harnesses", "evidence", "ab_report"})
        body = section(read_std("EVALUATION_STANDARD.md"), "Khối evaluated")
        self.assertTrue(body, "EVALUATION_STANDARD.md has no '## Khối evaluated'")
        documented = set(re.findall(r"^\| `(\w+)` \|", body, re.M))
        self.assertEqual(sorted(read_by_gate), sorted(documented))
        for value in _engine.evals.RESULT_VALUES:
            self.assertIn("`%s`" % value, body)
        for needle in ("40", "`commit`", "`tree`"):
            self.assertIn(needle, body)

    def test_doc_types_three_types(self):
        """FR4.2: DOC_TYPES.md has the 3 types, each with how it is recognised, what is required, what is forbidden and a length limit."""
        text = read_std("DOC_TYPES.md")
        titles = ["Skill", "Workflow / quy trình", "File luật agent"]
        self.assertEqual(titles, re.findall(r"^## (.+?)\s*$", text, re.M))
        for title in titles:
            for label in ("**Nhận loại:**", "**Bắt buộc:**", "**Cấm:**", "**Giới hạn:**"):
                self.assertIn(label, section(text, title), "%s lacks %s" % (title, label))
        self.assertIn("thoát 2", text)
        self.assertIn("≤ 300 dòng", section(text, "Workflow / quy trình"))
        self.assertIn("≤ 200 dòng", section(text, "File luật agent"))

    def test_moves_done(self):
        """FR1.3: each source path of the move table is gone and each target is there; only tests/fixtures may keep a registry/ folder."""
        moves = [
            ("adapters", "standards/HARNESSES.md"),
            ("registry/catalog.json", "evals/catalog.json"),
            ("registry/SKILL_CATALOG.md", None),
            ("QA_REPORT.md", None),
            ("standards/MEMO-SKILL-V0.md", None),
            ("ECOSYSTEM.md", "standards/README.md"),
            ("standards/ROBONUGGETS_46_RULE_MAP.md", "standards/SOURCE_TRACEABILITY.md"),
            ("standards/CORE_STANDARD.md", "standards/SKILL_AUTHORING_STANDARD.md"),
            ("standards/RULES_AND_PRECEDENCE.md", "standards/SKILL_AUTHORING_STANDARD.md"),
            ("standards/SKILL_LIFECYCLE.md", "standards/SKILL_AUTHORING_STANDARD.md"),
            ("templates/project", "templates/starter-project"),
            ("content", "examples"),
            ("skills/data-quality-audit", "examples/data-quality-audit"),
        ]
        for source, target in moves:
            with self.subTest(source=source):
                self.assertFalse((ROOT_DIR / source).exists(), "%s must be gone" % source)
                if target:
                    self.assertTrue((ROOT_DIR / target).exists(), "%s must exist" % target)
        stray = sorted({f.relative_to(ROOT_DIR).parent.as_posix() for f in repo_files() if f.relative_to(ROOT_DIR).parts[0] == "registry"})
        self.assertEqual([], stray, "no registry/ folder outside tests/fixtures")
        self.assertTrue(section(read_std("README.md"), "Hệ sinh thái"), "ECOSYSTEM.md became a section of standards/README.md")
        self.assertIn("FM1", read_std("SOURCE_TRACEABILITY.md"), "the ROBONUGGETS map moved into SOURCE_TRACEABILITY.md")

    def test_security_standard_forbids_loading_code_from_the_repo_it_sits_in(self):
        """Lesson LN3 of SPR-02: the engine has no way to load code from the repo that holds it (a copied engine cannot know that repo)."""
        text = read_std("SECURITY_AND_PERMISSIONS.md")
        self.assertIn("nạp mã", text)
        self.assertIn("repo chứa nó", text)


class SkillCreatorStudioManifestTests(unittest.TestCase):
    """SKILL.md of skill-creator-studio must not drift from the standard and from the real CLI (SPR-33 TK11)."""

    SKILL = ROOT_DIR / "skills" / "skill-creator-studio" / "SKILL.md"
    STUDIO = ROOT_DIR / "skills" / "skill-creator-studio" / "scripts" / "studio.py"

    @classmethod
    def help_of(cls, *args: str) -> str:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(cls.STUDIO), *args, "--help"],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        if proc.returncode != 0:
            raise AssertionError("studio.py %s --help exit %d: %s" % (" ".join(args), proc.returncode, proc.stderr))
        return proc.stdout

    def body(self) -> str:
        return self.SKILL.read_text(encoding="utf-8")

    def test_rule_count_matches_standard(self) -> None:
        standard = (ROOT_DIR / "standards" / "SKILL_AUTHORING_STANDARD.md").read_text(encoding="utf-8")
        expected = len(re.findall(r"^### SK-\d\d\b", standard, re.MULTILINE)) - 1  # minus SK-00
        stated = re.findall(r"\b(\d+) rules\b", self.body())
        self.assertEqual(
            stated, [str(expected)],
            "SKILL.md states rule counts %s, the standard has %d (without SK-00)" % (stated, expected),
        )

    def test_has_gotchas_and_no_resources(self) -> None:
        headings = re.findall(r"^## (.+?)\s*$", self.body(), re.MULTILINE)
        self.assertIn("Gotchas", headings)
        self.assertNotIn("Resources", headings)

    def test_every_flag_and_command_exists_in_real_help(self) -> None:
        top = self.help_of()
        commands = re.search(r"\{([a-z,\-]+)\}", top)
        self.assertIsNotNone(commands, top)
        names = commands.group(1).split(",")
        helps = {name: self.help_of(name) for name in names}
        everything = "\n".join(helps.values())
        body = self.body()
        flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", body))
        for needed in ("--lang", "--full", "--target"):
            self.assertIn(needed, flags, "%s is no longer mentioned in SKILL.md" % needed)
        missing = sorted(f for f in flags if f != "--help" and f not in everything)
        self.assertEqual(missing, [], "flags named in SKILL.md but absent from studio.py --help: %s" % missing)
        for value in re.findall(r"--target ([a-z-]+)", body):
            self.assertIn(value, helps["validate"], "--target %s is not a choice of validate" % value)
        listed = re.search(r"\(commands: ([^;]+);", body)
        self.assertIsNotNone(listed, "SKILL.md no longer lists the sub-commands")
        self.assertEqual(sorted(re.findall(r"`([a-z-]+)`", listed.group(1))), sorted(names))


if __name__ == "__main__":
    unittest.main()
