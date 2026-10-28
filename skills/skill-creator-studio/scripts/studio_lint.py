"""Advisory lint of a SKILL.md body and references: forcing words, unclosed comments, Vietnamese prose rules, contents lists (SPR-02 TK4b).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from pathlib import Path

import studio_const as C
import studio_fs as fs


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
    vietnamese = bool(letters) and sum(c in C.VI_CHARS for c in letters) / len(letters) > 0.1
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
        opened = (C.FENCE_OPEN_LIST_RE if list_context else C.FENCE_OPEN_RE).match(text)
        if opened:
            fence = opened.group(1)
            prev_blank = False
            continue
        if C.STRICT_OPEN in text:
            strict, strict_line = True, lineno
        if strict:
            if C.STRICT_CLOSE in text:
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
            list_context = bool(C.LIST_ITEM_RE.match(text))
        prev_blank = False
        if stripped.startswith("|"):
            continue
        prose = fs.strip_html_comments(text)
        prose = fs.strip_code_spans(prose)
        prose = C.MD_LINK_RE.sub(" ", prose)
        prose = C.URL_RE.sub(" ", prose)
        match = C.FORCE_RE.search(prose)
        if match and not C.REASON_RE.search(prose):
            findings.append(fs.emit("WARN", "CT10", manifest, lineno,
                                 "'%s' without a reason on the same line (SK-14); state why, or mark a deliberately strict step with %s ... %s"
                                 % (match.group(1), C.STRICT_OPEN, C.STRICT_CLOSE)))
    if strict:
        findings.append(fs.emit("WARN", "CT10", manifest, strict_line,
                             "strict block not closed: %s has no matching %s, so the rest of the body was not linted (SK-14)"
                             % (C.STRICT_OPEN, C.STRICT_CLOSE)))
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
        opened = (C.FENCE_OPEN_LIST_RE if list_context else C.FENCE_OPEN_RE).match(text)
        if opened:
            fence = opened.group(1)
            continue
        if text.strip() and not text.startswith(("    ", "\t")):
            list_context = bool(C.LIST_ITEM_RE.match(text))
        rest = fs.strip_html_comments(fs.strip_code_spans(text))
        if "<!--" in rest:
            opened_at = body_start + offset + 1
    if opened_at:
        return [fs.emit("WARN", "CT11", manifest, opened_at, "HTML comment opened here is never closed with '-->'; the rest of the body is read as comment text (language and SK-14 lints skip it)")]
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
        opened = (C.FENCE_OPEN_LIST_RE if list_context else C.FENCE_OPEN_RE).match(text)
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
            list_context = bool(C.LIST_ITEM_RE.match(text))
        prev_blank = False
        if stripped.startswith("|") or C.VI_OK_MARK in text:
            continue
        prose = fs.strip_html_comments(text)
        prose = fs.strip_code_spans(prose)
        if "<!--" in prose:  # a comment that continues on the next lines
            prose, in_comment = prose[:prose.index("<!--")], True
        prose = C.MD_LINK_RE.sub(r"\1", prose)
        prose = C.URL_RE.sub(" ", prose)
        if prose.strip():
            found.append((offset + 1, prose))
    return found


def _vi_counts(text: str) -> tuple[int, int]:
    """(letters, letters with a Vietnamese diacritic), counted on the NFC form so an NFD body is still recognised."""
    letters = [c for c in unicodedata.normalize("NFC", text).lower() if c.isalpha()]
    return len(letters), sum(c in C.VI_CHARS for c in letters)


def _vi_lang(lines: list[tuple[int, str]]) -> str:
    letters = accents = 0
    for _, text in lines:
        count, accented = _vi_counts(text)
        letters, accents = letters + count, accents + accented
    return "vi" if letters and accents / letters >= C.VI_ACCENT_RATIO else "en"


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
        joined = C.SENTENCE_ABBREV_RE.sub(lambda m: m.group(1) + "․", " ".join(parts))
        offsets = [at for at, _ in starts]
        start = 0
        for cut in list(C.SENTENCE_SPLIT_RE.finditer(joined)) + [None]:
            end = cut.start() if cut else len(joined)
            if joined[start:end].split():
                sentences.append((starts[bisect.bisect_right(offsets, start) - 1][1], len(joined[start:end].split())))
            if cut:
                start = cut.end()
        buf.clear()

    prev = -1
    for rel, text in lines:
        item = bool(C.LIST_ITEM_RE.match(text))
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
    VI5 a '## ' section of at least VI5_SECTION_MIN_LETTERS letters with under VI5_ACCENT_MIN diacritics, unless the sections under
    VI5_ACCENT_MIN hold more than VI5_ENGLISH_BODY_SHARE of the prose letters (code and tables are not prose): a mostly English body
    is not reported section by section (FR14.1)."""
    lines = prose_lines(body)
    if _vi_lang(lines) != "vi":
        return []
    findings: list[dict] = []
    for rel, text in lines:
        if unicodedata.normalize("NFC", text) != text:
            findings.append(fs.emit("WARN", "VI1", manifest, body_start + rel,
                                 "body is not Unicode NFC (first deviating line; later lines may be too); re-save the text in NFC (V09)"))
            break
    for rel, text in lines:
        date = C.NON_ISO_DATE_RE.search(text)
        if date:
            findings.append(fs.emit("WARN", "VI2", manifest, body_start + rel, "date '%s' is not ISO; write yyyy-mm-dd (V11)" % date.group(0)))
    for rel, words in _vi_sentences(lines):
        if words > C.VI_SENTENCE_MAX:
            findings.append(fs.emit("WARN", "VI3", manifest, body_start + rel,
                                 "sentence has %d words (>%d); split it, aim for 25 or fewer (V03)" % (words, C.VI_SENTENCE_MAX)))
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
        return isinstance(value, str) and _vi_counts(fs.strip_html_comments(value))[1] > 0

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
        if accented(value) and not (at <= len(front) and C.VI_OK_MARK in front[at - 1]):
            findings.append(fs.emit("WARN", "VI4", manifest, at, "frontmatter '%s' has Vietnamese letters; keep frontmatter values English (V13)" % label))
    desc = fs.strip_html_comments(meta["description"]) if isinstance(meta.get("description"), str) else None
    at = front_line("description", 3)
    if accented(desc) and not C.VI_TRIGGER_RE.search(desc) and not (at <= len(front) and C.VI_OK_MARK in front[at - 1]):
        findings.append(fs.emit("WARN", "VI4", manifest, at,
                             "description has Vietnamese letters but no 'Use when' trigger phrase; write it in English and add Vietnamese only as extra trigger words (V13)"))
    sections: list = []  # [line, letters, letters with a diacritic, title] per '## ' section of the prose
    section = None
    for rel, text in lines + [(0, "# end")]:
        if re.match(r"^#{1,2}\s+\S", text):
            if section:
                sections.append(section)
            section = [rel, 0, 0, text.strip("# ").strip()] if re.match(r"^##\s", text) else None
        elif section:
            count, with_accent = _vi_counts(text)
            section[1], section[2] = section[1] + count, section[2] + with_accent
    prose_letters = sum(_vi_counts(text)[0] for _, text in lines)
    english = sum(sec[1] for sec in sections if sec[1] and sec[2] / sec[1] < C.VI5_ACCENT_MIN)
    if prose_letters and english / prose_letters > C.VI5_ENGLISH_BODY_SHARE:
        return findings  # a body that is mostly English (FR14.1): not reported section by section
    for sec in sections:
        if sec[1] >= C.VI5_SECTION_MIN_LETTERS and sec[2] / sec[1] < C.VI5_ACCENT_MIN:
            findings.append(fs.emit("WARN", "VI5", manifest, body_start + sec[0],
                                 "section '%s' has %d letters and almost no Vietnamese diacritics; one language per skill, write it in Vietnamese (V14)"
                                 % (sec[3], sec[1])))
    return findings


