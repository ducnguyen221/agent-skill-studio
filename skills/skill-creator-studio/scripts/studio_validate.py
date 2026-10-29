"""The skill validator: `validate_skill` runs every rule on one skill folder and `print_findings` prints the result (SPR-02 TK4b).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
"""

from __future__ import annotations

import bisect
import os
import re
from pathlib import Path

import studio_const as C
import studio_doctypes as doctypes
import studio_evals as evals
import studio_fs as fs
import studio_lint as lint


def budget_desc(meta: dict) -> str:
    """The description as `get_field` of bootstrap/measure-skill-budget.py reads it: the lines of a block scalar joined by one space (BG1, `budget`)."""
    desc = meta.get("description")
    return " ".join(desc.split("\n")) if isinstance(desc, str) else ""


def desc_chars_like_budget(meta: dict) -> int:
    """Characters of the description measured like measure-skill-budget.py; only BG1 uses it, DS1 keeps its own count."""
    return len(budget_desc(meta))


def validate_skill(folder: Path, eval_root: Path | None = None, require_evals: bool = False, target: str = "portable",
                   profile: str = "portable", allow_links_under: Path | None = None, max_file_bytes: int | None = None,
                   skip_markers: tuple = (), anchor: Path | None = None) -> list[dict]:
    """Findings for one skill. profile "opcos" (doctor): an existing link that leaves the skill but stays under `allow_links_under`
    is a WARN ST6, the OPCOS_PROVENANCE_KEYS are WARN FM4, and no `metadata.opcos_*` key is a NOTE MD1. ST3 and ST8 apply to every profile.
    `max_file_bytes` (doctor passes DOCTOR_MAX_FILE_BYTES): a SKILL.md or reference above it is not read, WARN SZ1. `skip_markers` extend CLOUD_MARKERS.
    A symlink, junction or cloud placeholder inside the skill is reported (SEC, SZ2) and never opened, listed or followed. Every file is opened with the folders
    from `anchor` (the scan root; default the skill folder) down to it pinned, so a folder swapped for a link after the checks is not read through (SPR-05 FR2.1)."""
    markers = C.CLOUD_MARKERS + tuple(skip_markers)
    given = folder / "SKILL.md"
    problem = fs.input_file_problem(given, markers)  # the spelling given first: a zone folder is not resolved, stat-ed or read (FR10.1)
    if problem:
        return [fs.emit("ERROR", "INPUT", given, 0, "SKILL.md %s" % problem)]
    folder = folder.resolve()
    pin_from = folder if anchor is None else Path(os.path.abspath(os.fspath(anchor)))
    if not fs.lexically_inside(folder, pin_from):  # resolve() followed a link out of the scan root: nothing there is read
        return [fs.emit("ERROR", "INPUT", given, 0, "SKILL.md lies behind a link that leaves the scan root; not read")]
    manifest = folder / "SKILL.md"
    problem = fs.input_file_problem(manifest, markers) if manifest != given else None  # then the real path
    if not problem and fs.is_link(manifest):  # open() follows a link: refused, as `package` does (ensure_distributable)
        problem = "is a symlink or junction; not read"
    if problem:
        return [fs.emit("ERROR", "INPUT", manifest, 0, "SKILL.md %s" % problem)]
    if not manifest.is_file():
        return [fs.emit("ERROR", "FM1", manifest, 0, "SKILL.md is missing")]
    try:
        text, too_big = fs.read_capped(manifest, max_file_bytes, single_link=True, anchor=pin_from)
    except fs.UnsafeOpen as exc:  # a link raced in, or a second name (hard link): refused before a byte is read
        return [fs.emit("ERROR", "INPUT", manifest, 0, "SKILL.md %s; not read" % ("has more than one name (hard link)" if "hard link" in str(exc) else "is a link or not a plain file"))]
    except UnicodeError:
        return [fs.emit("ERROR", "FM1", manifest, 0, "SKILL.md must be UTF-8 text")]
    if too_big:
        return [fs.emit("ERROR", "SZ1", manifest, 0, "SKILL.md is larger than %d bytes; not read or linted, so it cannot pass" % max_file_bytes)]
    claude = target == "claude-code"
    meta, findings, body_start = fs.parse_frontmatter(text, manifest, C.CLAUDE_CODE_KEYS if claude else frozenset())
    all_lines = text.splitlines()
    name = meta.get("name")
    desc = meta.get("description")
    if not isinstance(name, str) or not C.NAME_RE.fullmatch(name) or len(name) > 64:
        findings.append(fs.emit("ERROR", "FM2", manifest, 2, "name must be lowercase kebab-case, 1–64 chars and without '--'"))
    elif name != folder.name:
        findings.append(fs.emit("ERROR", "FM2", manifest, 2, "name '%s' differs from folder '%s'" % (name, folder.name)))
    if isinstance(name, str):
        word = next((w for w in C.RESERVED_NAME_WORDS if w in name), None)
        if word:
            findings.append(fs.emit("ERROR", "FM5", manifest, 2, "name must not contain the reserved word '%s'" % word))
        elif claude and name in C.CLAUDE_CODE_RESERVED_NAMES:
            findings.append(fs.emit("ERROR", "FM5", manifest, 2, "name '%s' is reserved by Claude Code" % name))
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 1024 or fs.has_xml_tag(desc or ""):
        findings.append(fs.emit("ERROR", "DS1", manifest, 3, "description must be a nonempty string <=1024 chars without XML tags"))
    elif not re.search(r"(?i)\b(use when|when to use|used when|for tasks involving)\b", desc):
        findings.append(fs.emit("WARN", "DS3", manifest, 3, "description should describe when to invoke the Skill, e.g. 'Use when ...'"))
    elif re.match(r"(?i)^\s*(i can|you can|i will|we can)\b", desc):
        findings.append(fs.emit("WARN", "DS2", manifest, 3, "prefer third-person description e.g. 'Validates CSV...'"))
    if isinstance(desc, str):
        trigger = C.TRIGGER_RE.search(desc)
        if trigger and trigger.start() >= C.TRIGGER_LATEST:
            findings.append(fs.emit("WARN", "DS4", manifest, 3, "trigger phrase starts at character %d; put 'Use when ...' inside the first %d characters" % (trigger.start() + 1, C.TRIGGER_LATEST)))
        listing = len(desc) + (len(meta["when_to_use"]) if isinstance(meta.get("when_to_use"), str) else 0)
        if claude and listing > C.LISTING_MAX:
            findings.append(fs.emit("WARN", "DS5", manifest, 3, "description + when_to_use is %d chars; Claude Code truncates the skill listing at %d" % (listing, C.LISTING_MAX)))
    if profile == "opcos" and desc_chars_like_budget(meta) > C.OPCOS_DESC_CHARS:
        findings.append(fs.emit("WARN", "BG1", manifest, 3, "description is %d chars (>%d, the OpcOS budget); every session loads it, shorten it" % (desc_chars_like_budget(meta), C.OPCOS_DESC_CHARS)))
    allowed = sorted(C.PORTABLE_KEYS | C.CLAUDE_CODE_KEYS) if claude else sorted(C.PORTABLE_KEYS)
    for key in meta:
        if key in C.PORTABLE_KEYS:
            continue
        at = next((i + 1 for i, x in enumerate(all_lines[:body_start]) if x.startswith(key + ":")), 2)
        if claude and key in C.CLAUDE_CODE_KEYS:
            findings.append(fs.emit("WARN", "FM6", manifest, at, "frontmatter key '%s' is Claude Code only; claude.ai and the API reject it with a hard error" % key))
        elif profile == "opcos" and key in C.OPCOS_PROVENANCE_KEYS:
            findings.append(fs.emit("WARN", "FM4", manifest, at, "provenance key '%s' is an OpcOS convention, not portable; move it under metadata before publishing" % key))
        else:
            findings.append(fs.emit("ERROR", "FM4", manifest, at, "unknown frontmatter key '%s' for target %s; allowed keys: %s; use metadata or a target adapter" % (key, target, ", ".join(allowed))))
    if profile == "opcos" and not (isinstance(meta.get("metadata"), dict) and any(k.startswith("opcos_") for k in meta["metadata"])):
        findings.append(fs.emit("NOTE", "MD1", manifest, 2, "no metadata.opcos_* key; OpcOS registry fields are optional"))
    extra = lint.frontmatter_extra_len(all_lines, body_start)
    if extra > C.FRONTMATTER_EXTRA_MAX:
        findings.append(fs.emit("WARN", "FM8", manifest, 1, "frontmatter outside description is %d chars (>%d); move detail to the body or references" % (extra, C.FRONTMATTER_EXTRA_MAX)))
    if "metadata" in meta and (not isinstance(meta["metadata"], dict) or any(not isinstance(v, str) for v in meta["metadata"].values())):
        findings.append(fs.emit("ERROR", "FM4", manifest, 0, "metadata must be a mapping of string keys to string values"))
    if "compatibility" in meta and len(str(meta["compatibility"])) > 500:
        findings.append(fs.emit("ERROR", "FM4", manifest, 0, "compatibility max length is 500 chars"))
    body = "\n".join(all_lines[body_start:])
    if len(body.splitlines()) >= 500:
        findings.append(fs.emit("WARN", "ST1", manifest, body_start + 1, "Skill body should be under 500 lines (best-practice, not spec hard limit)"))
    body_bytes = len(body.encode("utf-8"))
    if body_bytes > C.CODEX_BODY_MAX_BYTES:
        findings.append(fs.emit("WARN", "ST3", manifest, body_start + 1, "Skill body is %d bytes (>%d, the Codex 0.147 limit); move detail to references (standards/SOURCE_TRACEABILITY.md A16)" % (body_bytes, C.CODEX_BODY_MAX_BYTES)))
    tokens = lint.estimate_tokens(body)
    if tokens > C.BODY_TOKEN_MAX:
        findings.append(fs.emit("WARN", "ST2", manifest, body_start + 1, "Skill body is about %d tokens (estimate, not a tokenizer); keep it under %d and move detail to references" % (tokens, C.BODY_TOKEN_MAX)))
    findings.extend(lint.lint_forcing_words(body, body_start, manifest))
    findings.extend(lint.lint_unclosed_comment(body, body_start, manifest))
    findings.extend(lint.lint_contents(manifest, body.splitlines(), "skill_body", body_start))
    findings.extend(lint.lint_vietnamese(meta, body, body_start, manifest, all_lines[:body_start]))
    if re.search(r"<!--\s*STUDIO-DRAFT|\[FILL:|\bTODO\b|\bFIXME\b", body, re.IGNORECASE):
        findings.append(fs.emit("WARN", "CT9", manifest, body_start + 1, "draft marker/TODO/FIXME remains; do not ship unreviewed scaffold"))
    if re.search(r"(?i)(show|write out|transcribe|echo)\s+(your\s+)?(private\s+)?(chain.of.thought|internal reasoning|hidden reasoning)", body):
        findings.append(fs.emit("WARN", "NM2", manifest, body_start + 1, "possible request to disclose private model reasoning"))
    refs_linked = set()
    newlines: list | None = None  # offsets of "\n" in the body, built the first time a finding needs a line number
    verdicts: dict = {}  # link text -> (level, message) or (None, resolved path): one check per distinct target

    def line_of(offset: int) -> int:
        nonlocal newlines
        if newlines is None:
            newlines = [m.start() for m in re.finditer("\n", body)]
        return body_start + bisect.bisect_left(newlines, offset) + 1

    def classify(link: str) -> tuple:
        if C.ABSOLUTE_LINK_RE.match(link) or link.startswith(("/", "\\")):  # UNC, drive, file:, smb:, rooted: never resolved, stat-ed or opened (Windows would authenticate to a share)
            return "ERROR", "reference escapes Skill folder: absolute or UNC link not opened: '%s'" % link
        resolved = folder / link
        if not fs.lexically_inside(resolved, folder) and fs.zone_reason(resolved, markers):  # named outside and in a forbidden zone: do not resolve or stat it
            return "ERROR", "reference escapes Skill folder into a cloud or secret zone (not opened): '%s'" % link
        if fs.link_crosses_link(folder, link):
            return "ERROR", "reference goes through a symlink or junction (not opened): '%s'" % link
        if not fs.valid_resolved_under(resolved, folder):
            if (profile == "opcos" and allow_links_under is not None and not fs.zone_reason(resolved.resolve(), markers)
                    and fs.valid_resolved_under(resolved, allow_links_under) and resolved.exists()):
                return "WARN", "link leaves the Skill folder but stays inside the scanned root: '%s'" % link
            return "ERROR", "reference escapes Skill folder: '%s'" % link
        if not resolved.exists():
            return "ERROR", "missing referenced resource '%s'" % link
        try:
            return None, resolved.resolve()
        except OSError:
            return None, None

    for match in C.LINK_RE.finditer(body):
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
            findings.append(fs.emit(level, "ST6", manifest, line_of(match.start()), detail))
        elif detail is not None:
            refs_linked.add(detail)
    ref_dir = folder / "references"
    tree, tree_links, tree_dirs, tree_cloud, tree_cut = fs.walk_files(folder, markers)
    if tree_cut:
        findings.append(fs.emit("WARN", "SZ1", folder, 0, "skill lists more than %d files and folders or goes deeper than %d levels; the rest was not listed or checked"
                             % (C.DOCTOR_MAX_FILES_PER_SKILL, C.DOCTOR_MAX_SKILL_DEPTH)))
    if ref_dir in tree_dirs:
        for p in (x for x in tree if ref_dir in x.parents and x.name.endswith(".md") and not fs.is_sensitive_name(x.name)):
            if p in tree_cloud:
                continue  # reported as SZ2 below, never opened
            if p not in tree_links and not p.is_file():
                continue
            if p in tree_links:
                findings.append(fs.emit("ERROR", "SEC", p, 0, "symlink in reference tree may escape package; replace with real file"))
                continue
            if p.resolve() not in refs_linked:
                findings.append(fs.emit("WARN", "ST4", p, 0, "reference Markdown is not directly linked from SKILL.md"))
            try:
                ref_text, ref_too_big = fs.read_capped(p, max_file_bytes, anchor=pin_from)
            except fs.UnsafeOpen:  # swapped for a link after the listing: never read
                findings.append(fs.emit("ERROR", "SEC", p, 0, "reference is a link or not a plain file; not read"))
                continue
            except UnicodeError:
                findings.append(fs.emit("ERROR", "ST6", p, 0, "reference must be UTF-8"))
                continue
            if ref_too_big:
                findings.append(fs.emit("WARN", "SZ1", p, 0, "reference is larger than %d bytes; not read or linted" % max_file_bytes))
                continue
            findings.extend(lint.lint_contents(p, ref_text.splitlines(), "reference"))
    scripts = folder / "scripts"
    if scripts in tree_dirs:
        for script in tree:
            if (script.parent == scripts and script not in tree_links and script not in tree_dirs and script not in tree_cloud
                    and script.suffix in {".py", ".sh", ".js", ".ts"} and script.name not in body):
                findings.append(fs.emit("WARN", "SC3", script, 0, "script not mentioned in SKILL.md; document whether to run or read"))
    for p in tree:
        if p in tree_cloud:
            findings.append(fs.emit("WARN", "SZ2", p, 0, "cloud placeholder (OneDrive/SharePoint attributes) inside the skill; not opened or listed"))
        elif p in tree_links:
            findings.append(fs.emit("ERROR", "SEC", p, 0, "symlinks are not portable/safe in distributed skill packages"))
        elif (p.parent == folder and p.name.lower() not in C.ST8_ALLOWED_DIRS and p.name.lower() not in C.SKIP_DIRS and not fs.is_sensitive_name(p.name)
              and p in tree_dirs):
            findings.append(fs.emit("WARN", "ST8", p, 0, "folder '%s' is outside references/, scripts/, assets/, agents/ and tests/; move it or drop it from the skill" % p.name))
    if eval_root is None:
        root = fs.repo_root(folder)
        if root is not None:
            eval_root = root / "evals"
    if require_evals:
        if eval_root is None:
            findings.append(fs.emit("ERROR", "EV1", folder, 0, "eval root not found; supply --eval-root or use within Studio repo"))
        else:
            findings.extend(evals.check_evals(eval_root / folder.name))
    return findings


