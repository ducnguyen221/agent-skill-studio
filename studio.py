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
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
import zipfile
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
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")  # [text](target) -> text
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
CODE_SPAN_RE = re.compile(r"(`+).+?\1")
URL_RE = re.compile(r"https?://\S+")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->")
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
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
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
    found.append(eval_dir.resolve().parent.parent / "skills")
    return found


def export_fixture_source(eval_dir: Path, relative: str) -> tuple[Path | None, list[str], str]:
    """Resolve a fixture path from cases.json to (source, export-name parts, problem). Only plain relative paths inside eval_dir, no links."""
    posix = relative.replace("\\", "/")
    parts = [x for x in posix.split("/")]
    if not posix or posix.startswith("/") or re.match(r"^[A-Za-z]:", posix) or any(x in ("", ".", "..") for x in parts):
        return None, [], "unsafe fixture path '%s' (must be a plain relative path inside the eval folder)" % relative
    current = eval_dir
    for part in parts:
        current = current / part
        if is_link(current):
            return None, [], "fixture '%s' goes through a symlink or junction; refusing to copy it" % relative
    if not current.is_file() or not valid_resolved_under(current, eval_dir):
        return None, [], "missing/outside eval fixture '%s'" % relative
    return current, (parts[1:] if parts[0] == "fixtures" and len(parts) > 1 else parts), ""


def export_agentskills(eval_dir: Path, skill_name: str, out_root: Path, force: bool = False) -> tuple[int, list[dict], dict]:
    """Write <out_root>/<skill_name>/evals/evals.json (agentskills schema, SPEC 9.6) plus evals/files/ from evals/<skill>/cases.json.

    Returns (exit code, findings, {"exported", "excluded_negative", "path"}). 1 = refused (nothing written), 2 = bad destination.
    Only the positive cases (should_trigger true) are exported; nothing is deleted, and --force only overwrites the files this function generates."""
    eval_dir, out_root = Path(eval_dir), Path(out_root)
    stats = {"exported": 0, "excluded_negative": 0, "path": ""}

    def refuse(code: int, ident: str, message: str, path: Path = eval_dir):
        return code, [emit("ERROR", ident, path, 0, message)], stats

    dest = out_root / skill_name
    if any(valid_resolved_under(dest, skills) for skills in export_skills_dirs(eval_dir)):
        return refuse(2, "EX1", "export destination must not be under skills/ (it would ship test data inside the skill): %s" % out_root, out_root)
    if not EXPORT_NAME_RE.match(skill_name or ""):
        return refuse(1, "EX2", "skill name '%s' is not a plain lowercase-hyphen name" % skill_name)
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
    sources: dict[str, Path] = {}
    evals = []
    for number, case in enumerate(positive, 1):
        names = []
        for relative in case.get("fixtures", []):
            source, parts, problem = export_fixture_source(eval_dir, relative)
            if source is None:
                return refuse(1, "EX4", problem, eval_dir / "cases.json")
            name = "/".join(parts)
            if name in sources and sources[name] != source:
                return refuse(1, "EX7", "fixture names collide after export: '%s' is both %s and %s" % (name, sources[name], source), eval_dir / "cases.json")
            sources[name] = source
            names.append("evals/files/" + name)
        evals.append({"id": number, "prompt": case["prompt"], "expected_output": "; ".join(case["expected_behaviors"]), "files": names, "assertions": list(case["expected_behaviors"])})
    evals_dir = dest / "evals"
    target = evals_dir / "evals.json"
    copies = {evals_dir / "files" / Path(*name.split("/")): source for name, source in sources.items()}
    for owned in [dest, evals_dir, evals_dir / "files"] + [t.parent for t in copies] + [target] + list(copies):
        if is_link(owned):
            return refuse(1, "EX6", "export destination goes through a symlink or junction: %s" % owned, owned)
    for t, source in copies.items():
        if t.exists() and source.exists() and os.path.samefile(t, source):
            return refuse(1, "EX6", "export destination is the source fixture itself: %s" % t, t)
    clash = [x for x in [target] + list(copies) if x.exists()]
    if clash and not force:
        return refuse(1, "EX5", "export file exists: %s; choose another --out or explicitly --force" % clash[0], clash[0])
    try:
        for t, source in copies.items():
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, t)
        evals_dir.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"skill_name": skill_name, "evals": evals}, ensure_ascii=False, indent=2) + "\n")
    except OSError as exc:
        return refuse(1, "EX8", "cannot write export: %s" % exc, out_root)
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
        opened = FENCE_OPEN_RE.match(text)
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
        prose = HTML_COMMENT_RE.sub(" ", text)
        prose = CODE_SPAN_RE.sub(" ", prose)
        prose = MD_LINK_RE.sub(" ", prose)
        prose = URL_RE.sub(" ", prose)
        match = FORCE_RE.search(prose)
        if match and not REASON_RE.search(text):
            findings.append(emit("WARN", "CT10", manifest, lineno,
                                 "'%s' without a reason on the same line (SK-14); state why, or mark a deliberately strict step with %s ... %s"
                                 % (match.group(1), STRICT_OPEN, STRICT_CLOSE)))
    if strict:
        findings.append(emit("WARN", "CT10", manifest, strict_line,
                             "strict block not closed: %s has no matching %s, so the rest of the body was not linted (SK-14)"
                             % (STRICT_OPEN, STRICT_CLOSE)))
    return findings


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
        opened = FENCE_OPEN_RE.match(text)
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
        prose = HTML_COMMENT_RE.sub(" ", text)
        prose = CODE_SPAN_RE.sub(" ", prose)
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
        start = 0
        for cut in list(SENTENCE_SPLIT_RE.finditer(joined)) + [None]:
            end = cut.start() if cut else len(joined)
            if joined[start:end].split():
                sentences.append(([rel for at, rel in starts if at <= start][-1], len(joined[start:end].split())))
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


