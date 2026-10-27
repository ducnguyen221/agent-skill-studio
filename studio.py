#!/usr/bin/env python3
"""Agent Skill Studio: portable skill factory and static auditor.

Python 3.9+, standard library only. Supports a documented YAML frontmatter
subset (single-line string scalars, folded block strings, metadata string map).
This is a static validator, not a Claude/Codex/Antigravity evaluation runner.

Use `python3 studio.py --help` and per-subcommand --help.
"""

from __future__ import annotations

import argparse
import ast
import bisect
import errno
import functools
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"
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
# (source dir under templates/, mirror dir under skills/skill-creator-studio/assets/)
TEMPLATE_PAIRS = (("skill-template", "skill-template"), ("skill-template-full", "skill-template-full"))
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
DOCTOR_MAX_DEPTH = 12  # folder levels below a root
DOCTOR_MAX_DIRS = 100000  # folders listed per run
DOCTOR_MAX_SKILLS = 3000
DOCTOR_MAX_FILE_BYTES = 1_000_000  # a SKILL.md or reference above this is not read (SZ1)
DOCTOR_MAX_FILES_PER_SKILL = 5000  # files and folders listed inside one skill; the rest is not listed (SZ1)
DOCTOR_MAX_SKILL_DEPTH = 12  # folder levels listed inside one skill
DOCTOR_REPORT_HEAD = re.compile(rb'\A(?:\xef\xbb\xbf)?\s*\{\s*"schema"\s*:')  # how a doctor report starts
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
FMT_FRONT_SEARCH_LINES = 60  # a frontmatter block that starts later than this is not looked for
FMT_BLOCKING_REASONS = frozenset({"would-change-text", "not-utf8", "unreadable", "too-many-folders", "limit"})  # skipped for these: exit 1 even inside a folder


def emit(level: str, code: str, path: Path, line: int, message: str) -> dict:
    return {"level": level, "code": code, "path": str(path), "line": line, "message": message}


