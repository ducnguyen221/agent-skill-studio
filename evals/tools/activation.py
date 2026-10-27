#!/usr/bin/env python3
"""Count whether a skill was activated in an agent transcript, hash skill trees, summarize run logs.

Python 3.9+, standard library only. Read-only.

  activation.py count <transcript.jsonl> --skill NAME --runtime claude-code|codex
  activation.py hash <skill-dir>                    # LF-normalised tree hash
  activation.py freeze|verify --eval-dir D --main-skill-dir M --cache-skill-dir C --manifest F
  activation.py summarize <runs-dir>                # runtime x (positive x/n, negative x/m)

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
USE_MAP = re.compile(r"\b([A-Za-z_$][\w$]*)(?=\s*\.\s*(?:map|forEach)\b)")
USE_OF = re.compile(r"\bof\s+(?=([A-Za-z_$][\w$]*))")
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


def _js_command_spans(js):
    """(start, end) spans of array bodies `NAME = [ ... ]` where NAME is later mapped/iterated (a command batch)."""
    assigns = list(ARRAY_ASSIGN.finditer(js))
    if not assigns:
        return []
    # last start of each name's use: one scan of the text instead of one search of the tail per assignment
    last_use = {}
    for m in USE_MAP.finditer(js):
        last_use[m.group(1)] = m.start()
    for m in USE_OF.finditer(js):
        last_use[m.group(1)] = max(last_use.get(m.group(1), -1), m.start())
    close = None
    spans = []
    for m in assigns:
        if last_use.get(m.group(1), -1) < m.end():
            continue
        if close is None:
            close = _bracket_ends(js, _string_body_ends(js))
        spans.append((m.end(), close[m.end()]))
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


def summarize(runs_dir):
    """Table from run logs: per runtime, positive/negative triggered counts of with_skill runs."""
    rows = {}
    for f in sorted(Path(runs_dir).glob("*.json")):
        try:
            log = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(log, dict) or "runtime" not in log or "with_skill" not in log or log.get("status") != "ran":
            continue
        if log["with_skill"] is not True:
            continue
        r = rows.setdefault(log["runtime"], {"pos": 0, "pos_trig": 0, "neg": 0, "neg_trig": 0})
        positive = log.get("kind") != "near-miss"
        trig = bool(log.get("triggered"))
        r["pos" if positive else "neg"] += 1
        if trig:
            r["pos_trig" if positive else "neg_trig"] += 1
    return rows


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
    a = ap.parse_args(argv)
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
    else:
        rows = summarize(a.runs_dir)
        print("| runtime | positive triggered | negative triggered |")
        print("|---|---|---|")
        for rt, r in sorted(rows.items()):
            print("| %s | %d/%d | %d/%d |" % (rt, r["pos_trig"], r["pos"], r["neg_trig"], r["neg"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
