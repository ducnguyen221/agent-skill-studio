#!/usr/bin/env python3
"""Count whether a skill was activated in an agent transcript, hash skill trees, summarize run logs.

Python 3.9+, standard library only. Read-only.

  activation.py count <transcript.jsonl> --skill NAME --runtime claude-code|codex
  activation.py hash <skill-dir>                    # LF-normalised tree hash
  activation.py freeze|verify --eval-dir D --main-skill-dir M --cache-skill-dir C --manifest F
  activation.py summarize <runs-dir>                # runtime x (positive x/n, negative x/m)
  activation.py compact <runs-dir> --skill S --batch B --out F    # raw batch folder -> the one compact evidence file the gate reads
  activation.py compact --verify <runs-dir> F       # exit 0 when the rebuild is byte for byte F, 1 when not

Only agent tool calls count. System / user / developer messages (where the skill catalogue
appears in every session) are never scanned, so a catalogue entry is not an activation.
"""
import argparse
import bisect
import hashlib
import json
import re
import sys
from pathlib import Path

CLAUDE_SHELL_TOOLS = {"Bash", "PowerShell"}
CODEX_CALL_TYPES = {"function_call", "custom_tool_call", "local_shell_call"}
READ_VERBS = ("cat", "type", "Get-Content", "gc", "sed", "head", "tail", "less", "more", "bat", "rg", "grep", "egrep", "fgrep",
              "Select-String", "sls", "awk", "ReadAllText", "ReadAllLines", "ReadAllBytes", "read_file")
# a verb counts only as a whole word: not part of a path/flag such as "-type" or "cat.txt"
READ_RE = re.compile(r"(?<![\w.-])(?:%s)(?![\w-])" % "|".join(re.escape(v) for v in READ_VERBS), re.I)
# operators only: blanks around them are stripped per part (a `\s*` on both sides is quadratic on a long run of blanks)
SEGMENT_SPLIT = re.compile(r"(;|&&|\|\||\||\n)")
DENIED_RE = re.compile(r"requires? approval|permission to use|haven't granted|was denied|not allowed", re.I)
# Codex JS: a double-quoted literal is a command only as `cmd: "..."` or as an element of `NAME = [...]` that is then run with
# NAME.map / NAME.forEach / `of NAME`; patch bodies and prose strings are not commands.
JS_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
CMD_KEY_BEFORE = re.compile(r'\bcmd["\']?\s*:\s*$')
CMD_KEY_AT = re.compile(r'\bcmd["\']?\s*:\s*')  # a literal is a command value when a match of this ends exactly at its opening quote
ARRAY_ASSIGN = re.compile(r'\b([A-Za-z_$][\w$]*)\s*=\s*\[')
# lookaheads: a match consumes only the name, so `x . map` does not hide a following `map . map`
# whole identifier runs (a regex that starts at every word/`$` boundary of one long run is quadratic); names are cut out of a run in code
USE_MAP = re.compile(r"(?<![\w$])([\w$]+)(?=\s*\.\s*(?:map|forEach)\b)")
ASSIGN_RUN = re.compile(r"(?<![\w$])([\w$]+)\s*=\s*\[")
USE_OF = re.compile(r"\bof\s+(?=([\w$]+))")
ENGINE_DIR = Path(__file__).resolve().parents[2] / "skills" / "skill-creator-studio" / "scripts"
SCRIPTS = {"data-quality-audit": ("validate_csv.py",), "skill-creator-studio": ("studio.py",)}


def _skill_md_re(skill):
    # name must start at a boundary and be followed by a path separator: "x-data-quality-audit/" or "data-quality-audit-v2/" do not match
    return re.compile(r"(?<![\w.-])%s[\\/]SKILL\.md(?![\w.-])" % re.escape(skill), re.I)