def lint_vietnamese(meta: dict, body: str, body_start: int, manifest: Path) -> list:
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
    try:
        front = manifest.read_text(encoding="utf-8").splitlines()[:body_start]
    except (OSError, UnicodeError):
        front = []

    def front_line(label: str, default: int) -> int:
        key = label.rsplit(".", 1)[-1]
        return next((i + 1 for i, x in enumerate(front) if x.lstrip().startswith(key + ":")), default)

    def accented(value) -> bool:
        return isinstance(value, str) and _vi_counts(HTML_COMMENT_RE.sub(" ", value))[1] > 0

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
    desc = HTML_COMMENT_RE.sub(" ", meta["description"]) if isinstance(meta.get("description"), str) else None
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


def validate_skill(folder: Path, eval_root: Path | None = None, require_evals: bool = False, target: str = "portable") -> list[dict]:
    folder = folder.resolve()
    manifest = folder / "SKILL.md"
    if not manifest.is_file():
        return [emit("ERROR", "FM1", manifest, 0, "SKILL.md is missing")]
    try:
        text = manifest.read_text(encoding="utf-8")
    except UnicodeError:
        return [emit("ERROR", "FM1", manifest, 0, "SKILL.md must be UTF-8 text")]
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
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 1024 or re.search(r"<[^>]+>", desc or ""):
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
        if claude and key in CLAUDE_CODE_KEYS:
            at = next((i + 1 for i, x in enumerate(all_lines[:body_start]) if x.startswith(key + ":")), 2)
            findings.append(emit("WARN", "FM6", manifest, at, "frontmatter key '%s' is Claude Code only; claude.ai and the API reject it with a hard error" % key))
        else:
            findings.append(emit("ERROR", "FM4", manifest, 2, "unknown frontmatter key '%s' for target %s; allowed keys: %s; use metadata or a target adapter" % (key, target, ", ".join(allowed))))
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
    tokens = estimate_tokens(body)
    if tokens > BODY_TOKEN_MAX:
        findings.append(emit("WARN", "ST2", manifest, body_start + 1, "Skill body is about %d tokens (estimate, not a tokenizer); keep it under %d and move detail to references" % (tokens, BODY_TOKEN_MAX)))
    findings.extend(lint_forcing_words(body, body_start, manifest))
    findings.extend(lint_contents(manifest, body.splitlines(), "skill_body", body_start))
    findings.extend(lint_vietnamese(meta, body, body_start, manifest))
    if re.search(r"<!--\s*STUDIO-DRAFT|\[FILL:|\bTODO\b|\bFIXME\b", body, re.IGNORECASE):
        findings.append(emit("WARN", "CT9", manifest, body_start + 1, "draft marker/TODO/FIXME remains; do not ship unreviewed scaffold"))
    if re.search(r"(?i)(show|write out|transcribe|echo)\s+(your\s+)?(private\s+)?(chain.of.thought|internal reasoning|hidden reasoning)", body):
        findings.append(emit("WARN", "NM2", manifest, body_start + 1, "possible request to disclose private model reasoning"))
    refs_linked = set()
    for match in LINK_RE.finditer(body):
        link = match.group(1).strip().strip('<>')
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        link = link.split('#')[0].split('?')[0]
        if not link:
            continue
        resolved = folder / link
        line = body_start + body[:match.start()].count("\n") + 1
        if not valid_resolved_under(resolved, folder):
            findings.append(emit("ERROR", "ST6", manifest, line, "reference escapes Skill folder: '%s'" % link))
        elif not resolved.exists():
            findings.append(emit("ERROR", "ST6", manifest, line, "missing referenced resource '%s'" % link))
        else:
            try:
                refs_linked.add(resolved.resolve())
            except OSError:
                pass
    ref_dir = folder / "references"
    if ref_dir.is_dir():
        for p in ref_dir.rglob("*.md"):
            if p.is_symlink():
                findings.append(emit("ERROR", "SEC", p, 0, "symlink in reference tree may escape package; replace with real file"))
                continue
            if p.resolve() not in refs_linked:
                findings.append(emit("WARN", "ST4", p, 0, "reference Markdown is not directly linked from SKILL.md"))
            try:
                ref_lines = p.read_text(encoding="utf-8").splitlines()
            except UnicodeError:
                findings.append(emit("ERROR", "ST6", p, 0, "reference must be UTF-8"))
                continue
            findings.extend(lint_contents(p, ref_lines, "reference"))
    scripts = folder / "scripts"
    if scripts.is_dir():
        for script in scripts.iterdir():
            if script.is_file() and script.suffix in {".py", ".sh", ".js", ".ts"} and script.name not in body:
                findings.append(emit("WARN", "SC3", script, 0, "script not mentioned in SKILL.md; document whether to run or read"))
    for p in folder.rglob('*'):
        if p.is_symlink():
            findings.append(emit("ERROR", "SEC", p, 0, "symlinks are not portable/safe in distributed skill packages"))
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
    for p in folder.rglob("*"):
        rel = p.relative_to(folder)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_symlink():
            findings.append(emit("ERROR", "SEC", p, 0, "cannot package symlink"))
            continue
        if not p.is_file():
            continue
        if p.name in REJECT_NAMES or p.name.startswith(".env.") or p.suffix.lower() in REJECT_SUFFIXES:
            findings.append(emit("ERROR", "SEC", p, 0, "secret/credential-like file must not be shipped"))
            continue
        if p.stat().st_size > 25 * 1024 * 1024:
            findings.append(emit("ERROR", "PACK", p, 0, "file exceeds 25 MB; review before shipping"))
            continue
        if p.suffix.lower() in {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".sh"}:
            try:
                raw = p.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                raw = ""
            if ("-----BEGIN " + "PRIVATE KEY-----") in raw or re.search(r"\b(?:sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})\b", raw):
                findings.append(emit("ERROR", "SEC", p, 0, "possible hardcoded secret in package"))
        files.append(p)
    return files, findings


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
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, arcname=str(Path(folder.name) / p.relative_to(folder)))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print("Packaged %d runtime files -> %s\nSHA256: %s\nExcluded: evals/, tests/, secrets, caches. Model evaluation status is unchanged." % (len(files), target, digest))
    return 0


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
    dest = skill_root / folder.name
    if dest.resolve() == folder or valid_resolved_under(dest, folder):
        print("ERROR: destination is the source Skill or nested under it; refusing self-overwrite", file=sys.stderr)
        return 1
    if dest.exists() and not args.force:
        print("ERROR: %s exists; no changes made. Use --force only if you intend replacement." % dest, file=sys.stderr)
        return 1
    if dest.exists() and args.force:
        # Refuse symlink/junction targets and back up rather than silently erasing.
        if is_link(dest):
            print("ERROR: symlink destination refused", file=sys.stderr)
            return 1
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = dest.with_name(dest.name + ".backup-" + stamp)
        if backup.exists():
            print("ERROR: backup collision", file=sys.stderr)
            return 1
        dest.rename(backup)
        print("Existing installation backed up to %s" % backup)
    dest.mkdir(parents=True, exist_ok=False)  # creates skill_root itself, never the agent's config parent
    for source in files:
        destination = dest / source.relative_to(folder)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
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
    p.add_argument("--out", help="export destination (default %s); must not be under skills/" % EXPORT_DEFAULT_OUT)
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
    p.add_argument("--force", action="store_true", help="back up and replace existing install")
    p.set_defaults(func=cmd_install)
    p = sub.add_parser("sync-template", help="sync source template to packaged Skill asset")
    p.add_argument("--check", action="store_true", help="verify byte-identical mirror without modifications")
    p.set_defaults(func=cmd_sync)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