def print_findings(folder: Path, findings: list[dict]) -> None:
    errors = sum(f["level"] == "ERROR" for f in findings)
    warnings = sum(f["level"] == "WARN" for f in findings)
    print("%s: %d errors; %d warnings" % (folder, errors, warnings))
    for item in findings:
        location = item["path"] + ((":%s" % item["line"]) if item["line"] else "")
        print("  %-5s %-4s %s — %s" % (item["level"], item["code"], location, item["message"]))


def resolve_check_path(arg: str) -> tuple:
    """(kind, path) for `check <arg>` (FR5.2, FR5.3, FR8.1): ("skill", folder) for a folder, a missing path or `<folder>/SKILL.md`, which `validate_skill` takes as it is;
    ("workflow", file) or ("rules", file) for another file that `doctypes.doc_type` recognises by its `type:`, its name or its folder. ValueError carries the message
    (the caller prints it and exits 2) when the file is refused or no type can be told."""
    path = Path(arg).expanduser()
    if path.name == "SKILL.md":
        return "skill", path.parent
    named = fs.input_name_problem(path)  # by the spelling alone, before is_file stats anything: a path in a forbidden zone is never touched
    if named and (path.suffix or fs.secret_file_name(path.name)):  # a document or a secret-looking file is refused here
        raise ValueError("%s %s" % (path, named))
    if named:  # a folder-like name: validate_skill says INPUT for it without touching it
        return "skill", path
    absolute, cwd = Path(os.path.abspath(path)), Path.cwd()
    stop = cwd if cwd in absolute.parents else absolute.parent  # inside the working folder every step down is looked at; elsewhere the file and its folder
    if fs.link_in_chain(absolute, stop) is not None:  # before is_file stats the target (RF-S3)
        raise ValueError("%s is a symlink or junction, or lies below one; check does not read it" % path)
    if not path.is_file():
        return "skill", path
    problem = fs.input_file_problem(path)  # before anything opens the file: secret or cloud zone, secret-looking name, stream, placeholder
    if problem:
        raise ValueError("%s %s" % (path, problem))
    if fs.is_link(path):
        raise ValueError("%s is a symlink or junction; check does not read it" % path)
    if fs.path_is_cloud(path):
        raise ValueError("%s is a cloud placeholder; check does not read it" % path)
    unknown = "cannot tell the document type of %s (expected a skill folder or SKILL.md, or a .md file with `type:` in its frontmatter)" % path
    if path.suffix.casefold() != ".md":
        raise ValueError(unknown)
    try:
        text, too_big = fs.read_capped(path, C.DOCTOR_MAX_FILE_BYTES, single_link=True, anchor=fs.anchor_for(path))
    except (OSError, UnicodeError) as exc:
        raise ValueError("%s cannot be read as UTF-8 text: %s" % (path, exc))
    if too_big:
        raise ValueError("%s is larger than %d bytes; check does not read it" % (path, C.DOCTOR_MAX_FILE_BYTES))
    meta, _findings, _end = fs.parse_frontmatter(text, path)
    kind = doctypes.doc_type(path, meta)
    if kind in ("workflow", "rules"):
        return kind, path
    raise ValueError(unknown)