def _script_re(skill):
    names = "|".join(re.escape(s) for s in SCRIPTS.get(skill, ())) or r"[\w.-]+\.py"
    # Linear: the interpreter is the FIRST one of its [^|;&] chunk (a later one only has a shorter tail to search), so a chunk is
    # scanned once instead of once per `py`.
    interp = r"(?<![\w.-])(?:python3?|py)(?:\.exe)?(?![\w-])"
    return re.compile(r"(?:^|(?<=[|;&]))(?:(?!%s)[^|;&])*%s[^|;&]*?(?<![\w.-])%s[\\/]scripts[\\/](?:%s)(?![\w.-])" % (interp, interp, re.escape(skill), names), re.I)


def _segments(command):
    """[(segment, piped)]; piped = the segment follows a single '|', so it filters its predecessor's output (a path there is a pattern, not a file read)."""
    out, piped, after_op = [], False, False
    for i, part in enumerate(SEGMENT_SPLIT.split(command)):
        if i % 2:
            if part == "\n" and after_op:  # blanks after an operator belong to it: "a |<newline> b" is still piped
                continue
            piped = part == "|"
            after_op = part != "\n"
        else:
            part = part.strip()
            if part:
                out.append((part, piped))
                piped = after_op = False
    return out


def _claude_calls(n, obj):
    if obj.get("type") != "assistant":
        return
    content = (obj.get("message") or {}).get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block.get("id"), block.get("name", ""), block.get("input") or {}


def _claude_results(obj):
    content = (obj.get("message") or {}).get("content") if obj.get("type") == "user" else None
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            c = block.get("content")
            if isinstance(c, list):
                c = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
            yield block.get("tool_use_id"), str(c or "")


def _string_body_ends(js):
    """ends[i] = where the body of a double-quoted literal ends when scanned from i (grammar of JS_STRING: a backslash escapes any char
    but newline). One right-to-left pass, so a literal is never re-scanned from every quote (unclosed or escaped quotes made the regex
    quadratic)."""
    n = len(js)
    ends = [n] * (n + 1)
    for i in range(n - 1, -1, -1):
        c = js[i]
        if c == '"':
            ends[i] = i
        elif c == "\\":
            ends[i] = ends[i + 2] if i + 1 < n and js[i + 1] != "\n" else i
        else:
            ends[i] = ends[i + 1]
    return ends


def _js_strings(js, ends=None):
    """[(start, end)] of the double-quoted literals JS_STRING.finditer finds, in linear time."""
    ends = _string_body_ends(js) if ends is None else ends
    found, q = [], js.find('"')
    while q != -1:
        e = ends[q + 1]
        if e < len(js) and js[e] == '"':
            found.append((q, e + 1))
            q = js.find('"', e + 1)
        else:
            q = js.find('"', q + 1)
    return found


def _bracket_ends(js, ends):
    """close[i] = index after the `]` closing a `[` opened just before i, literals skipped; len(js) when unclosed."""
    n = len(js)
    close = [n] * (n + 1)
    for i in range(n - 1, -1, -1):
        c = js[i]
        if c == "]":
            close[i] = i + 1
        elif c == "[":
            close[i] = close[close[i + 1]]
        elif c == '"' and ends[i + 1] < n and js[ends[i + 1]] == '"':
            close[i] = close[ends[i + 1] + 1]
        else:
            close[i] = close[i + 1]
    return close


_NAME_START = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$"  # ASCII only, like ARRAY_ASSIGN


def _word(c):
    return c.isalnum() or c == "_"


def _array_assigns(js):
    """[(name, end)] like ARRAY_ASSIGN.finditer: the name is the first `\\b`-started identifier inside the run, `end` is just after the `[`."""
    found = []
    for m in ASSIGN_RUN.finditer(js):
        x = m.group(1)
        for k, c in enumerate(x):
            if (c in _NAME_START) and ((k == 0 and _word(c)) or (k and _word(x[k - 1]) != _word(c))):
                found.append((x[k:], m.end()))
                break
    return found