def scalar(value: str) -> str:
    """Parse a *small, explicit subset* of YAML string scalars, not general YAML."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            if value[0] == "'":
                return value[1:-1].replace("''", "'")
            raise ValueError("malformed quoted scalar; check quote escaping")
    if ": " in value and not value.startswith("http"):
        raise ValueError("unquoted ': ' is ambiguous YAML; quote this scalar")
    if value.startswith(("[", "{", "@", "`")):
        raise ValueError("complex YAML scalar is not supported by the offline parser; quote it")
    return value


def parse_frontmatter(text: str, path: Path, opaque_keys: frozenset = frozenset()) -> tuple[dict, list, int]:
    """Parse the supported YAML subset. A key in `opaque_keys` with an empty value keeps its nested
    indented block as one raw string (no FM1); the block ends at the next top-level key."""
    lines = text.splitlines()
    findings: list[dict] = []
    if not lines or lines[0].strip() != "---":
        return {}, [emit("ERROR", "FM1", path, 1, "SKILL.md must start on line 1 with YAML '---'")], 0
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, [emit("ERROR", "FM1", path, 1, "closing frontmatter '---' not found")], 0
    parsed: dict = {}
    key = None
    mode = None  # 'block', 'meta', 'opaque' or None
    block_lines: list[str] = []
    block_kind = None

    def flush():
        nonlocal key, mode, block_lines, block_kind
        if mode == "block" and key is not None:
            parsed[key] = ("\n" if block_kind == "|" else " ").join(block_lines).strip()
        elif mode == "opaque" and key is not None:
            parsed[key] = "\n".join(block_lines)
        mode = None
        block_lines = []
        block_kind = None

    for index in range(1, end):
        raw = lines[index]
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            flush()
            match = FRONT_KEY_RE.fullmatch(raw.rstrip())
            if not match:
                findings.append(emit("ERROR", "FM1", path, index + 1, "invalid YAML top-level key/value line"))
                key = None
                continue
            key, val = match.group(1), (match.group(2) or "").strip()
            if key in parsed:
                findings.append(emit("ERROR", "FM1", path, index + 1, "duplicate frontmatter key '%s'" % key))
            if val in (">", ">-", "|", "|-"):
                mode, block_kind = "block", val[0]
                parsed[key] = ""
            elif key == "metadata" and val == "":
                mode = "meta"
                parsed[key] = {}
            elif key in opaque_keys and val == "":
                mode = "opaque"
                parsed[key] = ""
            else:
                try:
                    parsed[key] = scalar(val)
                except ValueError as exc:
                    findings.append(emit("ERROR", "FM1", path, index + 1, str(exc)))
                    parsed[key] = val
        else:
            if mode == "block" and raw.startswith((" ", "\t")):
                block_lines.append(raw.strip())
            elif mode == "opaque":
                block_lines.append(raw.rstrip())
            elif mode == "meta":
                match = META_KEY_RE.fullmatch(raw.rstrip())
                if not match:
                    findings.append(emit("ERROR", "FM1", path, index + 1, "metadata must be a simple indented key: string map"))
                    continue
                try:
                    parsed["metadata"][match.group(1)] = scalar((match.group(2) or "").strip())
                except ValueError as exc:
                    findings.append(emit("ERROR", "FM1", path, index + 1, str(exc)))
            else:
                findings.append(emit("ERROR", "FM1", path, index + 1, "unexpected indentation outside YAML block/metadata"))
    flush()
    return parsed, findings, end + 1


def repo_root(start: Path) -> Path | None:
    for candidate in [start.resolve()] + list(start.resolve().parents):
        if (candidate / "standards" / "SKILL_AUTHORING_STANDARD.md").is_file() and (candidate / "templates" / "skill-template" / "SKILL.md").is_file():
            return candidate
    return None


def skill_dirs(root: Path) -> list[Path]:
    p = root / "skills"
    if not p.is_dir():
        return []
    return sorted(x for x in p.iterdir() if x.is_dir() and (x / "SKILL.md").exists())


def is_link(path: Path) -> bool:
    """True for a symlink or, on Windows, any reparse point such as a directory junction (os.path.isjunction needs Python 3.12)."""
    if path.is_symlink():
        return True
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False


def valid_resolved_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


@functools.lru_cache(maxsize=8)
def _secret_dirs(home: str) -> tuple:
    """Normalized, case-folded spellings of ~/.secret. Only `home` is resolved (a lstat chain up to it), never the secret folder."""
    return (os.path.normcase(os.path.abspath(os.path.join(home, ".secret"))).casefold(),
            os.path.join(os.path.normcase(os.path.realpath(home)), ".secret").casefold())


def _long_name_text(text: str) -> str:
    """On Windows, `text` with 8.3 short names (ONEDRI~1) replaced by the long names, for the longest prefix that exists; else `text`.
    Asks the OS about names only (GetLongPathNameW lists directory entries; it opens no file). Any failure keeps `text`."""
    if os.name != "nt" or "~" not in text:
        return text
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        head, tail = text, []
        while head:
            size = ctypes.windll.kernel32.GetLongPathNameW(head, buf, len(buf))
            if 0 < size < len(buf):
                return os.path.join(buf.value, *reversed(tail)) if tail else buf.value
            up, name = os.path.split(head)
            if not name or up == head:
                break
            head, tail = up, tail + [name]
    except (OSError, AttributeError, ImportError, ValueError):
        pass
    return text


def zone_reason(path, markers=CLOUD_MARKERS) -> str | None:
    """'cloud' for a path naming one of `markers` (OneDrive, SharePoint and any --skip-marker; case-insensitive), 'secret-zone' for ~/.secret
    or any folder called .secret (any case, any platform), else None. Compares strings only: it never stats, lists or opens `path` (RK15)."""
    given = os.path.abspath(os.fspath(path))
    texts = [os.path.normcase(given).casefold()]
    long_form = os.path.normcase(_long_name_text(given)).casefold()
    if long_form != texts[0]:
        texts.append(long_form)  # an 8.3 spelling (ONEDRI~1) hides the folder's real name from a string test
    if any(marker.casefold() in text for text in texts for marker in markers):
        return "cloud"
    if any(".secret" in text.split(os.sep) for text in texts):
        return "secret-zone"
    try:
        secrets = _secret_dirs(str(Path.home()))
    except (RuntimeError, KeyError, OSError):
        return None
    return "secret-zone" if any(text == s or text.startswith(s + os.sep) for text in texts for s in secrets) else None


def _stat_is_cloud(info) -> bool:
    """Cloud attribute bits, or a cloud reparse tag (st_reparse_tag, Python 3.8+ on Windows). Reads the stat result only, never the file."""
    if getattr(info, "st_file_attributes", 0) & CLOUD_ATTR_MASK:
        return True
    return (getattr(info, "st_reparse_tag", 0) & CLOUD_TAG_MASK) == CLOUD_TAG


def entry_is_cloud(entry) -> bool:
    """True when a directory entry carries Windows cloud attributes or a cloud reparse tag. DirEntry.stat(follow_symlinks=False) reads the listing, not the file."""
    if not CLOUD_ATTRS_AVAILABLE:
        return False
    try:
        return _stat_is_cloud(entry.stat(follow_symlinks=False))
    except OSError:
        return False


def path_is_cloud(path) -> bool:
    """The same test for a path: one lstat (metadata only; it neither follows a link nor starts a download)."""
    if not CLOUD_ATTRS_AVAILABLE:
        return False
    try:
        return _stat_is_cloud(os.lstat(path))
    except OSError:
        return False


def _plain_path(path) -> str:
    """Case-normalised absolute spelling without a \\\\?\\ or \\\\?\\UNC\\ prefix. Names only."""
    text = os.path.abspath(os.fspath(path))
    if text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(text)


def _broad_by_name(text: str, homes: list) -> bool:
    if not os.path.splitdrive(text)[1].strip("\\/"):
        return True
    for home in homes:
        try:
            if os.path.commonpath([text, home]) == text:
                return True
        except ValueError:  # another drive
            continue
    return False


def namespace_refused(path) -> bool:
    """True for a root spelled in a Windows device namespace (\\\\.\\..., \\??\\..., and \\\\?\\ followed by anything but a drive letter or UNC\\:
    GLOBALROOT, Volume{GUID}...) or on an administrative share (\\\\host\\C$, \\\\?\\UNC\\host\\C$). Judged on the spelling alone: such a
    path can name the home folder or a whole drive in a way the other checks do not recognise, so it is never a root."""
    text = os.fspath(path).replace("/", "\\")
    if text[:4] in ("\\\\.\\", "\\??\\") or text in ("\\\\.", "\\??"):
        return True
    if text.startswith("\\\\?\\"):
        rest = text[4:]
        if re.match(r"[A-Za-z]:(\\|$)", rest):
            return False
        if rest[:4].upper() != "UNC\\":
            return True
        text = "\\\\" + rest[4:]
    if text.startswith("\\\\"):
        parts = [x for x in text[2:].split("\\") if x]
        return len(parts) >= 2 and parts[1].endswith("$")
    return False


def root_too_broad(path, markers=CLOUD_MARKERS) -> bool:
    """True for a drive or filesystem root, the home folder, or any folder above it, judged on the spelling given, on the normalised
    spelling (no \\\\?\\ prefix) and on the real path (a junction or symlink into the home, an 8.3 name). The real path is looked up only
    for a local path outside the cloud and secret zones; a UNC path is never resolved. A device namespace or an administrative share
    is always too broad (namespace_refused)."""
    if namespace_refused(path):
        return True
    given = _plain_path(path)
    homes = []
    try:
        home = Path.home()
        homes.append(_plain_path(home))
        if not zone_reason(home, markers):
            homes.append(_plain_path(home.resolve()))
    except (RuntimeError, KeyError, OSError):
        pass
    if _broad_by_name(given, homes):
        return True
    if given.startswith("\\\\") or zone_reason(given, markers):
        return False
    try:
        real = _plain_path(Path(given).resolve())
    except (OSError, RuntimeError):
        return False
    return real != given and _broad_by_name(real, homes)


def input_file_problem(source: Path, markers=CLOUD_MARKERS) -> str | None:
    """Why an input file (--roots-file, --baseline) may not be read, else None. Decided before opening it: not an NTFS data stream
    (name:stream), not a secret-looking name, not a cloud placeholder, and neither the spelling given nor the real path (a link, an 8.3
    name such as SECRET~1) in a cloud or secret zone."""
    text = os.fspath(source)
    if os.name == "nt" and ":" in os.path.splitdrive(text)[1]:
        return "names an NTFS data stream; not read"
    if secret_file_name(source.name):
        return "has a secret-looking file name; not read"
    reason = zone_reason(source, markers)
    if not reason:
        if path_is_cloud(source):
            return "is a cloud placeholder; not read"
        try:
            real = source.resolve()
        except (OSError, RuntimeError):
            return "cannot be resolved; not read"
        if secret_file_name(real.name):
            return "is a link to a file with a secret-looking name; not read"
        reason = zone_reason(real, markers)
        if not reason and path_is_cloud(real):
            return "is a cloud placeholder; not read"
    return "is inside a %s zone; not read" % reason if reason else None


def link_crosses_link(base: Path, link: str) -> bool:
    """True when walking `link` from `base` passes through a symlink or junction. One lstat per step; nothing is followed or resolved."""
    current = Path(base)
    for part in re.split(r"[\\/]+", link):
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
        else:
            current = current / part
            if is_link(current):
                return True
    return False


def read_capped(path, limit: int | None) -> tuple:
    """(text, too_big). With a limit the file is read in binary up to limit+1 bytes and never further; newlines are folded as read_text does."""
    if limit is None:
        return Path(path).read_text(encoding="utf-8"), False
    with open(path, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        return None, True
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"), False


def strip_code_spans(text: str, repl: str = " ") -> str:
    """Replace each inline code span as re.sub(r"(`+).+?\\1", repl, text) did, but in linear time: a long run of backticks made
    that regex cubic. The regex's rule, worked out per run of K backticks that starts a try: the longest opener k that has a closer wins,
    a closer being k backticks after at least one character, inside the same run (k <= (K-1)//2) or in a later run at least k long.
    A run no closer can follow stays plain text. Each line is handled alone, as `.` never matched a newline."""
    if "`" not in text:
        return text
    return "\n".join(_strip_code_spans_line(part, repl) for part in text.split("\n"))


def _strip_code_spans_line(line: str, repl: str) -> str:
    runs = [match.span() for match in BACKTICK_RUN_RE.finditer(line)]
    if not runs:
        return line
    longest_after = [0] * (len(runs) + 1)
    for index in range(len(runs) - 1, -1, -1):
        longest_after[index] = max(longest_after[index + 1], runs[index][1] - runs[index][0])
    out, copied, index, pos = [], 0, 0, runs[0][0]
    while index < len(runs):
        width = runs[index][1] - pos
        inside = (width - 1) // 2
        size = max(inside, min(width, longest_after[index + 1]))
        if size < 1:
            break  # no run is left to close anything
        if size == inside:
            end, last = pos + 2 * size + 1, index
        else:
            last = index + 1
            while runs[last][1] - runs[last][0] < size:
                last += 1
            end = runs[last][0] + size
        out.append(line[copied:pos])
        out.append(repl)
        copied = end
        if end < runs[last][1]:
            index, pos = last, end
        else:
            index = last + 1
            if index < len(runs):
                pos = runs[index][0]
    out.append(line[copied:])
    return "".join(out)


def has_xml_tag(text: str) -> bool:
    """Same answer as re.search(r"<[^>]+>", text), in linear time: a '<' whose first following '>' is not right behind it."""
    start = text.find("<")
    while start != -1:
        close = text.find(">", start + 1)
        if close == -1:
            return False
        if close > start + 1:
            return True
        start = text.find("<", start + 1)
    return False


def strip_html_comments(text: str, repl: str = " ") -> str:
    """Replace each `<!-- ... -->` that opens and closes on one line, as re.sub(r"<!--.*?-->") did, but in linear time:
    thousands of unclosed '<!--' made that regex quadratic."""
    out, pos = [], 0
    i = text.find("<!--")
    while i != -1:
        eol = text.find("\n", i + 4)
        j = text.find("-->", i + 4, len(text) if eol == -1 else eol)
        if j == -1:  # nothing closes on this line, so no later opener on it can either
            if eol == -1:
                break
            i = text.find("<!--", eol + 1)
            continue
        out.append(text[pos:i])
        out.append(repl)
        pos = j + 3
        i = text.find("<!--", pos)
    out.append(text[pos:])
    return "".join(out)


def lexically_inside(path, base) -> bool:
    """True when `path` is `base` or below it by name alone (`..` folded, nothing resolved or stat-ed)."""
    path, base = os.path.normcase(os.path.abspath(os.fspath(path))), os.path.normcase(os.path.abspath(os.fspath(base)))
    try:
        return os.path.commonpath([path, base]) == base
    except ValueError:  # different drives
        return False


def is_sensitive_name(name: str) -> bool:
    """File names doctor never opens, even inside a skill: .env*, *.credentials.json, auth.json, *.pem, *.key."""
    low = name.lower()
    return low.startswith(".env") or low.endswith(".credentials.json") or low == "auth.json" or low.endswith((".pem", ".key"))


def secret_file_name(name: str) -> bool:
    """is_sensitive_name plus the names the packager refuses to ship (REJECT_NAMES: secrets.json, credentials.json, id_rsa...): the names of
    files doctor is handed (--roots-file, --baseline, --out) and must not open."""
    return is_sensitive_name(name) or name.lower() in REJECT_NAMES


WIN_DEVICE_NAMES = frozenset(["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"]
                             + ["COM%d" % n for n in range(1, 10)] + ["LPT%d" % n for n in range(1, 10)]
                             + ["COM\u00b9", "COM\u00b2", "COM\u00b3", "LPT\u00b9", "LPT\u00b2", "LPT\u00b3"])
WIN_NAME_CODES = {"stream": "EX4", "trailing": "EX9", "device": "EX10", "short": "EX11"}  # kind -> EX code; kinds are the first word of the reason
SHORT_NAME_RE = re.compile(r"~[0-9]")


def unsafe_windows_name(component: str) -> str | None:
    """Why one path component is dangerous on Windows (whatever OS runs this), or None. The reason starts with its kind (see WIN_NAME_CODES):
    'stream' (a ':'), 'trailing' (ends with a dot or a space: Windows drops it, so 'auth.json.' IS auth.json), 'device' (CON, NUL, COM1, CONIN$...
    with or without an extension, any case), 'short' (8.3 alias such as AUTH~1.JSO). '.' and '..' are not judged here."""
    if component in ("", ".", ".."):
        return None
    if ":" in component:
        return "stream: '%s' contains ':' (drive letter or NTFS stream)" % component
    if component[-1] in ". ":
        return "trailing: '%s' ends with a dot or a space (Windows strips it, so it names another file)" % component
    if component.split(".", 1)[0].rstrip(" ").upper() in WIN_DEVICE_NAMES:
        return "device: '%s' is a reserved Windows device name" % component
    if SHORT_NAME_RE.search(component):
        return "short: '%s' looks like an 8.3 short name ('~' + digit), which can stand for a secret file" % component
    return None


class UnsafeOpen(OSError):
    """A file or folder is not the one that was checked (link, second hard link, swapped identity). `code` is the EX code to report."""

    def __init__(self, message: str, code: str = "EX13"):
        super().__init__(message)
        self.code = code


def open_nofollow_read(path, expect_stat=None, single_link: bool = True):
    """Open `path` for binary reading without following a link; return the file object. POSIX: O_NOFOLLOW. Windows (no O_NOFOLLOW): open, then compare
    (st_dev, st_ino) of the open handle with `expect_stat` (the lstat taken when the file was checked). Both: the handle must be a regular file and,
    with `single_link`, have exactly one name. Any mismatch raises UnsafeOpen. Windows residue: the open itself already follows a reparse point
    before the comparison (see README, "Rủi ro còn lại")."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
            raise UnsafeOpen("source is a symlink: %s" % path) from exc
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeOpen("source is not a regular file: %s" % path)
        if expect_stat is not None and (info.st_dev, info.st_ino) != (expect_stat.st_dev, expect_stat.st_ino):
            raise UnsafeOpen("source changed between check and copy: %s" % path)
        if single_link and info.st_nlink != 1:
            raise UnsafeOpen("source has %d names (hard link): %s" % (info.st_nlink, path))
        return os.fdopen(fd, "rb")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def create_exclusive(path):
    """Create `path` for binary writing, failing (FileExistsError) when anything, a link included, is already there; never writes through a link."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(path, flags, 0o666), "wb")


def link_in_chain(path, stop):
    """The first link/junction among `path` and its parents up to and including `stop` (all of them when `stop` is not above `path`), else None."""
    current, stop = Path(path), Path(stop)
    while True:
        if is_link(current):
            return current
        if current == stop or current.parent == current:
            return None
        current = current.parent


def zone_named(name: str, markers=CLOUD_MARKERS) -> bool:
    """A single folder name that is a cloud/secret zone by itself (.secret, or one containing a marker such as OneDrive/SharePoint)."""
    low = name.casefold()
    return low == ".secret" or any(marker.casefold() in low for marker in markers)


def walk_files(base: Path, markers=CLOUD_MARKERS, max_files: int | None = None, max_depth: int | None = None, skip_names=()) -> tuple[list[Path], set, set, set, bool]:
    """(every file and folder under `base`, sorted; the links, the real folders and the cloud placeholders the listing itself reports; cut short).
    A symlink or junction (any reparse point) is listed as a link and never entered, a folder named like a cloud/secret zone and
    anything carrying cloud attributes are listed but never entered or opened, and nothing else is stat-ed per entry except folders about to be entered.
    The walk stops after `max_files` entries (default DOCTOR_MAX_FILES_PER_SKILL) and does not enter folders `max_depth` levels down
    (default DOCTOR_MAX_SKILL_DEPTH); either sets the last value, True. An entry whose name is in `skip_names` is left out unlisted and unentered."""
    max_files = DOCTOR_MAX_FILES_PER_SKILL if max_files is None else max_files
    max_depth = DOCTOR_MAX_SKILL_DEPTH if max_depth is None else max_depth
    found, links, dirs, cloud, stack, cut = [], set(), set(), set(), [(base, 0)], False
    while stack and not cut:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as scan:
                entries = list(scan)
        except OSError:
            continue
        for entry in entries:
            if entry.name in skip_names:
                continue
            if len(found) >= max_files:
                cut = True
                break
            path = Path(entry.path)
            found.append(path)
            try:
                if entry_is_cloud(entry):
                    cloud.add(path)
                    if entry.is_dir(follow_symlinks=False):
                        dirs.add(path)
                elif entry.is_symlink():
                    links.add(path)
                elif entry.is_dir(follow_symlinks=False):
                    if zone_named(entry.name, markers):  # decided from the name: no stat, even for a link
                        dirs.add(path)
                    elif is_link(path):
                        links.add(path)
                    else:
                        dirs.add(path)
                        if depth + 1 < max_depth:
                            stack.append((path, depth + 1))
                        else:
                            cut = True
            except OSError:
                continue
    return sorted(found), links, dirs, cloud, cut


def check_evals(folder: Path) -> list[dict]:
    f = folder / "cases.json"
    results: list[dict] = []
    if not f.is_file():
        return [emit("ERROR", "EV1", f, 0, "missing evals/<skill-name>/cases.json")]
    try:
        obj = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [emit("ERROR", "EV1", f, 0, "cannot read evals JSON: %s" % exc)]
    if not isinstance(obj, dict) or not isinstance(obj.get("cases"), list):
        return [emit("ERROR", "EV1", f, 0, "evals JSON requires an object with cases: []")]
    cases = obj["cases"]
    if len(cases) < 3:
        results.append(emit("ERROR", "EV2", f, 0, "at least 3 realistic test cases required; found %d" % len(cases)))
    if not any(isinstance(c, dict) and c.get("should_trigger") is False for c in cases):
        results.append(emit("ERROR", "EV3", f, 0, "add a negative prompt (should_trigger: false)"))
    if not any(isinstance(c, dict) and c.get("should_trigger") is True for c in cases):
        results.append(emit("ERROR", "EV3", f, 0, "add a positive prompt (should_trigger: true)"))
    ids = set()
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            results.append(emit("ERROR", "EV4", f, 0, "case %d must be an object" % (i + 1)))
            continue
        ident = case.get("id")
        if not isinstance(ident, str) or not ident:
            results.append(emit("ERROR", "EV4", f, 0, "case %d missing string id" % (i + 1)))
        elif ident in ids:
            results.append(emit("ERROR", "EV4", f, 0, "duplicate case id '%s'" % ident))
        ids.add(ident)
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            results.append(emit("ERROR", "EV4", f, 0, "case %d missing prompt" % (i + 1)))
        if not isinstance(case.get("should_trigger"), bool):
            results.append(emit("ERROR", "EV4", f, 0, "case %d should_trigger must be boolean" % (i + 1)))
        if not isinstance(case.get("expected_behaviors"), list) or not case["expected_behaviors"] or not all(isinstance(x, str) and x.strip() for x in case["expected_behaviors"]):
            results.append(emit("ERROR", "EV4", f, 0, "case %d requires at least one nonempty expected_behaviors entry" % (i + 1)))
        fixtures = case.get("fixtures", [])
        if not isinstance(fixtures, list):
            results.append(emit("ERROR", "EV4", f, 0, "case %d fixtures must be a list" % (i + 1)))
        else:
            for relative in fixtures:
                if not isinstance(relative, str):
                    results.append(emit("ERROR", "EV5", f, 0, "fixture path must be string"))
                    continue
                target = folder / relative
                if not valid_resolved_under(target, folder) or not target.is_file():
                    results.append(emit("ERROR", "EV5", f, 0, "missing/outside eval fixture '%s'" % relative))
    if not (folder / "rubric.md").is_file():
        results.append(emit("WARN", "EV6", folder, 0, "rubric.md missing; expected behavior may lack independent grading"))
    return results


def export_skills_dirs(eval_dir: Path) -> list[Path]:
    """Every `skills/` directory an export must never write into: this repo's, the cwd repo's, the one this script is packaged under, and the sibling of the evals root."""
    here = Path(__file__).resolve()
    found = [root / "skills" for root in (repo_root(here), repo_root(Path.cwd())) if root]
    found += [parent for parent in here.parents if parent.name == "skills"]
    if here.parent.name == "scripts" and (here.parent.parent / "SKILL.md").is_file():
        found.append(here.parent.parent)  # a packaged skill copied somewhere that is not called skills/
    found.append(eval_dir.resolve().parent.parent / "skills")
    return found


def export_eval_dirs(eval_dir: Path) -> list[Path]:
    """Every evals root an export must never write into (frozen test data): the root holding this eval, and the evals/ of this repo and of the cwd repo."""
    here = Path(__file__).resolve()
    return [eval_dir.resolve().parent] + [root / "evals" for root in (repo_root(here), repo_root(Path.cwd())) if root]


def export_fixture_check(eval_dir: Path, relative: str) -> tuple[str, str]:
    """(EX code, why) a fixture path from cases.json must not be exported, or ("", "") when it may be. Reads names and link/cloud metadata (lstat) only: it never opens,
    stats-through or follows the fixture itself, so a secret, a cloud placeholder or a link target is not touched before the answer (RK15)."""
    posix = relative.replace("\\", "/")
    parts = [x for x in posix.split("/")]
    if not posix or posix.startswith("/") or ":" in posix or any(x in ("", ".", "..") for x in parts):  # ':' also covers drive letters and NTFS streams (a.csv:hid)
        return "EX4", "unsafe fixture path '%s' (must be a plain relative path inside the eval folder, without ':')" % relative
    for part in parts:
        bad_name = unsafe_windows_name(part)
        if bad_name:
            return WIN_NAME_CODES[bad_name.split(":", 1)[0]], "fixture '%s' has a Windows-dangerous name (%s); refusing to copy it" % (relative, bad_name.split(": ", 1)[1])
    for part in parts:
        if secret_file_name(part):
            return "EX4", "fixture '%s' has a secret or credential name ('%s': .env*, *.credentials.json, auth.json, *.pem, *.key, secrets.json...); refusing to copy it" % (relative, part)
        if zone_named(part):
            return "EX4", "fixture '%s' sits in a folder named like a secret or cloud-synced zone ('%s'); refusing to copy it" % (relative, part)
    if zone_reason(eval_dir / relative):
        return "EX4", "fixture '%s' is inside a secret or cloud-synced folder; refusing to copy it" % relative
    current = eval_dir
    for part in parts:
        current = current / part
        if is_link(current):
            return "EX4", "fixture '%s' goes through a symlink or junction; refusing to copy it" % relative
        if path_is_cloud(current):
            return "EX4", "fixture '%s' is a cloud placeholder; refusing to copy it" % relative
    if zone_reason(Path(os.path.realpath(current.parent)) / parts[-1]):
        return "EX4", "fixture '%s' resolves into a secret or cloud-synced folder; refusing to copy it" % relative
    try:
        info = os.lstat(current)
    except OSError:
        return "", ""  # missing: reported by the caller
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        return "EX4", "fixture '%s' is a hard link (%d names for one file); refusing to copy it" % (relative, info.st_nlink)
    return "", ""


def export_fixture_refusal(eval_dir: Path, relative: str) -> str:
    """The message of export_fixture_check, or "" when the fixture may be exported."""
    return export_fixture_check(eval_dir, relative)[1]


def export_eval_check(eval_dir: Path) -> tuple[str, str]:
    """The first reason any fixture named in cases.json is refused (export_fixture_refusal), checked BEFORE check_evals stats a single fixture. An eval folder
    inside a secret or cloud-synced zone is refused without reading cases.json. Unreadable or malformed JSON gives "" so that check_evals reports it (EV1)."""
    if zone_reason(eval_dir):
        return "EX4", "eval folder is inside a secret or cloud-synced folder; refusing to read or export it"
    try:
        cases = json.loads((eval_dir / "cases.json").read_text(encoding="utf-8"))["cases"]
        listed = [c["fixtures"] for c in cases if isinstance(c, dict) and isinstance(c.get("fixtures"), list)]
    except (ValueError, OSError, KeyError, TypeError):
        return "", ""
    for relative in (x for fixtures in listed for x in fixtures if isinstance(x, str)):
        found = export_fixture_check(eval_dir, relative)
        if found[1]:
            return found
    return "", ""


def export_eval_refusal(eval_dir: Path) -> str:
    """The message of export_eval_check, or "" when no fixture is refused."""
    return export_eval_check(eval_dir)[1]


def export_fixture_source(eval_dir: Path, relative: str) -> tuple[Path | None, list[str], str]:
    """Resolve a fixture path from cases.json to (source, export-name parts, problem). Only plain relative paths inside eval_dir, no links,
    no secret/credential names, nothing in a secret or cloud-synced zone (export_fixture_refusal)."""
    problem = export_fixture_check(eval_dir, relative)[1]
    if problem:
        return None, [], problem
    parts = relative.replace("\\", "/").split("/")
    current = eval_dir.joinpath(*parts)
    if not current.is_file() or not valid_resolved_under(current, eval_dir):
        return None, [], "missing/outside eval fixture '%s'" % relative
    return current, (parts[1:] if parts[0] == "fixtures" and len(parts) > 1 else parts), ""


def export_agentskills(eval_dir: Path, skill_name: str, out_root: Path, force: bool = False) -> tuple[int, list[dict], dict]:
    """Write <out_root>/<skill_name>/evals/evals.json (agentskills schema, SPEC 9.6) plus evals/files/ from evals/<skill>/cases.json.

    Returns (exit code, findings, {"exported", "excluded_negative", "path"}). 2 = destination under skills/ or an evals root (EX1);
    1 = refused before any write (EV*, EX2-EX7, EX9-EX12; EX4 also covers a fixture with a secret/credential name, in a secret or cloud-synced zone, behind a link or a hard link, decided from names and lstat before any fixture is opened or stat-ed) or a write error (EX8; EX13 = a source changed between check and copy; EX6 also covers a parent swapped for a link after mkdir). On EX8 the files this run created are removed again (empty folders may remain);
    a file replaced under --force is not restored. Only the positive cases (should_trigger true) are exported; nothing else is deleted,
    and --force only overwrites the files this function generates."""
    eval_dir, out_root = Path(eval_dir), Path(out_root)
    stats = {"exported": 0, "excluded_negative": 0, "path": ""}

    def refuse(code: int, ident: str, message: str, path: Path = eval_dir):
        return code, [emit("ERROR", ident, path, 0, message)], stats

    dest = out_root / skill_name
    if any(valid_resolved_under(dest, skills) for skills in export_skills_dirs(eval_dir)):
        return refuse(2, "EX1", "export destination must not be under skills/ (it would ship test data inside the skill): %s" % out_root, out_root)
    if any(valid_resolved_under(dest, frozen) for frozen in export_eval_dirs(eval_dir)):
        return refuse(2, "EX1", "export destination must not be under evals/ (frozen test data; the export would change the eval it came from): %s" % out_root, out_root)
    if not EXPORT_NAME_RE.match(skill_name or ""):
        return refuse(1, "EX2", "skill name '%s' is not a plain lowercase-hyphen name" % skill_name)
    ident, problem = export_eval_check(eval_dir)  # names, zones and links first: check_evals below stats every fixture
    if problem:
        return refuse(1, ident, problem, eval_dir / "cases.json")
    problems = [x for x in check_evals(eval_dir) if x["level"] == "ERROR"]
    if problems:
        return 1, problems, stats
    try:
        data = json.loads((eval_dir / "cases.json").read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return refuse(1, "EV1", "cannot read evals JSON: %s" % exc, eval_dir / "cases.json")
    cases = data["cases"]
    if data.get("status") == "draft" or any("STUDIO-DRAFT" in "%s %s" % (c.get("prompt", ""), " ".join(map(str, c.get("expected_behaviors", [])))) for c in cases):
        return refuse(1, "EX3", "eval is still a draft (status 'draft' or STUDIO-DRAFT text); write real cases before exporting", eval_dir / "cases.json")
    positive = [c for c in cases if c["should_trigger"]]
    sources: dict[str, tuple[str, Path]] = {}  # NFC-casefolded name -> (name as exported: NFC, case kept; source file)
    checked: dict[Path, os.stat_result] = {}  # source -> lstat taken when it was checked; the copy re-proves this identity on the open handle
    evals = []
    for number, case in enumerate(positive, 1):
        names = []
        for relative in case.get("fixtures", []):
            source, parts, problem = export_fixture_source(eval_dir, relative)
            if source is None:
                return refuse(1, "EX4", problem, eval_dir / "cases.json")
            try:
                checked.setdefault(source, os.lstat(source))
            except OSError as exc:
                return refuse(1, "EX4", "cannot inspect fixture '%s': %s" % (relative, exc), eval_dir / "cases.json")
            name = unicodedata.normalize("NFC", "/".join(parts))  # written to disk and to evals.json as NFC, case kept (Data.csv stays Data.csv)
            key = name.casefold()  # a.csv and A.csv are one file on Windows/macOS disks; the key is only for the collision check
            seen = sources.get(key)
            if seen and (seen[0] != name or seen[1] != source):
                return refuse(1, "EX7", "fixture names collide after export (compared ignoring case and Unicode form): '%s' is %s but '%s' is %s" % (seen[0], seen[1], name, source), eval_dir / "cases.json")
            sources[key] = (name, source)
            names.append("evals/files/" + name)
        evals.append({"id": number, "prompt": case["prompt"], "expected_output": "; ".join(case["expected_behaviors"]), "files": names, "assertions": list(case["expected_behaviors"])})
    for key in sources:
        for other in sources:
            if other.startswith(key + "/"):
                return refuse(1, "EX12", "fixture '%s' is a file but '%s' needs it as a folder; rename one of them" % (sources[key][0], sources[other][0]), eval_dir / "cases.json")
    evals_dir = dest / "evals"
    target = evals_dir / "evals.json"
    copies = {evals_dir / "files" / Path(*name.split("/")): source for name, source in sources.values()}
    for owned in [dest, evals_dir, evals_dir / "files"] + [t.parent for t in copies] + [target] + list(copies):
        if is_link(owned):
            return refuse(1, "EX6", "export destination goes through a symlink or junction: %s" % owned, owned)
    for t, source in copies.items():
        if t.exists() and source.exists() and os.path.samefile(t, source):
            return refuse(1, "EX6", "export destination is the source fixture itself: %s" % t, t)
    clash = [x for x in [target] + list(copies) if x.exists()]
    if clash and not force:
        return refuse(1, "EX5", "export file exists: %s; choose another --out or explicitly --force" % clash[0], clash[0])
    fresh = [x for x in [target] + list(copies) if not x.exists()]
    temp_name = ""
    try:
        for t, source in copies.items():
            t.parent.mkdir(parents=True, exist_ok=True)
            linked = link_in_chain(t.parent, dest)  # a parent swapped for a junction after the check above would redirect the write
            if linked:
                raise UnsafeOpen("export destination goes through a symlink or junction: %s" % linked, "EX6")
            if t.exists():  # only reachable with --force: replace the file, never write through it
                t.unlink()
            with open_nofollow_read(source, checked[source]) as reader, create_exclusive(t) as writer:
                shutil.copyfileobj(reader, writer)
        evals_dir.mkdir(parents=True, exist_ok=True)
        linked = link_in_chain(evals_dir, dest)
        if linked:
            raise UnsafeOpen("export destination goes through a symlink or junction: %s" % linked, "EX6")
        handle, temp_name = tempfile.mkstemp(prefix=".evals-", suffix=".tmp", dir=str(evals_dir))  # same folder, so os.replace is atomic
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps({"skill_name": skill_name, "evals": evals}, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp_name, target)
        temp_name = ""
    except OSError as exc:
        for leftover in fresh + ([Path(temp_name)] if temp_name else []):  # a half-written export must not look like a finished one
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(exc, UnsafeOpen):
            return refuse(1, exc.code, "%s (files created by this run were removed)" % exc, out_root)
        return refuse(1, "EX8", "cannot write export: %s (files created by this run were removed)" % exc, out_root)
    stats.update({"exported": len(evals), "excluded_negative": len(cases) - len(positive), "path": str(target)})
    return 0, [], stats


def frontmatter_extra_len(lines: list, body_start: int) -> int:
    """Characters of the frontmatter outside the `description` key (the key's own lines are skipped)."""
    total, in_description = 0, False
    for raw in lines[1:max(body_start - 1, 1)]:
        if raw and not raw[0].isspace():
            in_description = raw.startswith("description:")
        if not in_description:
            total += len(raw) + 1
    return total


def estimate_tokens(body: str) -> int:
    """Rough estimate: chars / 4; Vietnamese bodies tokenize about 1.2-2x worse (lower bound used). Not a tokenizer."""
    letters = [c for c in body.lower() if c.isalpha()]
    vietnamese = bool(letters) and sum(c in VI_CHARS for c in letters) / len(letters) > 0.1
    return int(len(body) / 4 * (1.2 if vietnamese else 1))


def lint_forcing_words(body: str, body_start: int, manifest: Path) -> list:
    """SK-14 / CT10: an all-caps MUST/NEVER/ALWAYS/CRITICAL line needs a reason on the same line.
    Not prose, so skipped: fenced code (a fence closes only on the same character and at least the opening length),
    indented code blocks (after a blank line, outside lists), table rows, inline code, link text, URLs, one-line HTML
    comments, and <!-- studio:strict --> ... <!-- /studio:strict --> blocks. A strict block left open is itself a CT10."""
    findings: list[dict] = []
    fence, strict, strict_line = None, False, 0
    prev_blank, in_indented, list_context = True, False, False
    for offset, line in enumerate(body.splitlines()):
        text = unicodedata.normalize("NFC", line)
        stripped = text.strip()
        lineno = body_start + offset + 1
        if fence:
            if re.fullmatch(re.escape(fence[0]) + "{%d,}" % len(fence), stripped):
                fence = None
            continue
        opened = (FENCE_OPEN_LIST_RE if list_context else FENCE_OPEN_RE).match(text)
        if opened:
            fence = opened.group(1)
            prev_blank = False
            continue
        if STRICT_OPEN in text:
            strict, strict_line = True, lineno
        if strict:
            if STRICT_CLOSE in text:
                strict = False
            continue
        if not stripped:
            prev_blank = True
            continue
        indented = text.startswith(("    ", "\t"))
        if indented and (in_indented or (prev_blank and not list_context)):
            in_indented, prev_blank = True, False
            continue
        in_indented = False
        if not indented:
            list_context = bool(LIST_ITEM_RE.match(text))
        prev_blank = False
        if stripped.startswith("|"):
            continue
        prose = strip_html_comments(text)
        prose = strip_code_spans(prose)
        prose = MD_LINK_RE.sub(" ", prose)
        prose = URL_RE.sub(" ", prose)
        match = FORCE_RE.search(prose)
        if match and not REASON_RE.search(prose):
            findings.append(emit("WARN", "CT10", manifest, lineno,
                                 "'%s' without a reason on the same line (SK-14); state why, or mark a deliberately strict step with %s ... %s"
                                 % (match.group(1), STRICT_OPEN, STRICT_CLOSE)))
    if strict:
        findings.append(emit("WARN", "CT10", manifest, strict_line,
                             "strict block not closed: %s has no matching %s, so the rest of the body was not linted (SK-14)"
                             % (STRICT_OPEN, STRICT_CLOSE)))
    return findings


def lint_unclosed_comment(body: str, body_start: int, manifest: Path) -> list:
    """CT11: a `<!--` outside code that no `-->` ever closes hides the rest of the body from the language and forcing-word lints."""
    fence, list_context, opened_at = None, False, 0
    for offset, line in enumerate(body.splitlines()):
        text = unicodedata.normalize("NFC", line)
        if fence:
            if re.fullmatch(re.escape(fence[0]) + "{%d,}" % len(fence), text.strip()):
                fence = None
            continue
        if opened_at:
            closed = text.find("-->")
            if closed < 0:
                continue
            text, opened_at = text[closed + 3:], 0
        opened = (FENCE_OPEN_LIST_RE if list_context else FENCE_OPEN_RE).match(text)
        if opened:
            fence = opened.group(1)
            continue
        if text.strip() and not text.startswith(("    ", "\t")):
            list_context = bool(LIST_ITEM_RE.match(text))
        rest = strip_html_comments(strip_code_spans(text))
        if "<!--" in rest:
            opened_at = body_start + offset + 1
    if opened_at:
        return [emit("WARN", "CT11", manifest, opened_at, "HTML comment opened here is never closed with '-->'; the rest of the body is read as comment text (language and SK-14 lints skip it)")]
    return []


def prose_lines(body: str) -> list[tuple[int, str]]:
    """Prose lines of a Markdown body as (1-based line number inside `body`, text); file line = body_start + number.
    Left out: blank lines, fenced and indented code, table rows, lines marked <!-- studio:vi-ok -->, and the lines of a
    multi-line HTML comment. In the text, inline code, link targets, URLs and HTML comments are blanked; the text is not
    normalized, so VI1 can see NFD."""
    found: list[tuple[int, str]] = []
    fence, prev_blank, in_indented, list_context, in_comment = None, True, False, False, False
    for offset, text in enumerate(body.splitlines()):
        stripped = text.strip()
        if fence:
            if re.fullmatch(re.escape(fence[0]) + "{%d,}" % len(fence), stripped):
                fence = None
            continue
        if in_comment:
            closed = text.find("-->")
            if closed < 0:
                continue
            text, in_comment = text[closed + 3:], False
            stripped = text.strip()
        opened = (FENCE_OPEN_LIST_RE if list_context else FENCE_OPEN_RE).match(text)
        if opened:
            fence, prev_blank = opened.group(1), False
            continue
        if not stripped:
            prev_blank = True
            continue
        indented = text.startswith(("    ", "\t"))
        if indented and (in_indented or (prev_blank and not list_context)):
            in_indented, prev_blank = True, False
            continue
        in_indented = False
        if not indented:
            list_context = bool(LIST_ITEM_RE.match(text))
        prev_blank = False
        if stripped.startswith("|") or VI_OK_MARK in text:
            continue
        prose = strip_html_comments(text)
        prose = strip_code_spans(prose)
        if "<!--" in prose:  # a comment that continues on the next lines
            prose, in_comment = prose[:prose.index("<!--")], True
        prose = MD_LINK_RE.sub(r"\1", prose)
        prose = URL_RE.sub(" ", prose)
        if prose.strip():
            found.append((offset + 1, prose))
    return found


def _vi_counts(text: str) -> tuple[int, int]:
    """(letters, letters with a Vietnamese diacritic), counted on the NFC form so an NFD body is still recognised."""
    letters = [c for c in unicodedata.normalize("NFC", text).lower() if c.isalpha()]
    return len(letters), sum(c in VI_CHARS for c in letters)


def _vi_lang(lines: list[tuple[int, str]]) -> str:
    letters = accents = 0
    for _, text in lines:
        count, accented = _vi_counts(text)
        letters, accents = letters + count, accents + accented
    return "vi" if letters and accents / letters >= VI_ACCENT_RATIO else "en"


def detect_lang(body: str) -> str:
    """'vi' when letters with a Vietnamese diacritic are at least VI_ACCENT_RATIO of the prose letters, else 'en'
    (code, table rows, inline code, vi-ok lines and the frontmatter do not count)."""
    return _vi_lang(prose_lines(body))


def _vi_sentences(lines: list[tuple[int, str]]) -> list[tuple[int, int]]:
    """(line where the sentence starts, word count). A sentence ends at . ! ? or ; followed by a space, and a list item,
    heading or blank line also ends one, so 'v1.0', '3.5', 'e.g.' and paths are not split. A word is a whitespace-separated token."""
    sentences: list[tuple[int, int]] = []
    buf: list[tuple[int, str]] = []

    def flush() -> None:
        if not buf:
            return
        starts, pos, parts = [], 0, []
        for rel, text in buf:
            starts.append((pos, rel))
            parts.append(text)
            pos += len(text) + 1
        joined = SENTENCE_ABBREV_RE.sub(lambda m: m.group(1) + "․", " ".join(parts))
        offsets = [at for at, _ in starts]
        start = 0
        for cut in list(SENTENCE_SPLIT_RE.finditer(joined)) + [None]:
            end = cut.start() if cut else len(joined)
            if joined[start:end].split():
                sentences.append((starts[bisect.bisect_right(offsets, start) - 1][1], len(joined[start:end].split())))
            if cut:
                start = cut.end()
        buf.clear()

    prev = -1
    for rel, text in lines:
        item = bool(LIST_ITEM_RE.match(text))
        heading = text.lstrip().startswith("#")
        if buf and (rel != prev + 1 or item or heading):
            flush()
        buf.append((rel, re.sub(r"^\s*(#+|>+|[-*+]|\d+[.)])\s+", "", text.strip())))
        prev = rel
        if heading:
            flush()
    flush()
    return sentences


def lint_vietnamese(meta: dict, body: str, body_start: int, manifest: Path, front_lines: list | None = None) -> list:
    """FR16 / SPEC 9.10: VI1-VI5, all WARN, only when the body is Vietnamese (detect_lang). Line numbers are file lines.
    VI1 body not NFC (first deviating line) · VI2 d/m/yyyy date · VI3 sentence over VI_SENTENCE_MAX words ·
    VI4 frontmatter outside `description` holds Vietnamese letters, or `description` does but has no 'Use when' ·
    VI5 a '## ' section of at least VI5_SECTION_MIN_LETTERS letters with under VI5_ACCENT_MIN diacritics."""
    lines = prose_lines(body)
    if _vi_lang(lines) != "vi":
        return []
    findings: list[dict] = []
    for rel, text in lines:
        if unicodedata.normalize("NFC", text) != text:
            findings.append(emit("WARN", "VI1", manifest, body_start + rel,
                                 "body is not Unicode NFC (first deviating line; later lines may be too); re-save the text in NFC (V09)"))
            break
    for rel, text in lines:
        date = NON_ISO_DATE_RE.search(text)
        if date:
            findings.append(emit("WARN", "VI2", manifest, body_start + rel, "date '%s' is not ISO; write yyyy-mm-dd (V11)" % date.group(0)))
    for rel, words in _vi_sentences(lines):
        if words > VI_SENTENCE_MAX:
            findings.append(emit("WARN", "VI3", manifest, body_start + rel,
                                 "sentence has %d words (>%d); split it, aim for 25 or fewer (V03)" % (words, VI_SENTENCE_MAX)))
    if front_lines is not None:
        front = list(front_lines)
    else:
        try:
            front = manifest.read_text(encoding="utf-8").splitlines()[:body_start]
        except (OSError, UnicodeError):
            front = []
    first_line: dict = {}  # top-level key -> its frontmatter line; nested[parent][key] -> the line under that parent (built once, a scan per key was quadratic)
    nested: dict = {}
    parent = None
    for number, raw in enumerate(front, 1):
        stripped = raw.lstrip()
        colon = stripped.find(":")
        if colon <= 0:
            continue
        key = stripped[:colon]
        if raw[:1] not in (" ", "\t"):
            first_line.setdefault(key, number)
            parent = key
        elif parent is not None:
            nested.setdefault(parent, {}).setdefault(key, number)

    def front_line(label: str, default: int) -> int:
        parts = label.split("[")[0].split(".")
        if len(parts) > 1:  # metadata.k: look under metadata:, not at a root key of the same name
            return nested.get(parts[0], {}).get(parts[-1], first_line.get(parts[0], default))
        return first_line.get(parts[0], default)

    def accented(value) -> bool:
        return isinstance(value, str) and _vi_counts(strip_html_comments(value))[1] > 0

    def strings(label: str, value) -> list[tuple[str, str]]:
        """Every string inside a frontmatter value (nested dicts and lists), labelled by its path."""
        if isinstance(value, dict):
            return [pair for k, v in value.items() for pair in strings("%s.%s" % (label, k), v)]
        if isinstance(value, (list, tuple)):
            return [pair for i, v in enumerate(value) for pair in strings("%s[%d]" % (label, i), v)]
        return [(label, value)] if isinstance(value, str) else []

    pairs = [pair for key, value in meta.items() if key != "description" for pair in strings(key, value)]
    for label, value in pairs:
        at = front_line(label.split("[")[0], 2)
        if accented(value) and not (at <= len(front) and VI_OK_MARK in front[at - 1]):
            findings.append(emit("WARN", "VI4", manifest, at, "frontmatter '%s' has Vietnamese letters; keep frontmatter values English (V13)" % label))
    desc = strip_html_comments(meta["description"]) if isinstance(meta.get("description"), str) else None
    at = front_line("description", 3)
    if accented(desc) and not VI_TRIGGER_RE.search(desc) and not (at <= len(front) and VI_OK_MARK in front[at - 1]):
        findings.append(emit("WARN", "VI4", manifest, at,
                             "description has Vietnamese letters but no 'Use when' trigger phrase; write it in English and add Vietnamese only as extra trigger words (V13)"))
    section = None
    for rel, text in lines + [(0, "# end")]:
        if re.match(r"^#{1,2}\s+\S", text):
            if section and section[1] >= VI5_SECTION_MIN_LETTERS and section[2] / section[1] < VI5_ACCENT_MIN:
                findings.append(emit("WARN", "VI5", manifest, body_start + section[0],
                                     "section '%s' has %d letters and almost no Vietnamese diacritics; one language per skill, write it in Vietnamese (V14)"
                                     % (section[3], section[1])))
            section = [rel, 0, 0, text.strip("# ").strip()] if re.match(r"^##\s", text) else None
        elif section:
            count, with_accent = _vi_counts(text)
            section[1], section[2] = section[1] + count, section[2] + with_accent
    return findings


def lint_contents(path: Path, lines: list, kind: str, offset: int = 0) -> list:
    """FR15: Contents rules. kind 'reference' -> ST5, 'skill_body' -> ST7; `offset` = lines before lines[0]."""
    code = "ST5" if kind == "reference" else "ST7"
    limit = REF_TOC_LINES if kind == "reference" else BODY_TOC_LINES
    findings: list[dict] = []
    norm = [unicodedata.normalize("NFC", x) for x in lines]
    start = next((i for i, x in enumerate(norm[:CONTENTS_WINDOW]) if CONTENTS_RE.match(x.strip())), None)
    if start is None:
        if len(lines) > limit:
            level = "ERROR" if kind == "reference" else "WARN"
            what = "reference" if kind == "reference" else "SKILL.md body"
            findings.append(emit(level, code, path, offset + 1, "%s >%d lines needs a '## Contents' (or '## Mục lục') in its first %d lines" % (what, limit, CONTENTS_WINDOW)))
        return findings
    headings, fence = set(), None
    for i, x in enumerate(norm):
        s = x.strip()
        if fence:
            if s.startswith(fence):
                fence = None
            continue
        if s.startswith(("```", "~~~")):
            fence = s[:3]
        elif i != start and re.match(r"^##\s+\S", x):
            headings.add(x[2:].strip())
    entries = []
    for i in range(start + 1, len(norm)):
        s = norm[i].strip()
        if s.startswith("#"):
            break
        if s.startswith(("- ", "* ")):
            entries.append((i, MD_LINK_RE.sub(r"\1", s[2:]).split(" — ")[0].strip()))
    if len(entries) > CONTENTS_MAX:
        findings.append(emit("WARN", code, path, offset + start + 1, "Contents has %d entries; keep it to %d or fewer" % (len(entries), CONTENTS_MAX)))
    for i, name in entries:
        if name not in headings:
            findings.append(emit("WARN", code, path, offset + i + 1, "Contents entry '%s' matches no '## ' heading in this file" % name))
    return findings


def validate_skill(folder: Path, eval_root: Path | None = None, require_evals: bool = False, target: str = "portable",
                   profile: str = "portable", allow_links_under: Path | None = None, max_file_bytes: int | None = None,
                   skip_markers: tuple = ()) -> list[dict]:
    """Findings for one skill. profile "opcos" (doctor): an existing link that leaves the skill but stays under `allow_links_under`
    is a WARN ST6, the OPCOS_PROVENANCE_KEYS are WARN FM4, and no `metadata.opcos_*` key is a NOTE MD1. ST3 and ST8 apply to every profile.
    `max_file_bytes` (doctor passes DOCTOR_MAX_FILE_BYTES): a SKILL.md or reference above it is not read, WARN SZ1. `skip_markers` extend CLOUD_MARKERS.
    A symlink, junction or cloud placeholder inside the skill is reported (SEC, SZ2) and never opened, listed or followed."""
    folder = folder.resolve()
    manifest = folder / "SKILL.md"
    if not manifest.is_file():
        return [emit("ERROR", "FM1", manifest, 0, "SKILL.md is missing")]
    markers = CLOUD_MARKERS + tuple(skip_markers)
    try:
        text, too_big = read_capped(manifest, max_file_bytes)
    except UnicodeError:
        return [emit("ERROR", "FM1", manifest, 0, "SKILL.md must be UTF-8 text")]
    if too_big:
        return [emit("WARN", "SZ1", manifest, 0, "SKILL.md is larger than %d bytes; not read or linted" % max_file_bytes)]
    claude = target == "claude-code"
    meta, findings, body_start = parse_frontmatter(text, manifest, CLAUDE_CODE_KEYS if claude else frozenset())
    all_lines = text.splitlines()
    name = meta.get("name")
    desc = meta.get("description")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or len(name) > 64:
        findings.append(emit("ERROR", "FM2", manifest, 2, "name must be lowercase kebab-case, 1–64 chars and without '--'"))
    elif name != folder.name:
        findings.append(emit("ERROR", "FM2", manifest, 2, "name '%s' differs from folder '%s'" % (name, folder.name)))
    if isinstance(name, str):
        word = next((w for w in RESERVED_NAME_WORDS if w in name), None)
        if word:
            findings.append(emit("ERROR", "FM5", manifest, 2, "name must not contain the reserved word '%s'" % word))
        elif claude and name in CLAUDE_CODE_RESERVED_NAMES:
            findings.append(emit("ERROR", "FM5", manifest, 2, "name '%s' is reserved by Claude Code" % name))
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 1024 or has_xml_tag(desc or ""):
        findings.append(emit("ERROR", "DS1", manifest, 3, "description must be a nonempty string <=1024 chars without XML tags"))
    elif not re.search(r"(?i)\b(use when|when to use|used when|for tasks involving)\b", desc):
        findings.append(emit("WARN", "DS3", manifest, 3, "description should describe when to invoke the Skill, e.g. 'Use when ...'"))
    elif re.match(r"(?i)^\s*(i can|you can|i will|we can)\b", desc):
        findings.append(emit("WARN", "DS2", manifest, 3, "prefer third-person description e.g. 'Validates CSV...'"))
    if isinstance(desc, str):
        trigger = TRIGGER_RE.search(desc)
        if trigger and trigger.start() >= TRIGGER_LATEST:
            findings.append(emit("WARN", "DS4", manifest, 3, "trigger phrase starts at character %d; put 'Use when ...' inside the first %d characters" % (trigger.start() + 1, TRIGGER_LATEST)))
        listing = len(desc) + (len(meta["when_to_use"]) if isinstance(meta.get("when_to_use"), str) else 0)
        if claude and listing > LISTING_MAX:
            findings.append(emit("WARN", "DS5", manifest, 3, "description + when_to_use is %d chars; Claude Code truncates the skill listing at %d" % (listing, LISTING_MAX)))
    allowed = sorted(PORTABLE_KEYS | CLAUDE_CODE_KEYS) if claude else sorted(PORTABLE_KEYS)
    for key in meta:
        if key in PORTABLE_KEYS:
            continue
        at = next((i + 1 for i, x in enumerate(all_lines[:body_start]) if x.startswith(key + ":")), 2)
        if claude and key in CLAUDE_CODE_KEYS:
            findings.append(emit("WARN", "FM6", manifest, at, "frontmatter key '%s' is Claude Code only; claude.ai and the API reject it with a hard error" % key))
        elif profile == "opcos" and key in OPCOS_PROVENANCE_KEYS:
            findings.append(emit("WARN", "FM4", manifest, at, "provenance key '%s' is an OpcOS convention, not portable; move it under metadata before publishing" % key))
        else:
            findings.append(emit("ERROR", "FM4", manifest, at, "unknown frontmatter key '%s' for target %s; allowed keys: %s; use metadata or a target adapter" % (key, target, ", ".join(allowed))))
    if profile == "opcos" and not (isinstance(meta.get("metadata"), dict) and any(k.startswith("opcos_") for k in meta["metadata"])):
        findings.append(emit("NOTE", "MD1", manifest, 2, "no metadata.opcos_* key; OpcOS registry fields are optional"))
    extra = frontmatter_extra_len(all_lines, body_start)
    if extra > FRONTMATTER_EXTRA_MAX:
        findings.append(emit("WARN", "FM8", manifest, 1, "frontmatter outside description is %d chars (>%d); move detail to the body or references" % (extra, FRONTMATTER_EXTRA_MAX)))
    if "metadata" in meta and (not isinstance(meta["metadata"], dict) or any(not isinstance(v, str) for v in meta["metadata"].values())):
        findings.append(emit("ERROR", "FM4", manifest, 0, "metadata must be a mapping of string keys to string values"))
    if "compatibility" in meta and len(str(meta["compatibility"])) > 500:
        findings.append(emit("ERROR", "FM4", manifest, 0, "compatibility max length is 500 chars"))
    body = "\n".join(all_lines[body_start:])
    if len(body.splitlines()) >= 500:
        findings.append(emit("WARN", "ST1", manifest, body_start + 1, "Skill body should be under 500 lines (best-practice, not spec hard limit)"))
    body_bytes = len(body.encode("utf-8"))
    if body_bytes > CODEX_BODY_MAX_BYTES:
        findings.append(emit("WARN", "ST3", manifest, body_start + 1, "Skill body is %d bytes (>%d, the Codex 0.147 limit); move detail to references (standards/SOURCE_TRACEABILITY.md A16)" % (body_bytes, CODEX_BODY_MAX_BYTES)))
    tokens = estimate_tokens(body)
    if tokens > BODY_TOKEN_MAX:
        findings.append(emit("WARN", "ST2", manifest, body_start + 1, "Skill body is about %d tokens (estimate, not a tokenizer); keep it under %d and move detail to references" % (tokens, BODY_TOKEN_MAX)))
    findings.extend(lint_forcing_words(body, body_start, manifest))
    findings.extend(lint_unclosed_comment(body, body_start, manifest))
    findings.extend(lint_contents(manifest, body.splitlines(), "skill_body", body_start))
    findings.extend(lint_vietnamese(meta, body, body_start, manifest, all_lines[:body_start]))
    if re.search(r"<!--\s*STUDIO-DRAFT|\[FILL:|\bTODO\b|\bFIXME\b", body, re.IGNORECASE):
        findings.append(emit("WARN", "CT9", manifest, body_start + 1, "draft marker/TODO/FIXME remains; do not ship unreviewed scaffold"))
    if re.search(r"(?i)(show|write out|transcribe|echo)\s+(your\s+)?(private\s+)?(chain.of.thought|internal reasoning|hidden reasoning)", body):
        findings.append(emit("WARN", "NM2", manifest, body_start + 1, "possible request to disclose private model reasoning"))
    refs_linked = set()
    newlines: list | None = None  # offsets of "\n" in the body, built the first time a finding needs a line number
    verdicts: dict = {}  # link text -> (level, message) or (None, resolved path): one check per distinct target

    def line_of(offset: int) -> int:
        nonlocal newlines
        if newlines is None:
            newlines = [m.start() for m in re.finditer("\n", body)]
        return body_start + bisect.bisect_left(newlines, offset) + 1

    def classify(link: str) -> tuple:
        if ABSOLUTE_LINK_RE.match(link) or link.startswith(("/", "\\")):  # UNC, drive, file:, smb:, rooted: never resolved, stat-ed or opened (Windows would authenticate to a share)
            return "ERROR", "reference escapes Skill folder: absolute or UNC link not opened: '%s'" % link
        resolved = folder / link
        if not lexically_inside(resolved, folder) and zone_reason(resolved, markers):  # named outside and in a forbidden zone: do not resolve or stat it
            return "ERROR", "reference escapes Skill folder into a cloud or secret zone (not opened): '%s'" % link
        if link_crosses_link(folder, link):
            return "ERROR", "reference goes through a symlink or junction (not opened): '%s'" % link
        if not valid_resolved_under(resolved, folder):
            if (profile == "opcos" and allow_links_under is not None and not zone_reason(resolved.resolve(), markers)
                    and valid_resolved_under(resolved, allow_links_under) and resolved.exists()):
                return "WARN", "link leaves the Skill folder but stays inside the scanned root: '%s'" % link
            return "ERROR", "reference escapes Skill folder: '%s'" % link
        if not resolved.exists():
            return "ERROR", "missing referenced resource '%s'" % link
        try:
            return None, resolved.resolve()
        except OSError:
            return None, None

    for match in LINK_RE.finditer(body):
        link = match.group(1).strip().strip('<>')
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        link = link.split('#')[0].split('?')[0]
        if not link:
            continue
        if link not in verdicts:
            verdicts[link] = classify(link)
        level, detail = verdicts[link]
        if level:
            findings.append(emit(level, "ST6", manifest, line_of(match.start()), detail))
        elif detail is not None:
            refs_linked.add(detail)
    ref_dir = folder / "references"
    tree, tree_links, tree_dirs, tree_cloud, tree_cut = walk_files(folder, markers)
    if tree_cut:
        findings.append(emit("WARN", "SZ1", folder, 0, "skill lists more than %d files and folders or goes deeper than %d levels; the rest was not listed or checked"
                             % (DOCTOR_MAX_FILES_PER_SKILL, DOCTOR_MAX_SKILL_DEPTH)))
    if ref_dir in tree_dirs:
        for p in (x for x in tree if ref_dir in x.parents and x.name.endswith(".md") and not is_sensitive_name(x.name)):
            if p in tree_cloud:
                continue  # reported as SZ2 below, never opened
            if p not in tree_links and not p.is_file():
                continue
            if p in tree_links:
                findings.append(emit("ERROR", "SEC", p, 0, "symlink in reference tree may escape package; replace with real file"))
                continue
            if p.resolve() not in refs_linked:
                findings.append(emit("WARN", "ST4", p, 0, "reference Markdown is not directly linked from SKILL.md"))
            try:
                ref_text, ref_too_big = read_capped(p, max_file_bytes)
            except UnicodeError:
                findings.append(emit("ERROR", "ST6", p, 0, "reference must be UTF-8"))
                continue
            if ref_too_big:
                findings.append(emit("WARN", "SZ1", p, 0, "reference is larger than %d bytes; not read or linted" % max_file_bytes))
                continue
            findings.extend(lint_contents(p, ref_text.splitlines(), "reference"))
    scripts = folder / "scripts"
    if scripts in tree_dirs:
        for script in tree:
            if (script.parent == scripts and script not in tree_links and script not in tree_dirs and script not in tree_cloud
                    and script.suffix in {".py", ".sh", ".js", ".ts"} and script.name not in body):
                findings.append(emit("WARN", "SC3", script, 0, "script not mentioned in SKILL.md; document whether to run or read"))
    for p in tree:
        if p in tree_cloud:
            findings.append(emit("WARN", "SZ2", p, 0, "cloud placeholder (OneDrive/SharePoint attributes) inside the skill; not opened or listed"))
        elif p in tree_links:
            findings.append(emit("ERROR", "SEC", p, 0, "symlinks are not portable/safe in distributed skill packages"))
        elif (p.parent == folder and p.name.lower() not in ST8_ALLOWED_DIRS and p.name.lower() not in SKIP_DIRS and not is_sensitive_name(p.name)
              and p in tree_dirs):
            findings.append(emit("WARN", "ST8", p, 0, "folder '%s' is outside references/, scripts/, assets/, agents/ and tests/; move it or drop it from the skill" % p.name))
    if eval_root is None:
        root = repo_root(folder)
        if root is not None:
            eval_root = root / "evals"
    if require_evals:
        if eval_root is None:
            findings.append(emit("ERROR", "EV1", folder, 0, "eval root not found; supply --eval-root or use within Studio repo"))
        else:
            findings.extend(check_evals(eval_root / folder.name))
    return findings


def print_findings(folder: Path, findings: list[dict]) -> None:
    errors = sum(f["level"] == "ERROR" for f in findings)
    warnings = sum(f["level"] == "WARN" for f in findings)
    print("%s: %d errors; %d warnings" % (folder, errors, warnings))
    for item in findings:
        location = item["path"] + ((":%s" % item["line"]) if item["line"] else "")
        print("  %-5s %-4s %s — %s" % (item["level"], item["code"], location, item["message"]))


def get_template(full: bool = False, lang: str = "en") -> Path:
    """Minimal template: the SKILL.md / SKILL.vi.md file. Full template: the skill-template-full directory."""
    root = repo_root(Path(__file__).resolve())
    base = root / "templates" if root is not None else Path(__file__).resolve().parents[1] / "assets"
    if full:
        return base / "skill-template-full"
    return base / "skill-template" / ("SKILL.vi.md" if lang == "vi" else "SKILL.md")


def mirror_diff(src: Path, dst: Path) -> list:
    """Relative paths that are missing from dst, differ in bytes, or exist only in dst (an extra file is drift too)."""
    def files(base: Path) -> dict:
        if not base.is_dir():
            return {}
        return {p.relative_to(base).as_posix(): p for p in base.rglob("*")
                if p.is_file() and "__pycache__" not in p.relative_to(base).parts}
    left, right = files(src), files(dst)
    diff = {rel for rel, p in left.items() if rel not in right or p.read_bytes() != right[rel].read_bytes()}
    return sorted(diff | (set(right) - set(left)))


def user_skill_root(agent: str) -> Path:
    """Per-user skill directory of an agent (FR19.1). Claude Code has none here: use --workspace."""
    if agent == "antigravity":
        return Path.home() / ".gemini" / "config" / "skills"
    if agent == "codex":
        return Path.home() / ".agents" / "skills"
    raise ValueError("--user is not supported for %s; use --workspace" % agent)


def cmd_new(args) -> int:
    name = args.name
    if not NAME_RE.fullmatch(name) or len(name) > 64:
        print("ERROR: name must be lowercase kebab-case <=64 chars", file=sys.stderr)
        return 2
    word = next((w for w in RESERVED_NAME_WORDS if w in name), None)
    if word:
        print("ERROR: name must not contain the reserved word '%s' (FM5)" % word, file=sys.stderr)
        return 2
    if not args.description or len(args.description) > 1024 or "\n" in args.description:
        print("ERROR: --description is required, single line and <=1024 characters", file=sys.stderr)
        return 2
    if args.full and args.lang != "en":
        print("ERROR: full template is English-only; drop --full or use --lang en", file=sys.stderr)
        return 2
    root = repo_root(Path(__file__))
    output = Path(args.output).expanduser() if args.output else (root / "skills" if root else Path.cwd() / "skills")
    target = (output / name).resolve()
    if target.exists():
        print("ERROR: refusing to overwrite existing %s" % target, file=sys.stderr)
        return 1
    template = get_template(args.full, args.lang)
    if not ((template / "SKILL.md") if args.full else template).is_file():
        print("ERROR: bundled template missing at %s" % template, file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.full:
        shutil.copytree(template, target)
    else:
        target.mkdir()
        shutil.copyfile(template, target / "SKILL.md")
    p = target / "SKILL.md"
    content = p.read_text(encoding="utf-8")
    content = re.sub(r"^name: skill-template(-full)?$", lambda _m: "name: " + name, content, count=1, flags=re.MULTILINE)
    escaped = json.dumps(args.description, ensure_ascii=False)
    content = re.sub(r'^description: .*$', "description: " + escaped, content, count=1, flags=re.MULTILINE)
    content = content.replace("# Skill Template", "# " + name.replace("-", " ").title(), 1)
    p.write_text(content, encoding="utf-8")
    # Evals are outside runtime; do not invent test prompts or scores.
    external_eval = Path(args.eval_root).expanduser() if args.eval_root else ((root / "evals") if root else (Path.cwd() / "evals"))
    ef = external_eval / name
    ef.mkdir(parents=True, exist_ok=True)
    (ef / "fixtures").mkdir(exist_ok=True)
    (ef / "baselines").mkdir(exist_ok=True)
    sample = [
        {"id": "%s-typical" % name, "kind": "typical", "should_trigger": True},
        {"id": "%s-edge" % name, "kind": "edge", "should_trigger": True},
        {"id": "%s-negative" % name, "kind": "near-miss", "should_trigger": False},
    ]
    cases = [{**c, "prompt": "STUDIO-DRAFT: replace with a realistic %s prompt" % c["kind"],
              "expected_behaviors": ["STUDIO-DRAFT: replace with observable behavior"], "fixtures": []} for c in sample]
    (ef / "cases.json").write_text(json.dumps({"skill_name": name, "status": "draft", "cases": cases}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ef / "rubric.md").write_text("# %s — evaluation rubric (draft)\n\nDefine actual success criteria, trigger expectations, and failure cases before release.\n" % name, encoding="utf-8")
    (ef / "baselines" / "BASELINE.md").write_text("# Baseline: NOT RUN\n\nRecord fresh-session model/runtime, prompt, outputs, score and evidence after real execution.\n", encoding="utf-8")
    print("Created draft Skill: %s\nExternal evals: %s\nNext: replace STUDIO-DRAFT in the 3 sample eval cases, write real references, then validate." % (target, ef))
    return 0


def find_skills(args):
    root = repo_root(Path(__file__)) or repo_root(Path.cwd())
    if args.all:
        if root is None:
            raise ValueError("--all requires Studio repository; use an explicit Skill path")
        return skill_dirs(root)
    if not args.skill:
        raise ValueError("provide a skill path or --all")
    return [Path(args.skill).expanduser()]


def cmd_check(args, audit: bool = False) -> int:
    try:
        folders = find_skills(args)
    except ValueError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    reports = []
    root = repo_root(Path(__file__))
    external = Path(args.eval_root) if args.eval_root else (root / "evals" if root else None)
    for folder in folders:
        findings = validate_skill(folder, eval_root=external, require_evals=args.require_evals, target=getattr(args, "target", "portable"))
        reports.append({"skill": str(folder), "findings": findings})
    if args.json:
        print(json.dumps({"audit": audit, "reports": reports}, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print_findings(Path(report["skill"]), report["findings"])
        if audit:
            print("\nAUDIT IS READ-ONLY. Semantic review is required for SK-03/04/06/07/08/10/12/14 (SK-14 is only partly machine-checked by CT10); model tests were not run.")
    return 1 if any(f["level"] == "ERROR" for x in reports for f in x["findings"]) else 0


def cmd_evals_export(args, paths: list[Path]) -> int:
    out_root = Path(args.out or EXPORT_DEFAULT_OUT).expanduser()
    reports, worst = [], 0
    for path in paths:
        code, findings, stats = export_agentskills(path, path.name, out_root, force=args.force)
        worst = 2 if code == 2 or worst == 2 else max(worst, code)
        reports.append({"skill": path.name, "exit": code, "findings": findings, "stats": stats})
    if args.json:
        print(json.dumps({"reports": reports, "model_runs_performed": 0}, ensure_ascii=False, indent=2))
        return worst
    for item in reports:
        for f in item["findings"]:
            print("ERROR: %s %s: %s" % (item["skill"], f["code"], f["message"]), file=sys.stderr)
        if item["exit"] == 0:
            stats = item["stats"]
            print("exported %d, excluded %d" % (stats["exported"], stats["excluded_negative"]))
            print("  excluded cases are should_trigger: false; agentskills evals have no negative-case field")
            print("  wrote %s" % stats["path"])
    return worst


def cmd_evals(args) -> int:
    root = repo_root(Path(__file__)) or repo_root(Path.cwd())
    eval_root = Path(args.eval_root) if args.eval_root else (root / "evals" if root else None)
    if eval_root is None:
        print("ERROR: provide --eval-root for non-Studio repository", file=sys.stderr)
        return 2
    if not args.export and (args.out is not None or args.force):
        print("ERROR: --out and --force only apply together with --export agentskills", file=sys.stderr)
        return 2
    if args.all:
        paths = sorted(p for p in eval_root.iterdir() if p.is_dir() and any((p / m).exists() for m in ("cases.json", "rubric.md", "fixtures", "baselines", "expected"))) if eval_root.is_dir() else []
    elif args.skill:
        paths = [eval_root / Path(args.skill).name]
    else:
        print("ERROR: specify --all or skill name", file=sys.stderr)
        return 2
    if args.export:
        return cmd_evals_export(args, paths)
    reports = []
    for path in paths:
        findings = check_evals(path)
        reports.append({"skill": path.name, "findings": findings})
    if args.json:
        print(json.dumps({"reports": reports, "model_runs_performed": 0}, ensure_ascii=False, indent=2))
    else:
        for item in reports:
            print_findings(eval_root / item["skill"], item["findings"])
        print("Schema-only evaluation: NO model sessions were executed.")
    return 1 if any(f["level"] == "ERROR" for x in reports for f in x["findings"]) else 0


def ensure_distributable(folder: Path) -> tuple[list[Path], list[dict]]:
    findings = validate_skill(folder)
    manifest = folder / "SKILL.md"
    if manifest.is_file() and re.search(r"<!--\s*STUDIO-DRAFT", manifest.read_text(encoding="utf-8")):
        findings.append(emit("ERROR", "PACK", manifest, 0, "cannot package an unfinished template: remove draft marker after authoring"))
    files = []
    paths, links, dirs, cloud, cut = walk_files(folder, skip_names=SKIP_DIRS)  # no rglob: links and cloud placeholders are listed, never entered or opened
    if cut:
        findings.append(emit("ERROR", "PACK", folder, 0, "skill tree is over the scan limit (%d entries or %d folder levels); nothing is packaged short, trim the tree"
                             % (DOCTOR_MAX_FILES_PER_SKILL, DOCTOR_MAX_SKILL_DEPTH)))
    for p in paths:
        if p in cloud:
            findings.append(emit("ERROR", "PACK", p, 0, "cloud placeholder; not read, not packaged"))
        elif p in links:
            findings.append(emit("ERROR", "PACK", p, 0, "symlink or junction; not followed, not packaged"))
        elif p in dirs:
            if zone_named(p.name):
                findings.append(emit("ERROR", "PACK", p, 0, "folder named like a cloud/secret zone; not entered, not packaged"))
        else:
            files.append(p)
    kept = []
    for p in files:
        if p.name in REJECT_NAMES or p.name.startswith(".env.") or p.suffix.lower() in REJECT_SUFFIXES:
            findings.append(emit("ERROR", "SEC", p, 0, "secret/credential-like file must not be shipped"))
            continue
        try:
            info = os.lstat(p)
        except OSError as exc:
            findings.append(emit("ERROR", "PACK", p, 0, "cannot stat: %s" % (exc.strerror or type(exc).__name__)))
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        if info.st_size > 25 * 1024 * 1024:
            findings.append(emit("ERROR", "PACK", p, 0, "file exceeds 25 MB; review before shipping"))
            continue
        if p.suffix.lower() in {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".sh"}:
            try:
                with open_nofollow_read(p, info) as handle:
                    raw = handle.read().decode("utf-8")
            except UnsafeOpen as exc:
                findings.append(emit("ERROR", "PACK", p, 0, "not packaged: %s" % exc))
                continue
            except (OSError, UnicodeError):
                raw = ""
            if ("-----BEGIN " + "PRIVATE KEY-----") in raw or re.search(r"\b(?:sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})\b", raw):
                findings.append(emit("ERROR", "SEC", p, 0, "possible hardcoded secret in package"))
        kept.append(p)
    return kept, findings


def cmd_package(args) -> int:
    folder = Path(args.skill).expanduser().resolve()
    if not folder.is_dir():
        print("ERROR: skill folder not found: %s" % folder, file=sys.stderr)
        return 2
    files, findings = ensure_distributable(folder)
    if any(f["level"] == "ERROR" for f in findings):
        print_findings(folder, findings)
        print("Package blocked; correct errors before trying again.", file=sys.stderr)
        return 1
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / (folder.name + ".zip")
    if target.exists() and not args.force:
        print("ERROR: package exists: %s; choose another --out or explicitly --force" % target, file=sys.stderr)
        return 1
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                arcname = str(Path(folder.name) / p.relative_to(folder))
                with open_nofollow_read(p, os.lstat(p)) as handle:  # the file that was checked, never a link put there since
                    data = handle.read()
                zf.writestr(zipfile.ZipInfo.from_file(p, arcname), data, compress_type=zipfile.ZIP_DEFLATED)
    except UnsafeOpen as exc:
        _remove_quietly(target)
        print("ERROR: PACK: %s; nothing was packaged" % exc, file=sys.stderr)
        return 1
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print("Packaged %d runtime files -> %s\nSHA256: %s\nExcluded: evals/, tests/, secrets, caches. Model evaluation status is unchanged." % (len(files), target, digest))
    return 0


def root_link_in_chain(skill_root: Path, stop: Path):
    """First link/junction among `skill_root` and its parents strictly below `stop` (HOME or the workspace itself is not checked), else None."""
    current, stop_norm = Path(skill_root), os.path.normcase(os.path.abspath(stop))
    while os.path.normcase(os.path.abspath(current)) != stop_norm and current.parent != current:
        if is_link(current):
            return current
        current = current.parent
    return None


def move_aside(src: Path, dst: Path) -> None:
    """Move the folder `src` to `dst` (same device: rename). Across devices (rename raises OSError) copy first, then delete `src`; a failed copy removes the
    half-made `dst` and re-raises, so `src` stays whole."""
    try:
        os.rename(src, dst)
        return
    except OSError:
        pass
    try:
        shutil.copytree(src, dst, symlinks=True)
    except BaseException:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    shutil.rmtree(src)


def cmd_install(args) -> int:
    folder = Path(args.skill).expanduser().resolve()
    if not folder.is_dir():
        print("ERROR: skill folder not found", file=sys.stderr)
        return 2
    if args.user:
        try:
            skill_root = user_skill_root(args.agent)
        except ValueError as exc:
            print("ERROR: %s" % exc, file=sys.stderr)
            return 2
        if not skill_root.parent.is_dir():
            print("ERROR: parent directory not found: %s; nothing was created" % skill_root.parent, file=sys.stderr)
            return 2
        boundary = Path.home()
    files, findings = ensure_distributable(folder)
    if any(f["level"] == "ERROR" for f in findings):
        print_findings(folder, findings)
        return 1
    if not args.user:
        rel = Path(".claude") / "skills" if args.agent == "claude" else Path(".agents") / "skills"
        workspace = Path(args.workspace or ".").expanduser().resolve()
        if not workspace.is_dir():
            print("ERROR: workspace directory not found: %s" % workspace, file=sys.stderr)
            return 2
        skill_root = workspace / rel
        boundary = workspace
    linked = root_link_in_chain(skill_root, boundary)
    if linked is not None:
        real = os.path.realpath(skill_root)
        if not args.allow_root_link:
            print("ERROR: skill folder %s is behind a link (%s); its real location is %s. Nothing was installed. Re-run with --allow-root-link if that is intended."
                  % (skill_root, linked, real), file=sys.stderr)
            return 2
        print("Note: skill folder %s is behind a link (%s); installing into its real location %s" % (skill_root, linked, real))
    dest = skill_root / folder.name
    if dest.resolve() == folder or valid_resolved_under(dest, folder):
        print("ERROR: destination is the source Skill or nested under it; refusing self-overwrite", file=sys.stderr)
        return 1
    if os.path.lexists(dest) and is_link(dest):  # before exists(): a dangling link is not "there" for exists() and would crash mkdir
        print("ERROR: symlink destination refused", file=sys.stderr)
        return 1
    if dest.exists() and not args.force:
        print("ERROR: %s exists; no changes made. Use --force only if you intend replacement." % dest, file=sys.stderr)
        return 1
    backup = None
    if dest.exists() and args.force:
        # Back up rather than silently erase; the backup lives next to the skill root, not in it, so the agent never loads it.
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backups_dir = skill_root.parent / ".skill-studio-backups"
        if os.path.lexists(backups_dir) and is_link(backups_dir):
            print("ERROR: backup folder %s is a link; nothing was changed" % backups_dir, file=sys.stderr)
            return 1
        backup = backups_dir / (dest.name + "-" + stamp)
        if os.path.lexists(backup):
            print("ERROR: backup collision", file=sys.stderr)
            return 1
        try:
            backups_dir.mkdir(exist_ok=True)
            move_aside(dest, backup)
        except OSError as exc:
            print("ERROR: could not back up the existing installation (%s); the old Skill was left in place" % (exc.strerror or type(exc).__name__), file=sys.stderr)
            return 1
        print("Existing installation backed up to %s" % backup)
    dest.mkdir(parents=True, exist_ok=False)  # creates skill_root itself, never the agent's config parent
    try:
        for source in files:
            destination = dest / source.relative_to(folder)
            destination.parent.mkdir(parents=True, exist_ok=True)
            inner = link_in_chain(destination.parent, dest)
            if inner is not None:
                raise UnsafeOpen("link inside the destination: %s" % inner)
            info = os.lstat(source)
            with open_nofollow_read(source, info) as src_handle, create_exclusive(destination) as dst_handle:
                shutil.copyfileobj(src_handle, dst_handle)
            os.chmod(destination, stat.S_IMODE(info.st_mode))
    except (UnsafeOpen, OSError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        if backup is not None:
            try:
                os.rename(backup, dest)
            except OSError:
                print("ERROR: the old Skill is kept at %s" % backup, file=sys.stderr)
        print("ERROR: install stopped: %s; no partial Skill was left" % exc, file=sys.stderr)
        return 1
    print("Installed %s for %s at %s. This copies files; it does not run the agent or its scripts." % (folder.name, args.agent, dest))
    return 0


def cmd_sync(args) -> int:
    root = repo_root(Path(__file__))
    if root is None:
        print("ERROR: sync-template is for Studio source repository only", file=sys.stderr)
        return 2
    assets = root / "skills" / "skill-creator-studio" / "assets"
    pairs = [(root / "templates" / a, assets / b) for a, b in TEMPLATE_PAIRS]
    if args.check:
        drift = [(src.name, rel) for src, dst in pairs for rel in mirror_diff(src, dst)]
        for name, rel in drift:
            print("ERROR: template mirror differs: %s/%s" % (name, rel), file=sys.stderr)
        if drift:
            return 1
        print("Template distribution mirror is in sync.")
        return 0
    for src, dst in pairs:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    print("Synced %d canonical templates to bundled skill assets." % len(pairs))
    return 0


def _posix(path) -> str:
    return os.fspath(path).replace("\\", "/")


def _is_excluded(parts: tuple, include_cache: bool) -> bool:
    """True when the newest folder name in `parts` (relative to the root) completes a DOCTOR_EXCLUDE_PARTS entry or looks like a cache."""
    low = [x.lower() for x in parts]
    for pattern in DOCTOR_EXCLUDE_PARTS:
        want = pattern.lower().split("/")
        if low[-len(want):] == want:
            return True
    return not include_cache and "cache" in low[-1]


def parse_roots(roots: str | None, roots_file: str | None, repo: Path | None, skip_markers: tuple = ()) -> list[Path]:
    """Absolute root paths from --roots (`;` separated) and --roots-file (one per line, `#` comments).
    Without either, the repo's skills/ is the root; outside the repo that is an error. A path in a cloud or secret zone is
    returned without being looked at (doctor reports it as skipped); any other root must be an existing directory and not too
    broad (a drive root, the home folder or a folder above it). A --roots-file with a secret-looking name is refused unread, and
    an error about one of its lines names the line number, never the line."""
    markers = CLOUD_MARKERS + tuple(skip_markers)
    items = [(x.strip(), x.strip()) for x in (roots or "").split(";") if x.strip()]
    if roots_file:
        listing = Path(os.path.abspath(os.path.expanduser(roots_file)))
        problem = input_file_problem(listing, markers)
        if problem:
            raise ValueError("--roots-file %s" % problem)
        try:
            lines = listing.read_text(encoding="utf-8").splitlines()
        except UnicodeError:
            raise ValueError("cannot read --roots-file %s: not UTF-8 text" % roots_file)
        except OSError as exc:
            raise ValueError("cannot read --roots-file %s: %s" % (roots_file, exc.strerror or type(exc).__name__))
        items += [(x.strip(), "--roots-file line %d" % number) for number, x in enumerate(lines, 1) if x.strip() and not x.lstrip().startswith("#")]
    if not items:
        if repo is None:
            raise ValueError("outside the Studio repository doctor needs --roots or --roots-file")
        items = [(str(repo / "skills"),) * 2]
    found = []
    for item, label in items:
        path = Path(os.path.abspath(os.path.expanduser(item)))
        if root_too_broad(path, markers):
            raise ValueError("root too broad; pass narrower roots (not a drive root, the home folder or a folder above it): %s" % label)
        if not zone_reason(path, markers) and not path.is_dir():
            raise ValueError("root not found or not a directory: %s" % label)
        found.append(path)
    return found


def iter_skill_dirs(roots: list, include_cache: bool = False, skip_markers: tuple = ()) -> tuple[list, list]:
    """(skill folders, skipped[{path, reason}]). A skill is a folder holding SKILL.md; the scan never goes below one, never
    follows a symlink or junction, and de-duplicates by real path. Reasons: cloud (a name with a marker, or Windows cloud
    attributes on the folder or its SKILL.md), secret-zone (both decided without listing or opening anything there),
    link, excluded, limit, unreadable."""
    markers = CLOUD_MARKERS + tuple(skip_markers)
    skills, skipped, seen_skills, seen_skips, seen_roots, listed = [], [], set(), set(), set(), 0

    def skip(path, reason):
        key = (os.path.normcase(os.fspath(path)), reason)
        if key not in seen_skips:
            seen_skips.add(key)
            skipped.append({"path": _posix(path), "reason": reason})

    for given in roots:
        given = Path(os.path.abspath(os.fspath(given)))
        reason = zone_reason(given, markers) or ("cloud" if path_is_cloud(given) else None)
        if reason:
            skip(given, reason)
            continue
        try:
            real = given.resolve()
        except (OSError, RuntimeError):
            skip(given, "unreadable")
            continue
        reason = zone_reason(real, markers) or ("cloud" if path_is_cloud(real) else None)
        if reason:
            skip(given, reason)
            continue
        if os.path.normcase(str(real)) in seen_roots:
            continue
        seen_roots.add(os.path.normcase(str(real)))
        stack = [(real, ())]
        while stack:
            current, rel = stack.pop()
            listed += 1
            if listed > DOCTOR_MAX_DIRS:
                skip(current, "limit")
                break
            try:
                with os.scandir(current) as scan:
                    entries = sorted(scan, key=lambda e: e.name)
            except OSError:
                skip(current, "unreadable")
                continue
            manifest = next((e for e in entries if e.name == "SKILL.md"), None)
            if manifest is not None:
                if manifest.is_symlink():
                    skip(current / "SKILL.md", "link")
                elif entry_is_cloud(manifest):
                    skip(current, "cloud")
                elif len(skills) >= DOCTOR_MAX_SKILLS:
                    skip(current, "limit")
                elif os.path.normcase(str(current)) not in seen_skills:
                    seen_skills.add(os.path.normcase(str(current)))
                    skills.append(current)
                continue
            for entry in reversed(entries):
                child = current / entry.name
                try:
                    if not (entry.is_dir(follow_symlinks=False) or entry.is_symlink()):
                        continue
                except OSError:
                    continue
                reason = zone_reason(child, markers)
                if reason:
                    skip(child, reason)
                elif entry_is_cloud(entry):
                    skip(child, "cloud")
                elif entry.is_symlink() or is_link(child):
                    skip(child, "link")
                elif entry.name.lower() in DOCTOR_PRUNE_SILENT:
                    continue
                elif _is_excluded(rel + (entry.name,), include_cache):
                    skip(child, "excluded")
                elif len(rel) + 1 > DOCTOR_MAX_DEPTH:
                    skip(child, "limit")
                else:
                    stack.append((child, rel + (entry.name,)))
    return sorted(skills, key=lambda p: os.path.normcase(str(p))), skipped


def _skill_identity(skill: Path, target: str, max_bytes: int | None = None) -> tuple[str, str]:
    """(name, 'en'|'vi') from SKILL.md: frontmatter name (folder name when unreadable or above `max_bytes`) and the body language."""
    manifest = skill / "SKILL.md"
    try:
        text, too_big = read_capped(manifest, max_bytes)
    except (OSError, UnicodeError):
        return skill.name, "en"
    if too_big:
        return skill.name, "en"
    meta, _, body_start = parse_frontmatter(text, manifest, CLAUDE_CODE_KEYS if target == "claude-code" else frozenset())
    name = meta.get("name") if isinstance(meta.get("name"), str) and meta["name"] else skill.name
    return name, detect_lang("\n".join(text.splitlines()[body_start:]))


def _code_counts(report: dict) -> dict:
    """{(skill path, code): times} over ERROR and WARN findings (a NOTE is information, never "new")."""
    counts: dict = {}
    for skill in report.get("skills", []):
        for item in skill.get("codes", []):
            if item.get("level") in ("ERROR", "WARN"):
                key = (skill.get("path"), item.get("code"))
                counts[key] = counts.get(key, 0) + 1
    return counts


def diff_baseline(current: dict, baseline: dict) -> list[dict]:
    """The (skill, code) pairs that occur more often in `current` than in `baseline`."""
    before = _code_counts(baseline)
    return [{"path": path, "code": code, "before": before.get((path, code), 0), "after": after}
            for (path, code), after in sorted(_code_counts(current).items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))
            if after > before.get((path, code), 0)]


def doctor_run(roots: list, profile: str, target: str, include_cache: bool, baseline: dict | None,
               skip_markers: tuple = (), scanned: tuple | None = None) -> dict:
    """The doctor report (SPEC 9.11, schema 1). Reads skills, writes nothing. `scanned` = a finished iter_skill_dirs result to reuse.
    A file above DOCTOR_MAX_FILE_BYTES or a cloud placeholder inside a skill is not read; it is listed in skipped as well as flagged in the skill."""
    skills, skipped = scanned if scanned is not None else iter_skill_dirs(roots, include_cache, skip_markers)
    skipped = list(skipped)
    seen_skips = {(os.path.normcase(x["path"]), x["reason"]) for x in skipped}
    real_roots = []
    for root in roots:
        if not zone_reason(root, CLOUD_MARKERS + tuple(skip_markers)):
            try:
                real_roots.append(Path(root).resolve())
            except OSError:
                continue
    entries = []
    totals = {"skills": 0, "errors": 0, "warnings": 0, "notes": 0}
    for skill in skills:
        under = next((r for r in real_roots if valid_resolved_under(skill, r)), None)
        findings = validate_skill(skill, require_evals=False, target=target, profile=profile, allow_links_under=under,
                                  max_file_bytes=DOCTOR_MAX_FILE_BYTES, skip_markers=skip_markers)
        codes = []
        for f in findings:
            if f["code"] in ("SZ1", "SZ2"):
                note = {"path": _posix(f["path"]), "reason": "limit" if f["code"] == "SZ1" else "cloud"}
                if (os.path.normcase(note["path"]), note["reason"]) not in seen_skips:
                    seen_skips.add((os.path.normcase(note["path"]), note["reason"]))
                    skipped.append(note)
            path = Path(f["path"])
            try:
                shown = path.relative_to(skill).as_posix()
            except ValueError:
                shown = _posix(path)
            codes.append({"code": f["code"], "level": f["level"], "file": shown, "line": f["line"], "message": f["message"]})
        name, lang = _skill_identity(skill, target, DOCTOR_MAX_FILE_BYTES)
        errors, warnings = sum(c["level"] == "ERROR" for c in codes), sum(c["level"] == "WARN" for c in codes)
        entries.append({"path": _posix(skill), "name": name, "lang": lang, "errors": errors, "warnings": warnings, "codes": codes})
        totals["skills"] += 1
        totals["errors"] += errors
        totals["warnings"] += warnings
        totals["notes"] += sum(c["level"] == "NOTE" for c in codes)
    report = {"schema": DOCTOR_SCHEMA, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "studio_version": VERSION, "roots": [_posix(r) for r in roots], "skills": entries, "skipped": skipped,
              "totals": totals, "new_vs_baseline": []}
    if baseline is not None:
        report["new_vs_baseline"] = diff_baseline(report, baseline)
    return report


def _baseline_problem(obj) -> str | None:
    if not isinstance(obj, dict) or obj.get("schema") != DOCTOR_SCHEMA or not isinstance(obj.get("skills"), list):
        return "is not a doctor report (expected JSON with schema %d and a skills list)" % DOCTOR_SCHEMA
    for skill in obj["skills"]:
        if not isinstance(skill, dict) or not isinstance(skill.get("codes", []), list) or any(not isinstance(c, dict) for c in skill.get("codes", [])):
            return "has skills[] entries that are not objects with a codes list"
    return None


def _out_problem(out: Path, roots: list, repo: Path | None, skills: list = (), include_cache: bool = False, skip_markers: tuple = ()) -> str | None:
    """Why `out` may not be written, else None. The report may not land in what the scan reads: not in a zone, not under skills/, not in a
    scanned skill, and not in a scanned root unless the folder in between (.tmp, .worktrees, a cache...) is one the scan leaves out.
    It may not carry a secret-looking name or an NTFS stream, and an existing file is overwritten only when it is empty or already a doctor
    report (a .json file that starts with {"schema"). Order matters: every decision by name, zone or cloud attributes on the spelling given
    and on the real folder comes first; the file itself is stat-ed and its first bytes read last, only once it is known to be a plain
    local path (so a link into ~/.secret or a cloud folder is refused without one call on the file, and with the same message whatever it holds)."""
    markers = CLOUD_MARKERS + tuple(skip_markers)
    reason = zone_reason(out, markers)
    if reason:
        return "--out is inside a %s zone" % reason
    if os.name == "nt" and ":" in os.path.splitdrive(os.fspath(out))[1]:
        return "--out names an NTFS data stream: %s" % out.name
    if secret_file_name(out.name):
        return "--out has a secret-looking file name: %s" % out.name
    try:
        real_parent = out.parent.resolve()
    except (OSError, RuntimeError):
        return "--out cannot be resolved: %s" % out
    real = real_parent / out.name
    reason = zone_reason(real, markers)
    if reason:
        return "--out is inside a %s zone (through a link)" % reason
    if path_is_cloud(real_parent) or path_is_cloud(out.parent):
        return "--out is inside a cloud placeholder folder: %s" % out.parent
    if path_is_cloud(real) or path_is_cloud(out):
        return "--out is a cloud placeholder: %s" % out
    if any(part.lower() == "skills" for part in out.parts[:-1]) or (repo is not None and valid_resolved_under(real, repo / "skills")):
        return "--out must not be under a skills/ folder: %s" % out
    if any(valid_resolved_under(real, skill) for skill in skills):
        return "--out must not be inside a scanned skill folder: %s" % out
    for root in roots:
        if zone_reason(root, markers):
            continue
        try:
            below = real.parent.relative_to(Path(root).resolve()).parts
        except (ValueError, OSError, RuntimeError):
            continue
        if not any(_is_excluded(below[:n], include_cache) for n in range(1, len(below) + 1)):
            return "--out must not be inside a scanned root (a folder the scan skips, such as .tmp, is fine): %s" % out
    if not real_parent.is_dir():
        return "folder of --out does not exist: %s (doctor never creates folders)" % out.parent
    if out.is_dir() or is_link(out):
        return "--out must be a plain file path: %s" % out
    if out.exists():
        if out.suffix.lower() != ".json":
            return "--out would overwrite an existing file that is not a .json report: %s" % out
        try:
            with open(out, "rb") as handle:
                head = handle.read(64)
        except OSError:
            return "--out exists and cannot be checked: %s" % out
        if head.strip() and not DOCTOR_REPORT_HEAD.match(head):
            return "--out would overwrite an existing file that is not a doctor report (it must start with {\"schema\"): %s" % out
    return None


def cmd_doctor(args) -> int:
    """Report-only scan of many skill roots. Exit 0 nothing at the --fail-on level, 1 findings, 2 could not scan."""
    repo = repo_root(Path(__file__)) or repo_root(Path.cwd())
    skip_markers = tuple(x.strip() for x in (args.skip_marker or []))
    if any(not x for x in skip_markers):
        print("ERROR: --skip-marker needs non-empty text", file=sys.stderr)
        return 2
    markers = CLOUD_MARKERS + skip_markers
    try:
        roots = parse_roots(args.roots, args.roots_file, repo, skip_markers)
    except ValueError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    baseline = None
    if args.fail_on == "new" and not args.baseline:
        print("ERROR: --fail-on new needs --baseline <earlier doctor --json report>", file=sys.stderr)
        return 2
    if args.baseline:
        source = Path(os.path.abspath(os.path.expanduser(args.baseline)))
        problem = input_file_problem(source, markers)
        if problem is None:
            try:
                baseline = json.loads(source.read_text(encoding="utf-8"))
            except UnicodeError:
                problem = "cannot be read: not UTF-8 text"
            except OSError as exc:
                problem = "cannot be read (%s)" % (exc.strerror or type(exc).__name__)
            except ValueError as exc:
                problem = "cannot be read as JSON (line %s column %s)" % (getattr(exc, "lineno", "?"), getattr(exc, "colno", "?"))
            else:
                problem = _baseline_problem(baseline)
        if problem:
            print("ERROR: baseline %s %s" % (args.baseline, problem), file=sys.stderr)
            return 2
    out = None
    if args.out:  # decided by name and by what the file holds before any root is walked; the scanned skills are added after the scan
        out = Path(os.path.abspath(os.path.expanduser(args.out)))
        problem = _out_problem(out, roots, repo, [], args.include_cache, skip_markers)
        if problem:
            print("ERROR: %s" % problem, file=sys.stderr)
            return 2
    scanned = iter_skill_dirs(roots, args.include_cache, skip_markers)
    if out is not None:
        problem = _out_problem(out, roots, repo, scanned[0], args.include_cache, skip_markers)
        if problem:
            print("ERROR: %s" % problem, file=sys.stderr)
            return 2
    report = doctor_run(roots, args.profile, args.target, args.include_cache, baseline, skip_markers, scanned)
    if out is not None:
        try:
            with open(out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        except OSError as exc:
            print("ERROR: cannot write --out: %s" % exc, file=sys.stderr)
            return 2
    totals = report["totals"]
    if args.json and out is None:
        try:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        except UnicodeEncodeError:  # a console that cannot show every character
            print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print("doctor (profile %s, target %s): %d skills, %d errors, %d warnings, %d notes; %d skipped"
              % (args.profile, args.target, totals["skills"], totals["errors"], totals["warnings"], totals["notes"], len(report["skipped"])))
        for skill in report["skills"]:
            if skill["errors"] or skill["warnings"]:
                print("  %s: %d errors, %d warnings" % (skill["path"], skill["errors"], skill["warnings"]))
        for item in report["skipped"]:
            print("  skipped (%s): %s" % (item["reason"], item["path"]))
        for item in report["new_vs_baseline"]:
            print("  new vs baseline: %s %s %d -> %d" % (item["path"], item["code"], item["before"], item["after"]))
        if out is not None:
            print("report written to %s" % out)
    if args.fail_on == "new":
        found = bool(report["new_vs_baseline"])
    elif args.fail_on == "warn":
        found = bool(totals["errors"] or totals["warnings"])
    else:
        found = bool(totals["errors"])
    return 1 if found else 0


def _fm_bounds(lines: list) -> tuple | None:
    """(0, closing index) when line 0 is '---' and a closing '---' follows, else None. Both lines are '---' in column 0 (blanks after them
    are allowed): an indented '---' neither opens the frontmatter nor, inside a block scalar, closes it."""
    if not lines or lines[0].rstrip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            return 0, index
    return None


def _fm_blocks(block_lines: list) -> tuple[list, list]:
    """(lines before the first key, [(key, [the key line and every line after it up to the next top-level key])])."""
    pre, blocks = [], []
    for line in block_lines:
        match = None if line[:1].isspace() else FRONT_KEY_RE.fullmatch(line)
        if match:
            blocks.append((match.group(1), [line]))
        else:
            (blocks[-1][1] if blocks else pre).append(line)
    return pre, blocks


def _looks_like_front(lines: list) -> bool:
    """lines[0] is '---', a closing '---' follows, and between them every plain line is `key: value` (at least one key)."""
    bounds = _fm_bounds(lines)
    if not bounds:
        return False
    keys = 0
    for line in lines[1:bounds[1]]:
        if not line.strip() or line[:1].isspace() or line.lstrip().startswith("#"):
            continue
        if not FRONT_KEY_RE.fullmatch(line):
            return False
        keys += 1
    return keys > 0


def _quote_meta(line: str) -> tuple[str, str]:
    """(the line, status) for one line of a metadata block. `fixed`: the value is now in double quotes. `stuck`: the value is not a plain
    string fmt can quote safely (a comment, a block or flow marker, an unmatched quote) and the line stays as it is. `ok`: nothing to do."""
    match = FMT_META_LINE_RE.match(line.rstrip(" \t"))  # only the blanks FT1 removes: a no-break space belongs to the value
    if not match:
        return line, "ok"
    value = match.group(2)
    if value[0] == '"':
        return line, "ok"
    if value[0] == "'" and len(value) >= 2 and value[-1] == "'":
        value = value[1:-1].replace("''", "'")
    elif value[0] in "[{>|&*!%@`'" or " #" in value or "\t#" in value or ": " in value:
        return line, "stuck"
    return "%s %s" % (match.group(1), json.dumps(value, ensure_ascii=False)), "fixed"


def fmt_text(text: str, kind: str, profile: str = "portable") -> tuple[str, list]:
    """Pure (no I/O): (the text in house style, findings FT1-FT5). `kind` is skill, process, studio-doc or other. A finding is
    {level, code, line, message, fixable}; the returned text has every fixable one applied and the words of the body unchanged.
    `profile` is accepted for symmetry with doctor: fmt adds no opcos metadata, so it changes nothing here."""
    if profile not in PROFILES:
        raise ValueError("unknown profile %r" % profile)
    found: list[dict] = []

    def add(code: str, line: int, message: str, fixable: bool) -> None:
        found.append({"level": "ERROR", "code": code, "line": line, "message": message, "fixable": fixable})

    new = text
    if new.startswith("﻿"):
        add("FT1", 1, "byte order mark", True)
        new = new.lstrip("﻿")
    if "\r" in new:
        add("FT1", len(re.findall(r"\r\n|\r|\n", new[:new.index("\r")])) + 1, "CR or CRLF line ending; use LF", True)
        new = new.replace("\r\n", "\n").replace("\r", "\n")
    lines = new.split("\n")
    trailing = [i + 1 for i, line in enumerate(lines) if line != line.rstrip(" \t")]
    if trailing:
        add("FT1", trailing[0], "trailing whitespace on %d line(s)" % len(trailing), True)
        lines = [line.rstrip(" \t") for line in lines]
    joined = "\n".join(lines)
    core = joined.rstrip("\n")
    wanted = core + "\n" if core else ""
    if joined != wanted:
        add("FT1", len(lines), "no final newline" if not joined.endswith("\n") else "more than one final newline", True)
    lines = wanted.split("\n")[:-1] if wanted else []

    lead = next((i for i, line in enumerate(lines) if line.strip()), 0)
    if kind != "other" and lines and lines[lead].strip() == "---" and lines[lead] != "---" and _looks_like_front(["---"] + lines[lead + 1:]):
        add("FT5", lead + 1, "the opening '---' of the frontmatter must be in column 0 (line %d is indented)" % (lead + 1), False)
    elif lead and _looks_like_front(lines[lead:]):
        add("FT5", 1, "%d blank line(s) before the frontmatter; it must start on line 1" % lead, True)
        lines = lines[lead:]
    elif kind != "other" and not (lines and lines[0] == "---"):
        fences = 0
        for index in range(1, min(len(lines), FMT_FRONT_SEARCH_LINES)):
            if FENCE_OPEN_RE.match(lines[index]):
                fences += 1
            elif lines[index] == "---" and fences % 2 == 0 and _looks_like_front(lines[index:]):
                block = lines[index + 1:index + _fm_bounds(lines[index:])[1]]
                if any(FRONT_KEY_RE.fullmatch(x) and FRONT_KEY_RE.fullmatch(x).group(1) in ("name", "description", "title", "status", "updated") for x in block):
                    add("FT5", index + 1, "frontmatter starts on line %d; it must start on line 1" % (index + 1), False)
                break

    bounds = _fm_bounds(lines)
    if kind == "skill" and bounds:
        pre, blocks = _fm_blocks(lines[1:bounds[1]])
        offset = 2 + len(pre)
        rebuilt = []
        for key, block in blocks:
            head = FRONT_KEY_RE.fullmatch(block[0])
            if key == "metadata" and head and not (head.group(2) or "").strip():
                quoted = [block[0]]
                for number, line in enumerate(block[1:], start=offset + 1):
                    changed, status = _quote_meta(line)
                    if status == "fixed":
                        add("FT3", number, "metadata value must be a double-quoted string", True)
                    elif status == "stuck":
                        add("FT3", number, "metadata value is not a plain string (comment, block or flow marker, unmatched quote): quote it by hand", False)
                    quoted.append(changed)
                block = quoted
            rebuilt.append((key, block))
            offset += len(block)
        rank = lambda key: FM_ORDER.index(key) if key in FM_ORDER else len(FM_ORDER)
        ordered = sorted(rebuilt, key=lambda item: rank(item[0]))
        if [k for k, _ in ordered] != [k for k, _ in rebuilt]:
            line = 2 + len(pre)
            for (have, block), (want, _) in zip(rebuilt, ordered):
                if have != want:
                    break
                line += len(block)
            add("FT2", line, "frontmatter keys out of order; expected %s, then any other keys in their own order" % ", ".join(FM_ORDER), True)
        lines = ["---"] + pre + [x for _, block in ordered for x in block] + lines[bounds[1]:]
    if kind == "studio-doc":
        keys = {key for key, _ in _fm_blocks(lines[1:bounds[1]])[1]} if bounds else set()
        missing = [key for key in DOC_MIN_KEYS if key not in keys]
        if missing:
            add("FT4", 1, "missing minimum frontmatter key(s): %s" % ", ".join(missing), False)
    found.sort(key=lambda item: item["line"])
    return ("\n".join(lines) + "\n" if lines else ""), found


def check_process_shape(text: str) -> list:
    """PR1 (WARN) for each part of the process-file shape (SPEC 9.13) that is missing. English or Vietnamese labels."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    bounds = _fm_bounds(lines)
    start = bounds[1] + 1 if bounds else 0
    body = lines[start:]
    heads: list[tuple] = []  # (index in body, level, title)
    plain: list[tuple] = []  # (index in body, line) outside code fences
    fence = None
    for index, line in enumerate(body):
        match = FENCE_OPEN_RE.match(line)
        if match:
            fence = None if fence == match.group(1)[0] else (fence or match.group(1)[0])
            continue
        if fence:
            continue
        plain.append((index, line))
        head = FMT_HEADING_RE.match(line.rstrip())
        if head:
            heads.append((index, len(head.group(1)), head.group(2)))
    found: list[dict] = []

    def warn(index: int, message: str) -> None:
        found.append({"level": "WARN", "code": "PR1", "line": start + index + 1, "message": message})

    if not any(level == 1 for _, level, _ in heads):
        warn(0, "process file has no '# <Name>' title")
    if not any(FMT_CONCLUSION_RE.match(line) for _, line in plain):
        warn(0, "process file has no '> **Conclusion:**' (VI '> **Kết luận:**') line")
    if len(body) > 100 and not any(CONTENTS_RE.match("## " + title) for _, level, title in heads if level == 2):
        warn(0, "process file is over 100 lines and has no '## Contents'")
    for pattern, label in FMT_PROCESS_SECTIONS:
        if not any(level == 2 and pattern.match(title) for _, level, title in heads):
            warn(0, "process file has no '## %s' section" % label)
    steps = [(i, title) for i, level, title in heads if level == 3 and FMT_STEP_RE.match(title)]
    if not steps:
        warn(0, "process file has no '### Step N — <verb>' (VI '### Bước N — <động từ>') section")
    ends = [i for i, level, _ in heads if level <= 3]  # ascending: a step's section stops at the next heading of level 3 or above
    plain_at = [i for i, _ in plain]
    for index, title in steps:
        at = bisect.bisect_right(ends, index)
        stop = ends[at] if at < len(ends) else len(body)
        section = [line for _, line in plain[bisect.bisect_right(plain_at, index):bisect.bisect_left(plain_at, stop)]]
        for pattern, label in FMT_STEP_LABELS:
            if not any(pattern.match(line) for line in section):
                warn(index, "step '%s' has no '%s'" % (title, label))
    return found


def classify_md(path: Path, root: Path | None) -> str:
    """skill (SKILL.md, SKILL.vi.md), process (*PROCESS*.md, *_WORKFLOW.md), studio-doc (standards/*.md, content/*.md, templates/README.md
    of the repo `root`) or other."""
    name = path.name
    if name in ("SKILL.md", "SKILL.vi.md"):
        return "skill"
    upper = name.upper()
    if upper.endswith(".MD") and ("PROCESS" in upper or upper.endswith("_WORKFLOW.MD")):
        return "process"
    if root is not None:
        try:
            parts = tuple(x.casefold() for x in Path(os.path.abspath(path)).relative_to(os.path.abspath(root)).parts)
        except ValueError:
            return "other"
        if len(parts) == 2 and parts[0] in ("standards", "content") and parts[1].endswith(".md"):
            return "studio-doc"
        if parts == ("templates", "readme.md"):
            return "studio-doc"
    return "other"


def _crosses_link(path) -> bool:
    """True when `path` itself or any folder on the way to it is a symlink or junction. The top-level folder of the volume is not looked at
    (/tmp and /var are links on macOS); every folder below it is, whether or not it lies under the repo."""
    parts = Path(os.path.abspath(path)).parts
    base = Path(parts[0])
    for depth, part in enumerate(parts[1:], start=1):
        base = base / part
        if (depth > 1 or depth == len(parts) - 1) and is_link(base):
            return True
    return False


def iter_md(paths: list, all_repo: bool, root: Path | None, skipped: list | None = None) -> list[Path]:
    """The Markdown files to format: each given file, plus every *.md under each given folder (and under `root` with all_repo). Never
    entered or opened: links, cloud placeholders, cloud/secret zones, .git, .tmp, .worktrees, dist, node_modules, evals/**/runs. A file or
    folder left out is appended to `skipped` as {path, reason}."""
    skipped = skipped if skipped is not None else []
    files: list[Path] = []
    seen: set = set()

    def skip(path, reason: str) -> None:
        skipped.append({"path": str(path), "reason": reason})

    def take(path: Path) -> None:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            return
        seen.add(key)
        if not path.name.lower().endswith(".md"):
            skip(path, "not-markdown")
        elif secret_file_name(path.name):
            skip(path, "secret-name")
        else:
            try:
                size = os.lstat(path).st_size
            except OSError:
                skip(path, "unreadable")
                return
            if size > DOCTOR_MAX_FILE_BYTES:
                skip(path, "limit")
            else:
                files.append(path)

    starts = [Path(os.path.abspath(os.path.expanduser(os.fspath(p)))) for p in paths]
    if all_repo and root is not None:
        starts.append(Path(os.path.abspath(root)))
    for start in starts:
        reason = zone_reason(start)
        if reason:
            skip(start, reason)
        elif _crosses_link(start):
            skip(start, "link")
        elif path_is_cloud(start):
            skip(start, "cloud")
        elif zone_reason(os.path.realpath(start)):  # the resolved spelling (8.3 short names, case): checked last, after the lstat above
            skip(start, zone_reason(os.path.realpath(start)))
        elif start.is_file():
            take(start)
        elif start.is_dir():
            stack, visited = [start], 0
            while stack:
                current = stack.pop()
                visited += 1
                if visited > DOCTOR_MAX_DIRS:
                    skip(current, "too-many-folders")
                    break
                try:
                    with os.scandir(current) as scan:
                        entries = sorted(scan, key=lambda e: e.name)
                except OSError:
                    skip(current, "unreadable")
                    continue
                for entry in entries:
                    child = Path(entry.path)
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        is_file = entry.is_file(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir or is_file:
                        if entry_is_cloud(entry):
                            skip(child, "cloud")
                            continue
                    if entry.is_symlink() or (is_dir and is_link(child)):
                        try:
                            to_dir = is_dir or entry.is_dir()  # a POSIX symlink to a folder is not is_dir(follow_symlinks=False): ask what it points at
                        except OSError:
                            to_dir = False
                        if to_dir or entry.name.lower().endswith(".md"):
                            skip(child, "link")
                    elif is_dir:
                        if entry.name in FMT_PRUNE_DIRS or (entry.name == "runs" and "evals" in (x.casefold() for x in child.parts)):
                            continue
                        if zone_named(entry.name):
                            skip(child, "cloud-or-secret-zone")
                        else:
                            stack.append(child)
                    elif is_file and entry.name.lower().endswith(".md"):
                        take(child)
    return sorted(files)


def _body_words(text: str) -> list:
    """Words of what follows the frontmatter (the whole text without one), ignoring a BOM: the thing fmt --fix must not change."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines = lines[1:]
    bounds = _fm_bounds(lines)
    return ("\n".join(lines[bounds[1] + 1:]) if bounds else "\n".join(lines)).split()


def _remove_quietly(path) -> None:
    """Delete a file this run made; one that is read-only (copied mode) loses that bit first. Never raises."""
    for attempt in (0, 1):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt:
                return
            try:
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                return


def _write_fixed(path: Path, data: bytes, backup: bool) -> str | None:
    """Replace `path` with `data`: a copy `<name>.bak-<ISO>` first when `backup`, then a new temp file next to it (a name chosen by the system
    and created exclusively, so a link planted at a guessable name is never followed) and an atomic replace. A read-only file is refused
    before anything is made. Whatever this call made is removed again when it fails; the original file stays as it was. Returns the path of
    the backup, or None when none was asked for."""
    if not os.access(path, os.W_OK):
        raise PermissionError(13, "file is read-only", os.fspath(path))
    made_backup, temp, handle, done = None, None, None, False
    try:
        if backup:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            target, count = path.with_name("%s.bak-%s" % (path.name, stamp)), 1
            while True:
                try:
                    sink = create_exclusive(target)  # O_EXCL: a name already there (a link included) is never written through
                    break
                except FileExistsError:
                    target = path.with_name("%s.bak-%s-%d" % (path.name, stamp, count))
                    count += 1
            made_backup = target  # set only once the exclusive create has succeeded, so a failure never removes a file we did not make
            with sink, open_nofollow_read(path, single_link=False) as source:
                shutil.copyfileobj(source, sink)
            try:
                shutil.copystat(path, target)
            except OSError:
                pass
        handle, name = tempfile.mkstemp(dir=os.fspath(path.parent), prefix=".%s." % path.name, suffix=".fmt-tmp")
        temp = Path(name)
        out, handle = os.fdopen(handle, "wb"), None
        with out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            shutil.copymode(path, temp)
        except OSError:
            pass
        os.replace(temp, path)
        done = True
        return os.fspath(made_backup) if made_backup is not None else None
    finally:
        if not done:
            if handle is not None:
                try:
                    os.close(handle)
                except OSError:
                    pass
            if temp is not None:
                _remove_quietly(temp)
            if made_backup is not None:
                _remove_quietly(made_backup)


def cmd_fmt(args) -> int:
    """`fmt --check` (default) lists FT*/PR1 findings and never writes; `fmt --fix` applies the fixable ones to the files named.
    Exit 0 nothing left at ERROR level, 1 an ERROR (FT*) remains, 2 a path does not exist or the request is refused."""
    fixing = bool(args.fix)
    repo = repo_root(Path(__file__)) or repo_root(Path.cwd())
    if args.profile not in PROFILES:
        print("ERROR: unknown profile %s" % args.profile, file=sys.stderr)
        return 2
    if args.no_backup and not fixing:
        print("ERROR: --no-backup needs --fix (check mode writes nothing)", file=sys.stderr)
        return 2
    if args.all and fixing:
        print("ERROR: --all only reports; give the files or folders to --fix", file=sys.stderr)
        return 2
    if not args.paths and not args.all:
        print("ERROR: give at least one file or folder, or --all", file=sys.stderr)
        return 2
    if args.all and repo is None:
        print("ERROR: --all needs to run inside the Studio repo", file=sys.stderr)
        return 2
    for given in args.paths:
        spelled = Path(os.path.abspath(os.path.expanduser(given)))
        if not zone_reason(spelled) and not os.path.lexists(spelled):
            print("ERROR: path does not exist: %s" % given, file=sys.stderr)
            return 2
    skipped: list[dict] = []
    files = iter_md(args.paths, args.all, repo, skipped)
    named = {os.path.normcase(os.path.abspath(os.path.expanduser(given))) for given in args.paths}
    if args.all and repo is not None:
        named.add(os.path.normcase(os.path.abspath(repo)))
    results, errors, warnings, changed, backups = [], 0, 0, 0, 0
    for path in files:
        try:
            with open_nofollow_read(path, single_link=False) as handle:
                raw = handle.read()
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append({"path": str(path), "reason": "not-utf8"})
            continue
        except OSError:
            skipped.append({"path": str(path), "reason": "unreadable"})
            continue
        kind = classify_md(path, repo)
        new, found = fmt_text(text, kind, args.profile)
        wrote, backup = False, None
        if fixing and new != text:
            if _body_words(new) != _body_words(text):  # fmt_text is meant never to do this; refuse to write if it ever does
                skipped.append({"path": str(path), "reason": "would-change-text"})
                continue
            try:
                backup = _write_fixed(path, new.encode("utf-8"), backup=not args.no_backup)
            except OSError as exc:
                print("ERROR: cannot write %s: %s" % (path, exc.strerror or type(exc).__name__), file=sys.stderr)
                return 2
            wrote, changed = True, changed + 1
            backups += 1 if backup else 0
            found = fmt_text(new, kind, args.profile)[1]
        if kind == "process":
            found = found + check_process_shape(new if fixing else text)
        errors += sum(1 for f in found if f["level"] == "ERROR")
        warnings += sum(1 for f in found if f["level"] == "WARN")
        results.append({"path": str(path), "kind": kind, "changed": wrote, "backup": backup,
                        "findings": [dict(f, fixable=f.get("fixable", False)) for f in found]})
    # A file or folder that was asked for (or could not be read, was refused, or is over the size limit) and so was not checked keeps "exit 0 =
    # everything is in house style" true: it makes the exit code 1. A file left out while walking a folder because it is cloud, a link, a
    # secret name or in a secret zone is left out on purpose and does not.
    blocked = {id(item) for item in skipped if item["reason"] in FMT_BLOCKING_REASONS or os.path.normcase(os.path.abspath(item["path"])) in named}
    report = {"schema": 1, "mode": "fix" if fixing else "check", "files": results, "skipped": skipped,
              "totals": {"files": len(results), "changed": changed, "errors": errors, "warnings": warnings, "blocked": len(blocked)}}
    if args.json:
        try:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        except UnicodeEncodeError:
            print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        for item in results:
            for f in item["findings"]:
                print("%s:%d: %s %s %s%s" % (item["path"], f["line"], f["level"], f["code"], f["message"],
                                             " (fixable with --fix)" if f["fixable"] and not fixing else ""))
            if item["changed"]:
                print("fixed: %s" % item["path"])
        for item in skipped:
            print("skipped (%s): %s%s" % (item["reason"], item["path"], "  [blocks the exit]" if id(item) in blocked else ""))
        print("fmt --%s: %d files, %d changed, %d backups, %d errors, %d warnings, %d skipped, %d of them block the exit"
              % (report["mode"], len(results), changed, backups, errors, warnings, len(skipped), len(blocked)))
    return 1 if errors or blocked else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Skill Studio: create, audit, lint, package and install portable skills")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("new", help="scaffold a new Skill and an external, empty eval suite")
    p.add_argument("name")
    p.add_argument("--description", required=True)
    p.add_argument("--output", help="parent directory (default repo skills/)")
    p.add_argument("--eval-root", help="external evals directory (default repo evals/)")
    p.add_argument("--lang", choices=TEMPLATE_LANGS, default="en", help="language of the template body (default en); frontmatter stays English")
    p.add_argument("--full", action="store_true", help="scaffold the full English-only template (references/, scripts/, assets/, agents/)")
    p.set_defaults(func=cmd_new)
    for action in ("validate", "audit"):
        p = sub.add_parser(action, help="static %s, never edits files" % action)
        p.add_argument("skill", nargs="?", help="Skill folder")
        p.add_argument("--all", action="store_true", help="all canonical repo skills")
        p.add_argument("--require-evals", action="store_true", help="require matching external eval manifest")
        p.add_argument("--eval-root", help="where external evals are stored")
        p.add_argument("--target", choices=TARGETS, default="portable", help="portable (default) or claude-code (also accepts Claude Code only keys as FM6 warnings)")
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=lambda args, audit=(action == "audit"): cmd_check(args, audit))
    p = sub.add_parser("evals", help="validate eval manifest schemas (no model calls); with --export agentskills also write evals.json")
    p.add_argument("skill", nargs="?", help="Skill name")
    p.add_argument("--all", action="store_true")
    p.add_argument("--eval-root")
    p.add_argument("--export", choices=EXPORT_FORMATS, help="write the positive cases as <out>/<skill>/evals/evals.json in this format")
    p.add_argument("--out", help="export destination (default %s); must not be under skills/ or evals/" % EXPORT_DEFAULT_OUT)
    p.add_argument("--force", action="store_true", help="overwrite existing exported files")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_evals)
    p = sub.add_parser("package", help="produce portable runtime-only Skill ZIP")
    p.add_argument("skill")
    p.add_argument("--out", default="dist")
    p.add_argument("--force", action="store_true", help="replace existing ZIP explicitly")
    p.set_defaults(func=cmd_package)
    p = sub.add_parser("install", help="copy a Skill into a project's runtime discovery folder")
    p.add_argument("skill")
    p.add_argument("--agent", choices=("claude", "codex", "antigravity"), required=True)
    where = p.add_mutually_exclusive_group()
    where.add_argument("--workspace", help="project directory (default .)")
    where.add_argument("--user", action="store_true", help="install into the per-user skill folder (antigravity, codex; not claude); the agent's config folder must already exist")
    p.add_argument("--force", action="store_true", help="back up (to <skill root parent>/.skill-studio-backups/) and replace existing install")
    p.add_argument("--allow-root-link", action="store_true", help="install even when the skill folder (or a parent below HOME/the workspace) is a symlink or junction; the real target is printed")
    p.set_defaults(func=cmd_install)
    p = sub.add_parser("sync-template", help="sync source template to packaged Skill asset")
    p.add_argument("--check", action="store_true", help="verify byte-identical mirror without modifications")
    p.set_defaults(func=cmd_sync)
    p = sub.add_parser("doctor", help="report-only scan of many skill roots (not Claude Code's /skill-doctor); exit 0 clean, 1 findings, 2 cannot scan")
    p.add_argument("--roots", help="skill roots separated by ';' (default: the repo's skills/; outside the repo --roots or --roots-file is required)")
    p.add_argument("--roots-file", help="file with one root per line, '#' starts a comment")
    p.add_argument("--profile", choices=PROFILES, default="portable", help="opcos: a link inside the scanned root is a WARN, provenance keys are WARN, missing metadata.opcos_* is a NOTE")
    p.add_argument("--target", choices=TARGETS, default="portable")
    p.add_argument("--include-cache", action="store_true", help="also scan folders whose name contains 'cache'")
    p.add_argument("--skip-marker", action="append", metavar="TEXT", help="skip any path containing TEXT (case-insensitive); repeatable. A synced SharePoint folder need not say 'SharePoint' (for example 'KPIM Joint Stock Company')")
    p.add_argument("--baseline", help="an earlier doctor JSON report; new_vs_baseline lists the (skill, code) pairs that grew")
    p.add_argument("--json", action="store_true", help="print the JSON report (with --out it goes to the file only)")
    p.add_argument("--out", help="write the JSON report here; the folder must exist; not under skills/, a scanned skill or a scanned root (a folder the scan skips, such as .tmp, is fine); not a secret-looking name")
    p.add_argument("--fail-on", choices=DOCTOR_FAIL_ON, default="error", help="what makes the exit code 1 (default error; new needs --baseline)")
    p.set_defaults(func=cmd_doctor)
    p = sub.add_parser("fmt", help="check (default) or fix the house style of Markdown files: line endings, key order, quoted metadata (never edits the words of the body)")
    p.add_argument("paths", nargs="*", help="files or folders (*.md); --fix only touches what is named")
    p.add_argument("--all", action="store_true", help="every *.md of the repo, report only (not with --fix)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="list findings, write nothing (default)")
    mode.add_argument("--fix", action="store_true", help="apply the fixable findings; every changed file is first copied to <file>.bak-<ISO> (see --no-backup)")
    p.add_argument("--no-backup", action="store_true", help="skip the <file>.bak-<ISO> copy; use when git or another backup already holds the files")
    p.add_argument("--profile", choices=PROFILES, default="portable")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fmt)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
