"""Document types beyond a skill: workflow files and agent rules files, and their checks (SPR-04 TK8, FR8, `standards/DOC_TYPES.md`).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
Pure on the text it is given: `lint_workflow` and `lint_rules` open nothing, so the caller decides which file may be read (zones, links and
cloud placeholders are refused before this module sees a byte). Findings use the same record as every other check (`fs.emit`).
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

import studio_const as C
import studio_fs as fs

RULES_NAMES = ("agents.md", "claude.md", "gemini.md")  # a rules file by its name alone (letter case ignored)
WORKFLOW_MAX_LINES = 300  # WC4
RULES_MAX_LINES = 200  # RL1
CONCLUSION_WINDOW = 15  # WC1: the Kết luận line sits within this many lines of the body start
CONCLUSION_RE = re.compile(r"^(?:>\s*)?\*\*Kết luận(?::\*\*|\*\*:)", re.IGNORECASE)
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*)$")
NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+\S")
HISTORY_RE = re.compile(r"đổi từ bản|changed from v", re.IGNORECASE)
COMMIT_RE = re.compile(r"\bcommit\b", re.IGNORECASE)
HEX_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
SUPERSEDE_RE = re.compile(r"^[\s>*\-`]*(?:status:\s*superseded\b|superseded(?:_by)?:|supersedes:)", re.IGNORECASE)
SHELL_LANGS = frozenset({"bash", "sh", "shell", "zsh", "fish", "console", "terminal", "powershell", "pwsh", "ps1", "cmd", "bat", "batch"})
COMMAND_LINE_RE = re.compile(r"^\s*(?:\$\s+|>\s+|PS>\s+)?(?:python3?|py|pip3?|npm|npx|pnpm|yarn|git|claude|codex|gemini|cd|curl|wget|powershell|pwsh|bash|docker|uv|node)\s", re.IGNORECASE)
CHECK_WORDS = ("kiểm", "check")  # a heading with one of these holds the one allowed block of commands (RL3)


def doc_type(path: Path, meta: dict) -> str | None:
    """"skill" for SKILL.md; else a `type:` of workflow or rules in the frontmatter; else a rules name (AGENTS.md, CLAUDE.md, GEMINI.md);
    else a file below a folder called workflows/. None when nothing tells (the caller exits 2, FR8.1). Decided by the spelling and the metadata, nothing is opened."""
    name = path.name.casefold()
    if name == "skill.md":
        return "skill"
    declared = meta.get("type") if isinstance(meta, dict) else None
    if declared in ("workflow", "rules"):
        return declared
    if name in RULES_NAMES:
        return "rules"
    if any(part.casefold() == "workflows" for part in Path(os.path.abspath(path)).parent.parts):
        return "workflow"
    return None


def _is_pointer(line: str) -> bool:
    """The history pointer `📜 … CHANGELOG … mốc` that the OpcOS rules require (FR8.3): not a history line. Three finds on one string, linear."""
    low = line.casefold()
    mark = low.find("📜")
    changelog = low.find("changelog", mark) if mark >= 0 else -1
    return changelog >= 0 and low.find("mốc", changelog) >= 0


def _body_start(lines: list) -> int:
    """Index of the first body line: after the closing `---` of a frontmatter that opens on line 1, else 0."""
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return index + 1
    return 0


def _structure(lines: list, start: int) -> tuple:
    """(headings, fences, inside) of the body: headings = [(index, level, text)] outside code fences; fences = [(first index, language,
    [content lines], [heading texts above it, outer first])]; inside = indexes that sit in a fence (marker lines included). One pass, linear."""
    headings, fences, inside, stack = [], [], set(), []
    fence = None  # (marker char run, language, first index, content)
    for index in range(start, len(lines)):
        text = lines[index]
        if fence is not None:
            inside.add(index)
            stripped = text.strip()
            if re.fullmatch(re.escape(fence[0][0]) + "{%d,}" % len(fence[0]), stripped):
                fences.append((fence[2], fence[1], fence[3], fence[4]))
                fence = None
            else:
                fence[3].append(text)
            continue
        opened = C.FENCE_OPEN_LIST_RE.match(text)
        if opened:
            lang = text[opened.end():].strip().split(" ")[0].strip("{}").casefold()
            fence = (opened.group(1), lang, index, [], [h[2] for h in stack])
            inside.add(index)
            continue
        found = HEADING_RE.match(text)
        if found:
            level = len(found.group(1))
            title = found.group(2).rstrip().rstrip("#").rstrip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, index, title))
            headings.append((index, level, title))
    if fence is not None:  # an unclosed fence runs to the end of the file
        fences.append((fence[2], fence[1], fence[3], fence[4]))
    return headings, fences, inside


def _secret_findings(path: Path, lines: list) -> list:
    for number, text in enumerate(lines, 1):
        if fs.secret_in_text(text):
            return [fs.emit("ERROR", "SEC", path, number, "possible hardcoded secret; remove it and rotate the key")]
    return []


def lint_workflow(path: Path, text: str) -> list:
    """WC1 no `Kết luận` line in the first 15 body lines, WC2 no numbered list under a Bước/Steps heading, WC3 no Xong khi/Done when heading (ERROR);
    WC4 more than 300 lines (WARN); SEC a secret (ERROR). `standards/DOC_TYPES.md`, section Workflow."""
    lines = unicodedata.normalize("NFC", text).splitlines()  # a file saved decomposed still says `Kết luận`
    start = _body_start(lines)
    headings, _fences, inside = _structure(lines, start)
    findings = []
    if not any(CONCLUSION_RE.match(lines[i].lstrip()) for i in range(start, min(len(lines), start + CONCLUSION_WINDOW)) if i not in inside):
        findings.append(fs.emit("ERROR", "WC1", path, start + 1, "no `> **Kết luận:**` line in the first %d lines of the body; say first what the workflow does and what comes out" % CONCLUSION_WINDOW))
    stepped = False
    for position, (index, level, title) in enumerate(headings):
        if not any(word in title.casefold() for word in ("bước", "steps")):
            continue
        end = next((h[0] for h in headings[position + 1:] if h[1] <= level), len(lines))
        if any(NUMBERED_RE.match(lines[i]) for i in range(index + 1, end) if i not in inside):
            stepped = True
            break
    if not stepped:
        findings.append(fs.emit("ERROR", "WC2", path, 0, "no numbered list under a heading with `Bước` or `Steps`; write the steps as 1. 2. 3., each one checkable"))
    if not any(word in title.casefold() for _i, _l, title in headings for word in ("xong khi", "done when")):
        findings.append(fs.emit("ERROR", "WC3", path, 0, "no `Xong khi` / `Done when` heading; say how to tell the workflow is finished and where to go back when a check fails"))
    if len(lines) > WORKFLOW_MAX_LINES:
        findings.append(fs.emit("WARN", "WC4", path, WORKFLOW_MAX_LINES + 1, "%d lines, above %d; move the rarely used part to a linked file and say when to read it" % (len(lines), WORKFLOW_MAX_LINES)))
    findings.extend(_secret_findings(path, lines))
    return findings


def _is_command_block(lang: str, content: list) -> bool:
    if lang in SHELL_LANGS:
        return any(line.strip() and not line.strip().startswith("#") for line in content)
    return not lang and any(COMMAND_LINE_RE.match(line) for line in content)


def lint_rules(path: Path, text: str, siblings: set) -> list:
    """RL1 more than 200 lines (WARN); RL2 a history line: «đổi từ bản», «changed from v» or a hash after the word commit, except the `📜 … CHANGELOG … mốc`
    pointer and the `superseded` / `supersedes:` keys (ERROR); RL3 a fenced block of commands outside a heading with kiểm or check (ERROR); RL4 a CLAUDE.md or
    GEMINI.md that does not name AGENTS.md although the folder has one (ERROR); SEC a secret (ERROR). `siblings` = the file names in the same folder."""
    lines = unicodedata.normalize("NFC", text).splitlines()
    findings = []
    if len(lines) > RULES_MAX_LINES:
        findings.append(fs.emit("WARN", "RL1", path, RULES_MAX_LINES + 1, "%d lines, above %d; keep one source file and let the others point to it" % (len(lines), RULES_MAX_LINES)))
    for number, line in enumerate(lines, 1):
        if _is_pointer(line) or SUPERSEDE_RE.match(line):
            continue
        first_commit = COMMIT_RE.search(line)
        if HISTORY_RE.search(line) or (first_commit and HEX_RE.search(line, first_commit.end())):
            findings.append(fs.emit("ERROR", "RL2", path, number, "a rules file holds the rules in force, not their history; move this line to the CHANGELOG and leave a `📜 … CHANGELOG … mốc` pointer"))
    _headings, fences, _inside = _structure(lines, _body_start(lines))
    for first, lang, content, above in fences:
        if _is_command_block(lang, content) and not any(word in title.casefold() for title in above for word in CHECK_WORDS):
            findings.append(fs.emit("ERROR", "RL3", path, first + 1, "block of commands outside a heading with `kiểm` or `check`; commands belong in the README of their component (one install line inside a sentence is fine)"))
    if path.name.casefold() in ("claude.md", "gemini.md") and "agents.md" in {s.casefold() for s in siblings} and not any("AGENTS.md" in line for line in lines):
        findings.append(fs.emit("ERROR", "RL4", path, 0, "%s does not name AGENTS.md although the folder has one; load it with @AGENTS.md or point to it" % path.name))
    findings.extend(_secret_findings(path, lines))
    return findings


def siblings_of(path: Path) -> set:
    """The file names in the folder of `path`, for RL4. A folder that cannot be listed gives an empty set (RL4 then stays quiet)."""
    try:
        with os.scandir(path.parent) as scan:
            return {entry.name for entry in scan}
    except OSError:
        return set()


def read_document(path: Path, markers: tuple = C.CLOUD_MARKERS, anchor: Path | None = None) -> tuple:
    """(text, None) or (None, why not). A file in a secret or cloud zone, a link, a cloud placeholder, a file over DOCTOR_MAX_FILE_BYTES or one that is not UTF-8 is not read."""
    problem = fs.input_file_problem(path, markers)
    if problem:
        return None, problem
    if fs.is_link(path):
        return None, "is a symlink or junction; it is not read"
    if fs.path_is_cloud(path):
        return None, "is a cloud placeholder; it is not read"
    try:
        text, too_big = fs.read_capped(path, C.DOCTOR_MAX_FILE_BYTES, anchor=fs.anchor_for(path) if anchor is None else anchor)
    except (OSError, UnicodeError) as exc:
        return None, "cannot be read as UTF-8 text: %s" % (getattr(exc, "strerror", None) or type(exc).__name__)
    if too_big:
        return None, "is larger than %d bytes; it is not read" % C.DOCTOR_MAX_FILE_BYTES
    return text, None


def lint_document(kind: str, path: Path, text: str) -> list:
    """The findings of one workflow or rules file; `kind` is what `doc_type` said."""
    if kind == "workflow":
        return lint_workflow(path, text)
    return lint_rules(path, text, siblings_of(path))


def plugin_documents(plugin: Path, markers: tuple = C.CLOUD_MARKERS) -> list:
    """The documents `doctor --docs` checks in one plugin folder (FR8.4) as [(path, default type)]: the rules files at its root and every .md file below its
    workflows/ folder. Listing only; nothing is opened here. A link or a placeholder is listed and refused later by `read_document`."""
    found = []
    try:
        with os.scandir(plugin) as scan:
            entries = sorted(scan, key=lambda e: e.name)
    except OSError:
        return found
    for entry in entries:
        low = entry.name.casefold()
        try:
            if low in RULES_NAMES and (entry.is_file(follow_symlinks=False) or entry.is_symlink()):
                found.append((Path(entry.path), "rules"))
            elif low == "workflows" and entry.is_dir(follow_symlinks=False) and not fs.zone_named(entry.name, markers):
                tree, _links, dirs, _cloud, _cut = fs.walk_files(Path(entry.path), markers)
                found.extend((p, "workflow") for p in tree if p.suffix.casefold() == ".md" and p not in dirs)
        except OSError:
            continue
    return found


def docs_report(plugins: list, markers: tuple = C.CLOUD_MARKERS) -> list:
    """The `docs` list of the doctor report (FR8.4): one {path, type, codes} per document. `codes` has the same record as a skill's (code, level, file, line,
    message); `file` is relative to the plugin folder. A document that is not read gets one WARN `INPUT` saying why. The type comes from `doc_type` after
    the frontmatter is read, else from where the file was found."""
    report = []
    for plugin in plugins:
        for path, default in plugin_documents(plugin, markers):
            text, problem = read_document(path, markers)
            if problem:
                kind, findings = default, [fs.emit("WARN", "INPUT", path, 0, "not checked: %s" % problem)]
            else:
                meta, _issues, _end = fs.parse_frontmatter(text, path)
                kind = doc_type(path, meta)
                kind = kind if kind in ("workflow", "rules") else default
                findings = lint_document(kind, path, text)
            codes = [{"code": f["code"], "level": f["level"], "file": Path(f["path"]).relative_to(plugin).as_posix(), "line": f["line"], "message": f["message"]} for f in findings]
            report.append({"path": os.fspath(path).replace("\\", "/"), "type": kind, "codes": codes})
    return report
