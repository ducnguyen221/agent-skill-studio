"""Constants of the Agent Skill Studio engine: version, regexes, limits, name lists (SPR-02 TK4a).

Internal module of `studio.py`; do not run it. It imports no other studio module (FR4.5), so it is a leaf.
"""

from __future__ import annotations

import os
import re

VERSION = "0.2.0"
PORTABLE_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
TARGETS = ("portable", "claude-code")
# Claude Code extension keys beyond the portable set (code.claude.com/docs/en/skills, read 2026-10-22).
CLAUDE_CODE_KEYS = frozenset({
    "when_to_use", "argument-hint", "arguments", "disable-model-invocation", "user-invocable",
    "disallowed-tools", "model", "effort", "context", "agent", "background", "hooks", "paths", "shell",
})
RESERVED_NAME_WORDS = ("anthropic", "claude")
CLAUDE_CODE_RESERVED_NAMES = frozenset({"synced"})
FORCE_RE = re.compile(r"\b(MUST|NEVER|ALWAYS|CRITICAL)\b")
REASON_RE = re.compile(r"\b(because|since|so that|otherwise|to avoid|in order to|vì|để|nếu không)\b", re.IGNORECASE)
STRICT_OPEN, STRICT_CLOSE = "<!-- studio:strict -->", "<!-- /studio:strict -->"
CONTENTS_RE = re.compile(r"^##\s+(Table of Contents|Contents|Mục lục)\s*$", re.IGNORECASE)
MD_LINK_RE = re.compile(r"\[([^\[\]]*)\]\([^()]*\)")  # [text](target) -> text; no nested brackets or parens, so a line of "[" stays linear
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
FENCE_OPEN_LIST_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")  # inside a list item a fence may sit deeper than 3 spaces (CommonMark: relative to the item)
BACKTICK_RUN_RE = re.compile(r"`+")
URL_RE = re.compile(r"https?://\S+")
LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s")
CONTENTS_MAX = 12
CONTENTS_WINDOW = 25  # Contents must start within the first 25 lines of the reference / body
REF_TOC_LINES = 100
BODY_TOC_LINES = 100
FRONTMATTER_EXTRA_MAX = 1024
LISTING_MAX = 1536  # Claude Code skill listing: description + when_to_use
TRIGGER_LATEST = 500  # the trigger phrase should begin inside the first 500 description characters
BODY_TOKEN_MAX = 5000
VI_CHARS = frozenset("ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")
VI_ACCENT_RATIO = 0.03  # FR16: at least this share of prose letters with a Vietnamese diacritic -> Vietnamese body
VI_SENTENCE_MAX = 40  # VI3 ceiling in words; 25 is advice only (VIETNAMESE_SKILL_WRITING.md V03)
VI5_SECTION_MIN_LETTERS = 80
VI5_ACCENT_MIN = 0.01
VI5_ENGLISH_BODY_SHARE = 0.7  # FR14.1: sections under VI5_ACCENT_MIN holding more than this share of the prose letters -> mostly English body, no VI5 per section
NON_ISO_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
VI_TRIGGER_RE = re.compile(r"(?i)\buse (this skill )?when\b")
VI_OK_MARK = "<!-- studio:vi-ok -->"
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")
SENTENCE_ABBREV_RE = re.compile(r"\b(e\.g|i\.e)\.")
TRIGGER_RE = re.compile(r"(?i)\b(use when|when to use|used when|for tasks involving)\b")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^\[\]\n]*\]\(((?:[^()\n]|\([^()\n]*\))+)\)")  # one line; the target may hold one level of balanced parens, x(1).md; the two branches start with different characters, so it stays linear
ABSOLUTE_LINK_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9+.\-]*:")  # a scheme (file:, smb:) or a drive letter (C:)
FRONT_KEY_RE = re.compile(r"^([a-zA-Z][\w-]*):(?:\s+(.*))?$")
META_KEY_RE = re.compile(r"^\s{2,}([\w.-]+):(?:\s+(.*))?$")
SKIP_DIRS = {"__pycache__", ".git", ".venv", "evals", "tests", ".pytest_cache", ".mypy_cache"}
EXPORT_FORMATS = ("agentskills",)
EXPORT_DEFAULT_OUT = "dist/agentskills"
EXPORT_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REJECT_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
REJECT_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
TEMPLATE_LANGS = ("en", "vi")
PROFILES = ("portable", "opcos")
DOCTOR_EXCLUDE_PARTS = (".claude/skills", ".agents/skills", ".worktrees", ".ads-worktrees", ".claude/worktrees", "node_modules", ".tmp", "__pycache__")
DOCTOR_PRUNE_SILENT = frozenset({".git", ".venv", ".pytest_cache", ".mypy_cache"})  # never skills, never worth a skipped[] line
CLOUD_MARKERS = ("OneDrive", "SharePoint")  # --skip-marker adds more: a synced folder need not carry either word
# FILE_ATTRIBUTE_RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS | OFFLINE | UNPINNED: a cloud placeholder; opening it can start a download. PINNED (0x80000) is left out on purpose: a pinned file is already local
CLOUD_ATTR_MASK = 0x40000 | 0x400000 | 0x1000 | 0x100000
CLOUD_TAG_MASK, CLOUD_TAG = 0xFFFF0FFF, 0x9000001A  # IO_REPARSE_TAG_CLOUD and its CLOUD_1..CLOUD_F family (the tag's bits 12-15 vary)
CLOUD_ATTRS_AVAILABLE = os.name == "nt"  # st_file_attributes exists on Windows only
ST8_ALLOWED_DIRS = frozenset({"references", "scripts", "assets", "agents", "tests"})  # a folder name is compared in lower case here and against SKIP_DIRS (evals, tests, tooling folders), which stay quiet
OPCOS_PROVENANCE_KEYS = frozenset({"source", "source_sha", "base_sha", "rewrite_before_public"})
CODEX_BODY_MAX_BYTES = 8000  # [codex 0.147]; standards/SOURCE_TRACEABILITY.md A16
DOCTOR_FAIL_ON = ("error", "warn", "new")
DOCTOR_SCHEMA = 1
OPCOS_DESC_CHARS = 350  # profile opcos: BG1 above this many description characters (measure-skill-budget.py DESC_CHAR_LIMIT)
OPCOS_DESC_TOTAL_BYTES = 20000  # profile opcos: the `budget` block is over above this many description bytes
DOCTOR_MAX_DEPTH = 12  # folder levels below a root
DOCTOR_MAX_DIRS = 100000  # folders listed per run
DOCTOR_MAX_SKILLS = 3000
DOCTOR_MAX_FILE_BYTES = 1_000_000  # a SKILL.md or reference above this is not read (SZ1)
DOCTOR_MAX_FILES_PER_SKILL = 5000  # files and folders listed inside one skill; the rest is not listed (SZ1)
DOCTOR_MAX_SKILL_DEPTH = 12  # folder levels listed inside one skill
PATHS_JSON_MAX = 256 * 1024  # a paths.json above this is refused unread (SPR-04 FR1.1)
MANIFEST_MAX = 64 * 1024  # a plugin manifest above this is refused unread (FR1.2)
PATHS_JSON_UP = 6  # folder levels above the working folder that are searched for paths.json
MANIFEST_SKILLS_MAX = 64  # entries of a manifest `skills` list that are looked at; the rest is not
DOCTOR_REPORT_HEAD = re.compile(rb'\A(?:\xef\xbb\xbf)?\s*\{\s*"schema"\s*:')  # how a doctor report starts
CATALOG_MD_HEAD = re.compile(rb'\A(?:\xef\xbb\xbf)?<!-- studio catalog -->[ \t]*(?:\r?\n|\Z)')  # how a CATALOG.md starts: the marker is the whole first line
FM_ORDER = ("name", "description", "license", "compatibility", "allowed-tools", "metadata")
DOC_MIN_KEYS = ("title", "status", "updated")
FMT_META_LINE_RE = re.compile(r"^(\s{2,}[\w.-]+:)[ \t]+(\S.*)$")  # match a line already stripped at the end: no lazy group followed by blanks
FMT_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")  # same: match a line already stripped at the end
FMT_CONCLUSION_RE = re.compile(r"^>\s*\*\*(Conclusion|Kết luận):\*\*")
FMT_STEP_RE = re.compile(r"(?i)^(step|bước)\s+\d+\s+[—–-]\s*\S")
FMT_PROCESS_SECTIONS = (
    (re.compile(r"(?i)^(when to use|khi nào dùng)"), "When to use / not"),
    (re.compile(r"(?i)^(steps|bước)$"), "Steps"),
    (re.compile(r"(?i)^(gotchas|cạm bẫy|lưu ý)$"), "Gotchas"),
    (re.compile(r"(?i)^(done when|kiểm xong)$"), "Done when"),
)
FMT_STEP_LABELS = tuple(
    (re.compile(r"(?i)^\s*(?:[-*+]\s+)?(?:\*\*)?(?:%s):" % names), label)
    for names, label in (("Command|Lệnh", "Command:"), ("Expect|Kỳ vọng", "Expect:"), ("Stop if|Dừng nếu", "Stop if:")))
FMT_PRUNE_DIRS = frozenset({".git", ".tmp", ".worktrees", "dist", "node_modules", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache"})
FMT_FIXTURE_PATHS = (("tests", "fixtures"), ("evals", "*", "fixtures"))  # fmt --all skips these deliberately broken test data folders (repo-relative; "*" = any one name)
FMT_FRONT_SEARCH_LINES = 60  # a frontmatter block that starts later than this is not looked for
FMT_BLOCKING_REASONS = frozenset({"would-change-text", "not-utf8", "unreadable", "too-many-folders", "limit"})  # skipped for these: exit 1 even inside a folder
WIN_DEVICE_NAMES = frozenset(["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"]
                             + ["COM%d" % n for n in range(1, 10)] + ["LPT%d" % n for n in range(1, 10)]
                             + ["COM\u00b9", "COM\u00b2", "COM\u00b3", "LPT\u00b9", "LPT\u00b2", "LPT\u00b3"])
WIN_NAME_CODES = {"stream": "EX4", "trailing": "EX9", "device": "EX10", "short": "EX11"}  # kind -> EX code; kinds are the first word of the reason
SHORT_NAME_RE = re.compile(r"~[0-9]")