def _js_command_spans(js):
    """(start, end) spans of array bodies `NAME = [ ... ]` where NAME is later mapped/iterated (a command batch)."""
    assigns = _array_assigns(js)
    if not assigns:
        return []
    # last start of each name's use: one scan of the text instead of one search of the tail per assignment
    # `$` is not a word char, so the old per-name patterns (`\bNAME`, `NAME\b`) also matched a name inside a longer identifier at a
    # word/`$` boundary: "x$foo.map" uses `$foo` and `foo`; "of foo$bar" uses `foo`. Only prefixes/suffixes whose length is the length of
    # an assigned name are looked at, so the work stays linear.
    names = {n for n, _ in assigns}
    lengths = sorted({len(n) for n in names})

    def note(name, pos):
        if pos > last_use.get(name, -1):
            last_use[name] = pos

    last_use = {}
    for m in USE_MAP.finditer(js):
        x, s0 = m.group(1), m.start()
        for ln in lengths:
            if ln > len(x):
                break
            k = len(x) - ln
            if ((k == 0 and _word(x[0])) or (k and _word(x[k - 1]) != _word(x[k]))) and x[k:] in names:
                note(x[k:], s0 + k)
    for m in USE_OF.finditer(js):
        x = m.group(1)
        for ln in lengths:
            if ln > len(x):
                break
            if (_word(x[-1]) if ln == len(x) else _word(x[ln - 1]) != _word(x[ln])) and x[:ln] in names:
                note(x[:ln], m.start())
    close = None
    spans = []
    for name, end in assigns:
        if last_use.get(name, -1) < end:
            continue
        if close is None:
            close = _bracket_ends(js, _string_body_ends(js))
        spans.append((end, close[end]))
    return spans


def _codex_commands(args):
    """Command strings of one Codex tool call: JSON arguments (command list / cmd) or JS source (`cmd: "..."` values and strings of a mapped `NAME = [...]` batch)."""
    if isinstance(args, dict):
        cmd = args.get("command", args.get("cmd", ""))
        return [" ".join(map(str, cmd)) if isinstance(cmd, list) else str(cmd)]
    if isinstance(args, str):
        found = []
        spans = sorted(_js_command_spans(args))
        starts = [a for a, _ in spans]
        reach = []  # reach[i] = furthest end among spans[:i + 1]
        for _, b in spans:
            reach.append(max(b, reach[-1]) if reach else b)
        after_cmd_key = {m.end() for m in CMD_KEY_AT.finditer(args)}
        for a, b in _js_strings(args):
            k = bisect.bisect_right(starts, a) - 1
            if not (a in after_cmd_key or (k >= 0 and a < reach[k])):
                continue
            try:
                found.append(json.loads(args[a:b]))
            except ValueError:
                pass
        return found
    return []


def _codex_calls(n, obj):
    if obj.get("type") != "response_item":
        return
    p = obj.get("payload") or {}
    if p.get("type") not in CODEX_CALL_TYPES:
        return
    args = p.get("arguments", p.get("input", p.get("action", "")))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            pass
    yield None, p.get("name") or p.get("type"), args


def _skill_tool_matches(skill, args):
    if not isinstance(args, dict):
        return None
    for key in ("skill", "command", "name"):
        v = str(args.get(key) or "").strip().lstrip("/")
        if v == skill or v.endswith(":" + skill):
            return v
    return None


