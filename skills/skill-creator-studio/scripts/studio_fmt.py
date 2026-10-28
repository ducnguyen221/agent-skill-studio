"""The `fmt` command: check or fix the layout of Markdown files (frontmatter, headings, process sections) (SPR-02 TK4c).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
"""

from __future__ import annotations

import bisect
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import studio_const as C
import studio_fs as fs


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
        match = None if line[:1].isspace() else C.FRONT_KEY_RE.fullmatch(line)
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
        if not C.FRONT_KEY_RE.fullmatch(line):
            return False
        keys += 1
    return keys > 0


def _quote_meta(line: str) -> tuple[str, str]:
    """(the line, status) for one line of a metadata block. `fixed`: the value is now in double quotes. `stuck`: the value is not a plain
    string fmt can quote safely (a comment, a block or flow marker, an unmatched quote) and the line stays as it is. `ok`: nothing to do."""
    match = C.FMT_META_LINE_RE.match(line.rstrip(" \t"))  # only the blanks FT1 removes: a no-break space belongs to the value
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
    if profile not in C.PROFILES:
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
        for index in range(1, min(len(lines), C.FMT_FRONT_SEARCH_LINES)):
            if C.FENCE_OPEN_RE.match(lines[index]):
                fences += 1
            elif lines[index] == "---" and fences % 2 == 0 and _looks_like_front(lines[index:]):
                block = lines[index + 1:index + _fm_bounds(lines[index:])[1]]
                if any(C.FRONT_KEY_RE.fullmatch(x) and C.FRONT_KEY_RE.fullmatch(x).group(1) in ("name", "description", "title", "status", "updated") for x in block):
                    add("FT5", index + 1, "frontmatter starts on line %d; it must start on line 1" % (index + 1), False)
                break

    bounds = _fm_bounds(lines)
    if kind == "skill" and bounds:
        pre, blocks = _fm_blocks(lines[1:bounds[1]])
        offset = 2 + len(pre)
        rebuilt = []
        for key, block in blocks:
            head = C.FRONT_KEY_RE.fullmatch(block[0])
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
        rank = lambda key: C.FM_ORDER.index(key) if key in C.FM_ORDER else len(C.FM_ORDER)
        ordered = sorted(rebuilt, key=lambda item: rank(item[0]))
        if [k for k, _ in ordered] != [k for k, _ in rebuilt]:
            line = 2 + len(pre)
            for (have, block), (want, _) in zip(rebuilt, ordered):
                if have != want:
                    break
                line += len(block)
            add("FT2", line, "frontmatter keys out of order; expected %s, then any other keys in their own order" % ", ".join(C.FM_ORDER), True)
        lines = ["---"] + pre + [x for _, block in ordered for x in block] + lines[bounds[1]:]
    if kind == "studio-doc":
        keys = {key for key, _ in _fm_blocks(lines[1:bounds[1]])[1]} if bounds else set()
        missing = [key for key in C.DOC_MIN_KEYS if key not in keys]
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
        match = C.FENCE_OPEN_RE.match(line)
        if match:
            fence = None if fence == match.group(1)[0] else (fence or match.group(1)[0])
            continue
        if fence:
            continue
        plain.append((index, line))
        head = C.FMT_HEADING_RE.match(line.rstrip())
        if head:
            heads.append((index, len(head.group(1)), head.group(2)))
    found: list[dict] = []

    def warn(index: int, message: str) -> None:
        found.append({"level": "WARN", "code": "PR1", "line": start + index + 1, "message": message})

    if not any(level == 1 for _, level, _ in heads):
        warn(0, "process file has no '# <Name>' title")
    if not any(C.FMT_CONCLUSION_RE.match(line) for _, line in plain):
        warn(0, "process file has no '> **Conclusion:**' (VI '> **Kết luận:**') line")
    if len(body) > 100 and not any(C.CONTENTS_RE.match("## " + title) for _, level, title in heads if level == 2):
        warn(0, "process file is over 100 lines and has no '## Contents'")
    for pattern, label in C.FMT_PROCESS_SECTIONS:
        if not any(level == 2 and pattern.match(title) for _, level, title in heads):
            warn(0, "process file has no '## %s' section" % label)
    steps = [(i, title) for i, level, title in heads if level == 3 and C.FMT_STEP_RE.match(title)]
    if not steps:
        warn(0, "process file has no '### Step N — <verb>' (VI '### Bước N — <động từ>') section")
    ends = [i for i, level, _ in heads if level <= 3]  # ascending: a step's section stops at the next heading of level 3 or above
    plain_at = [i for i, _ in plain]
    for index, title in steps:
        at = bisect.bisect_right(ends, index)
        stop = ends[at] if at < len(ends) else len(body)
        section = [line for _, line in plain[bisect.bisect_right(plain_at, index):bisect.bisect_left(plain_at, stop)]]
        for pattern, label in C.FMT_STEP_LABELS:
            if not any(pattern.match(line) for line in section):
                warn(index, "step '%s' has no '%s'" % (title, label))
    return found