def lint_contents(path: Path, lines: list, kind: str, offset: int = 0) -> list:
    """FR15: Contents rules. kind 'reference' -> ST5, 'skill_body' -> ST7; `offset` = lines before lines[0]."""
    code = "ST5" if kind == "reference" else "ST7"
    limit = C.REF_TOC_LINES if kind == "reference" else C.BODY_TOC_LINES
    findings: list[dict] = []
    norm = [unicodedata.normalize("NFC", x) for x in lines]
    start = next((i for i, x in enumerate(norm[:C.CONTENTS_WINDOW]) if C.CONTENTS_RE.match(x.strip())), None)
    if start is None:
        if len(lines) > limit:
            level = "ERROR" if kind == "reference" else "WARN"
            what = "reference" if kind == "reference" else "SKILL.md body"
            findings.append(fs.emit(level, code, path, offset + 1, "%s >%d lines needs a '## Contents' (or '## Mục lục') in its first %d lines" % (what, limit, C.CONTENTS_WINDOW)))
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
            entries.append((i, C.MD_LINK_RE.sub(r"\1", s[2:]).split(" — ")[0].strip()))
    if len(entries) > C.CONTENTS_MAX:
        findings.append(fs.emit("WARN", code, path, offset + start + 1, "Contents has %d entries; keep it to %d or fewer" % (len(entries), C.CONTENTS_MAX)))
    for i, name in entries:
        if name not in headings:
            findings.append(fs.emit("WARN", code, path, offset + i + 1, "Contents entry '%s' matches no '## ' heading in this file" % name))
    return findings