def count(transcript_path, skill, runtime):
    """Return {"triggered": bool, "evidence": "transcript", "hits": [...], "scripts": [...]}.

    A hit is a Skill-tool call naming the skill, or ONE shell command (split on ; && || | newline) that holds both a read verb and
    <skill>/SKILL.md, or a Read/Grep tool call on that path. Only command / path fields are examined, never description text.
    A script entry is an interpreter running <skill>/scripts/<script> (not reading it) whose call was not denied.
    """
    if runtime not in ("claude-code", "codex"):
        raise ValueError("runtime must be claude-code or codex, got %r" % runtime)
    path_re, script_re = _skill_md_re(skill), _script_re(skill)
    hits, scripts, results = [], [], {}
    calls = _claude_calls if runtime == "claude-code" else _codex_calls
    with Path(transcript_path).open("r", encoding="utf-8") as fp:
        for n, line in enumerate(fp, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if runtime == "claude-code":
                for tid, text in _claude_results(obj):
                    results[tid] = text
            for tid, name, args in calls(n, obj):
                if runtime == "claude-code" and name == "Skill":
                    m = _skill_tool_matches(skill, args)
                    if m:
                        hits.append({"line": n, "tool": name, "via": "Skill", "match": m})
                    continue
                if runtime == "claude-code" and name in ("Read", "Grep"):
                    fields = [str(args.get(k) or "") for k in ("file_path", "path", "glob")] if isinstance(args, dict) else []
                    for f in fields:
                        if path_re.search(f):
                            hits.append({"line": n, "tool": name, "via": "read-SKILL.md", "match": f[:160]})
                            break
                    continue
                if runtime == "claude-code":
                    commands = [str(args.get("command") or "")] if name in CLAUDE_SHELL_TOOLS and isinstance(args, dict) else []
                else:
                    commands = _codex_commands(args)
                for command in commands:
                    for seg, piped in _segments(command):
                        if READ_RE.search(seg) and path_re.search(seg) and not piped:
                            hits.append({"line": n, "tool": name, "via": "read-SKILL.md", "match": seg.strip()[:160]})
                        elif script_re.search(seg):
                            scripts.append({"line": n, "tool": name, "match": seg.strip()[:160], "_id": tid})
    kept = []
    for s in scripts:
        tid = s.pop("_id")
        if tid is not None and DENIED_RE.search(results.get(tid, "")):
            continue
        kept.append(s)
    return {"triggered": bool(hits), "evidence": "transcript", "hits": hits, "scripts": kept}


def _norm_bytes(p):
    data = p.read_bytes()
    return data.replace(b"\r\n", b"\n")


def skill_tree_sha256(skill_dir):
    """sha256 over sorted 'relpath NUL filehash' lines; CRLF normalised so Windows checkouts match."""
    root = Path(skill_dir)
    lines = []
    for f in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"):
        rel = f.relative_to(root).as_posix()
        lines.append("%s\0%s\n" % (rel, hashlib.sha256(_norm_bytes(f)).hexdigest()))
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def file_sha256(path):
    return hashlib.sha256(_norm_bytes(Path(path))).hexdigest()


FROZEN_PARTS = ("cases.json", "rubric.md", "expected", "fixtures")


def frozen_files(eval_dir):
    """Relative posix path -> normalised sha256 for the files a run must not change."""
    root = Path(eval_dir)
    out = {}
    for part in FROZEN_PARTS:
        base = root / part
        for f in ([base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []):
            if f.is_file():
                out[f.relative_to(root).as_posix()] = file_sha256(f)
    return out


def freeze(eval_dir, skill_dir, main_skill_dir, cache_skill_dir, now):
    return {
        "frozen_at": now,
        "files": frozen_files(eval_dir),
        "skill_sha256_repo": skill_tree_sha256(main_skill_dir),
        "skill_sha256_claude_cache": skill_tree_sha256(cache_skill_dir),
        "skill_sha256_worktree": skill_tree_sha256(skill_dir),
    }


def verify(manifest, eval_dir, main_skill_dir, cache_skill_dir):
    """List of problems; empty list = frozen files unchanged and repo/cache skill hashes still match."""
    problems = []
    now = frozen_files(eval_dir)
    for rel, h in manifest["files"].items():
        if now.get(rel) != h:
            problems.append("changed or missing: " + rel)
    for rel in now:
        if rel not in manifest["files"]:
            problems.append("not in manifest: " + rel)
    if skill_tree_sha256(main_skill_dir) != manifest["skill_sha256_repo"]:
        problems.append("repo skill hash changed")
    if skill_tree_sha256(cache_skill_dir) != manifest["skill_sha256_claude_cache"]:
        problems.append("claude cache skill hash changed")
    if skill_tree_sha256(main_skill_dir) != skill_tree_sha256(cache_skill_dir):
        problems.append("repo and claude cache differ (invalid-version)")
    return problems


class EngineMismatch(Exception):
    """The `studio_evals` module that was loaded does not come from this repository's engine folder."""


def _engine():
    """The engine module `studio_evals` of THIS repository, or EngineMismatch.

    The counting rule lives once, in the engine (`studio_evals.summarize_logs`, which the `evals --all` gate also uses). The engine folder is
    found by a fixed path from this file, `<repo>/skills/skill-creator-studio/scripts/`, never from the cwd or an environment variable: it is
    put first on sys.path (any other entry for it is dropped), and the module that was loaded must sit in that folder (RF-S8).
    """
    engine_dir = ENGINE_DIR.resolve()
    sys.path[:] = [entry for entry in sys.path if entry != str(engine_dir)]
    sys.path.insert(0, str(engine_dir))
    import studio_evals
    found = Path(studio_evals.__file__).resolve().parent
    if found != engine_dir:
        raise EngineMismatch("loaded engine module studio_evals from %s, expected %s; nothing was counted" % (found, engine_dir))
    return studio_evals


def summarize(runs_dir):
    """Table from run logs: per runtime, positive/negative triggered counts of with_skill runs (the engine's `summarize`)."""
    return _engine().summarize(runs_dir)


AB_NAME = re.compile(r"ab-([0-9]{4}-[0-9]{2}-[0-9]{2})\.json")


def source_sha256(runs_dir):
    """SHA-256 over the lines `<POSIX path>\\0<sha256 of the content, CRLF -> LF>\\n`, sorted by path, for EVERY file of the raw batch (logs, out/, blind/,
    smoke/, ab-*, manifest, notes). A link, a cloud placeholder or a folder past the walk limits makes it ValueError: nothing is read through them."""
    engine = _engine()
    runs = Path(runs_dir)
    found, links, _dirs, cloud, cut = engine.fs.walk_files(runs)
    if links or cloud or cut:
        raise ValueError("%s holds a link, a cloud placeholder or more files than the walk limit: %s" % (runs, sorted(links | cloud)[:1] or "limit"))
    lines = []
    for path in found:
        if path.is_file():
            lines.append(("%s\0%s\n" % (path.relative_to(runs).as_posix(), file_sha256_lf(path))).encode("utf-8"))
    return hashlib.sha256(b"".join(sorted(lines))).hexdigest()


def file_sha256_lf(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _entry(name, log, smoke):
    """The compact-evidence entry of one raw log; ValueError when a field the gate reads has a type the schema refuses."""
    runtime, with_skill = log["runtime"], log["with_skill"]
    if not isinstance(runtime, str):
        raise ValueError("%s: runtime is not a string" % name)
    if with_skill is not None and not isinstance(with_skill, bool):
        raise ValueError("%s: with_skill is not a bool or null" % name)
    entry = {"file": name, "runtime": runtime, "with_skill": with_skill is True}
    if smoke:
        return entry
    status = log.get("status")
    entry["status"] = status if isinstance(status, str) else ""
    for key, kind in (("case_id", str), ("kind", str), ("triggered", bool)):
        value = log.get(key)
        if value is not None and not isinstance(value, kind):
            raise ValueError("%s: %s is not a %s or null" % (name, key, kind.__name__))
        entry[key] = value
    return entry


def raw_batch(runs_dir, skill, batch, skipped=None):
    """The compact evidence of a raw batch folder as a dict (what `compact` writes). `skipped` collects the names of files that could not be read."""
    engine = _engine()
    runs = Path(runs_dir)
    if not runs.is_dir():
        raise ValueError("%s is not a folder" % runs)
    sha = source_sha256(runs)
    logs, smoke, ab = [], [], {}
    for name, log in engine.read_logs(runs, skipped):
        match = AB_NAME.fullmatch(name)
        if match:
            ab[match.group(1)] = log
        elif "runtime" in log and "with_skill" in log:
            logs.append(_entry(name, log, False))
    for name, log in engine.read_logs(runs / "smoke", skipped):
        if "runtime" in log and "with_skill" in log:
            smoke.append(_entry("smoke/" + name, log, True))
    return {"schema": 1, "skill": skill, "batch": batch, "source": "ledger/agent-skill-studio/evidence/%s/%s/" % (batch, skill),
            "source_sha256": sha, "logs": sorted(logs, key=lambda e: e["file"]), "smoke": sorted(smoke, key=lambda e: e["file"]), "ab": ab}


def compact_text(runs_dir, skill, batch, skipped=None):
    """The exact text of the compact evidence file: sorted keys, indent 2, LF, no time stamp, so the same raw folder gives the same bytes."""
    return json.dumps(raw_batch(runs_dir, skill, batch, skipped), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _compact(a, parser):
    engine = _engine()
    skipped = []
    if a.verify:
        if a.out or not a.file:
            parser.error("compact --verify takes <runs-dir> and the compact file, and no --out")
        try:
            held = json.loads(Path(a.file).read_text(encoding="utf-8"))
            text = compact_text(a.runs_dir, held["skill"], held["batch"], skipped)
            same = Path(a.file).read_bytes() == text.encode("utf-8")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print("compact differs: cannot rebuild %s from %s: %s" % (a.file, a.runs_dir, exc))
            return 1
        print("compact OK" if same else "compact differs: %s is not what %s gives" % (a.file, a.runs_dir))
        return 0 if same else 1
    if a.file or not (a.skill and a.batch and a.out):
        parser.error("compact needs <runs-dir> --skill S --batch B --out F")
    try:
        text = compact_text(a.runs_dir, a.skill, a.batch, skipped)
    except ValueError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    if skipped:
        print("WARNING: left out (unreadable or not a JSON object): %s" % ", ".join(sorted(skipped)), file=sys.stderr)
    out = Path(a.out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with engine.fs.create_exclusive(out) as handle:
            handle.write(text.encode("utf-8"))
    except FileExistsError:
        print("ERROR: %s already exists; it is never overwritten" % out, file=sys.stderr)
        return 2
    except OSError as exc:
        print("ERROR: cannot write %s: %s" % (out, exc), file=sys.stderr)
        return 2
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("count")
    c.add_argument("transcript")
    c.add_argument("--skill", required=True)
    c.add_argument("--runtime", required=True, choices=["claude-code", "codex"])
    h = sub.add_parser("hash")
    h.add_argument("skill_dir")
    for name in ("freeze", "verify"):
        f = sub.add_parser(name)
        f.add_argument("--eval-dir", required=True)
        f.add_argument("--skill-dir", help="skill in the working tree under test (freeze only)")
        f.add_argument("--main-skill-dir", required=True, help="skill dir of the marketplace source checkout")
        f.add_argument("--cache-skill-dir", required=True, help="skill dir inside the Claude plugin cache")
        f.add_argument("--manifest", required=True)
    s = sub.add_parser("summarize")
    s.add_argument("runs_dir")
    k = sub.add_parser("compact", help="write (or with --verify, rebuild and compare) the compact evidence file of a raw batch folder")
    k.add_argument("runs_dir")
    k.add_argument("file", nargs="?", help="with --verify: the compact file to compare with")
    k.add_argument("--skill")
    k.add_argument("--batch")
    k.add_argument("--out", help="the compact file to create; exit 2 when it already exists")
    k.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    try:
        return _dispatch(a, ap)
    except EngineMismatch as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


def _dispatch(a, ap):
    if a.cmd == "count":
        print(json.dumps(count(a.transcript, a.skill, a.runtime), ensure_ascii=False, indent=2))
    elif a.cmd == "hash":
        print(skill_tree_sha256(a.skill_dir))
    elif a.cmd == "freeze":
        from datetime import datetime, timezone
        m = freeze(a.eval_dir, a.skill_dir or a.main_skill_dir, a.main_skill_dir, a.cache_skill_dir, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        Path(a.manifest).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8", newline="\n")
    elif a.cmd == "verify":
        problems = verify(json.loads(Path(a.manifest).read_text(encoding="utf-8")), a.eval_dir, a.main_skill_dir, a.cache_skill_dir)
        print("\n".join(problems) if problems else "manifest OK")
        return 1 if problems else 0
    elif a.cmd == "compact":
        return _compact(a, ap)
    else:
        rows = summarize(a.runs_dir)
        print("| runtime | positive triggered | negative triggered |")
        print("|---|---|---|")
        for rt, r in sorted(rows.items()):
            print("| %s | %d/%d | %d/%d |" % (rt, r["pos_trig"], r["pos"], r["neg_trig"], r["neg"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