def classify_md(path: Path, root: Path | None) -> str:
    """skill (SKILL.md, SKILL.vi.md), process (*PROCESS*.md, *_WORKFLOW.md), studio-doc (standards/*.md, examples/*.md, templates/README.md
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
        if len(parts) == 2 and parts[0] in ("standards", "examples") and parts[1].endswith(".md"):
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
        if (depth > 1 or depth == len(parts) - 1) and fs.is_link(base):
            return True
    return False


def _is_fixture_dir(path: Path, root: Path | None) -> bool:
    """True for a folder that is deliberately broken test data: `tests/fixtures` or `evals/<skill>/fixtures`, counted from the repo `root` (a
    `fixtures` folder anywhere else is documentation like any other)."""
    if root is None:
        return False
    try:
        parts = [x.casefold() for x in path.relative_to(Path(os.path.abspath(root))).parts]
    except ValueError:
        return False
    return any(len(parts) == len(shape) and all(want in ("*", got) for want, got in zip(shape, parts)) for shape in C.FMT_FIXTURE_PATHS)


def iter_md(paths: list, all_repo: bool, root: Path | None, skipped: list | None = None) -> list[Path]:
    """The Markdown files to format: each given file, plus every *.md under each given folder (and under `root` with all_repo). Never
    entered or opened: links, cloud placeholders, cloud/secret zones, .git, .tmp, .worktrees, dist, node_modules, evals/**/runs, tests/fixtures, evals/*/fixtures. A file or
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
        elif fs.secret_file_name(path.name):
            skip(path, "secret-name")
        else:
            try:
                size = os.lstat(path).st_size
            except OSError:
                skip(path, "unreadable")
                return
            if size > C.DOCTOR_MAX_FILE_BYTES:
                skip(path, "limit")
            else:
                files.append(path)

    starts = [Path(os.path.abspath(os.path.expanduser(os.fspath(p)))) for p in paths]
    if all_repo and root is not None:
        starts.append(Path(os.path.abspath(root)))
    for start in starts:
        reason = fs.zone_reason(start)
        if reason:
            skip(start, reason)
        elif _crosses_link(start):
            skip(start, "link")
        elif fs.path_is_cloud(start):
            skip(start, "cloud")
        elif fs.zone_reason(os.path.realpath(start)):  # the resolved spelling (8.3 short names, case): checked last, after the lstat above
            skip(start, fs.zone_reason(os.path.realpath(start)))
        elif start.is_file():
            take(start)
        elif start.is_dir():
            stack, visited = [start], 0
            while stack:
                current = stack.pop()
                visited += 1
                if visited > C.DOCTOR_MAX_DIRS:
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
                        if entry.is_symlink():  # the order of walk_files: a symlink first; its target is never asked about, so every symlink is reported
                            skip(child, "link")
                            continue
                        is_dir = entry.is_dir(follow_symlinks=False)
                        is_file = entry.is_file(follow_symlinks=False)
                    except OSError:
                        continue
                    if (is_dir or is_file) and fs.entry_is_cloud(entry):
                        skip(child, "cloud")
                        continue
                    if is_dir:
                        if fs.is_link(child):  # a junction (any reparse point) is a folder for is_dir(follow_symlinks=False)
                            skip(child, "link")
                            continue
                        if entry.name in C.FMT_PRUNE_DIRS or (entry.name == "runs" and "evals" in (x.casefold() for x in child.parts)):
                            continue
                        if _is_fixture_dir(child, root):
                            continue
                        if fs.zone_named(entry.name):
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


def _write_fixed(path: Path, data: bytes, backup: bool) -> str | None:
    """Replace `path` with `data`: a copy `<name>.bak-<ISO>` first when `backup`, then a new temp file next to it (a name chosen by the system
    and created exclusively, so a link planted at a guessable name is never followed) and an atomic replace. A read-only file is refused
    before anything is made. Whatever this call made is removed again when it fails; the original file stays as it was. Returns the path of
    the backup, or None when none was asked for."""
    if not os.access(path, os.W_OK):
        raise PermissionError(13, "file is read-only", os.fspath(path))
    checked = os.lstat(path)  # the identity every read of `path` below must match (Windows has no O_NOFOLLOW)
    made_backup, temp, handle, done = None, None, None, False
    try:
        if backup:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            target, count = path.with_name("%s.bak-%s" % (path.name, stamp)), 1
            while True:
                try:
                    sink = fs.create_exclusive(target)  # O_EXCL: a name already there (a link included) is never written through
                    break
                except FileExistsError:
                    target = path.with_name("%s.bak-%s-%d" % (path.name, stamp, count))
                    count += 1
            made_backup = target  # set only once the exclusive create has succeeded, so a failure never removes a file we did not make
            with sink, fs.open_nofollow_read(path, checked, single_link=False) as source:
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
                fs._remove_quietly(temp)
            if made_backup is not None:
                fs._remove_quietly(made_backup)


def cmd_fmt(args) -> int:
    """`fmt --check` (default) lists FT*/PR1 findings and never writes; `fmt --fix` applies the fixable ones to the files named.
    Exit 0 nothing left at ERROR level, 1 an ERROR (FT*) remains, 2 a path does not exist or the request is refused."""
    fixing = bool(args.fix)
    repo = fs.repo_root(Path(__file__)) or fs.repo_root(Path.cwd())
    if args.profile not in C.PROFILES:
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
        if not fs.zone_reason(spelled) and not os.path.lexists(spelled):
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
            with fs.open_nofollow_read(path, os.lstat(path), single_link=False) as handle:  # lstat now, so Windows compares the opened handle with the listed file
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
    blocked = {id(item) for item in skipped if item["reason"] in C.FMT_BLOCKING_REASONS or os.path.normcase(os.path.abspath(item["path"])) in named}
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
