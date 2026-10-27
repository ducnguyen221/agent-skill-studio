#!/usr/bin/env python3
"""Make a committable copy of an agent transcript: keep what the activation counter and a reviewer need, drop the rest.

  redact.py filter <in.jsonl> <out.jsonl> --runtime claude-code|codex

Kept: tool calls (and results cut to 500 chars), assistant text and the tail of the prompt (cut), and the skill CATALOGUE
as a list of skill NAMES only (descriptions and the system prompt are dropped). The catalogue names are the evidence that a
skill was absent or present in a baseline / with-skill session. E-mail addresses and the user's home path are redacted.
`activation.py count` gives the same answer on the filtered copy as on the original (tested).
Python 3.9+, standard library only.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# any Windows user folder, also when the text was cut inside the name ("C:\Users\Xxxx...[cut]"); JSON-escaped backslashes included
PATH_RE = re.compile(r"""C:[\\/]+Users[\\/]+[^\\/"\s]+""", re.I)
# EMAIL_AT matches an address starting exactly where it is tried; EMAIL_RE only starts at a token start. Searching with the plain pattern
# retries every position of a long run of word chars (quadratic), so _redact_emails tries EMAIL_AT once at the scan position and
# EMAIL_RE for the rest - the same leftmost matches, one pass.
EMAIL_AT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CATALOG_NAME_RE = re.compile(r"(?m)^- ([\w.-]+(?::[\w.-]+)?): ")


def _runtime_user_names():
    """Account names of the machine running the filter, read at run time (never written in this file)."""
    names = {os.environ.get("USERNAME"), os.environ.get("USER"), Path.home().name}
    return sorted((n for n in names if n and len(n) >= 3), key=len, reverse=True)


def _redact_emails(text):
    out, pos = [], 0
    while True:
        m = EMAIL_AT.match(text, pos) or EMAIL_RE.search(text, pos)
        if not m:
            break
        out.append(text[pos:m.start()])
        out.append("<email>")
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def sanitize(text):
    text = PATH_RE.sub("~", text)
    text = _redact_emails(text)
    for name in _runtime_user_names():
        text = re.sub(re.escape(name), "<user>", text, flags=re.I)
    return text


def _cut(v, n, tail=False):
    if isinstance(v, str):
        if len(v) <= n:
            return v
        return "[cut]..." + v[-n:] if tail else v[:n] + "...[cut]"
    if isinstance(v, list):
        return [_cut(x, n, tail) for x in v]
    if isinstance(v, dict):
        return {k: (_cut(x, n, tail) if k in ("text", "content", "output") else x) for k, x in v.items()}
    return v


def _claude(obj):
    t = obj.get("type")
    if t == "assistant":
        blocks = [b for b in (obj.get("message") or {}).get("content", []) if isinstance(b, dict) and b.get("type") in ("text", "tool_use")]
        return {"type": "assistant", "message": {"content": [_cut(b, 300) if b.get("type") == "text" else b for b in blocks]}}
    if t == "user":
        return {"type": "user", "message": {"content": _cut((obj.get("message") or {}).get("content"), 500, tail=True)}}
    a = obj.get("attachment") or {}
    if t == "attachment" and a.get("type") == "skill_listing":
        names = a.get("names")
        if not isinstance(names, list):
            names = CATALOG_NAME_RE.findall(str(a.get("content") or ""))
        return {"type": "attachment", "attachment": {"type": "skill_listing", "skillCount": a.get("skillCount", len(names)), "names": names}}
    return None


def _codex(obj):
    t, p = obj.get("type"), obj.get("payload") or {}
    if t == "session_meta":
        return {"type": "session_meta", "payload": {k: p.get(k) for k in ("id", "cwd", "timestamp")}}
    if t != "response_item":
        return None
    pt = p.get("type")
    if pt in ("function_call", "custom_tool_call", "custom_tool_call_output", "function_call_output"):
        return {"type": "response_item", "payload": _cut(p, 500)}
    if pt == "message":
        text = "\n".join(c.get("text", "") for c in p.get("content", []) if isinstance(c, dict))
        role = p.get("role")
        if role == "developer":
            names = CATALOG_NAME_RE.findall(text)
            if names:
                return {"type": "response_item", "payload": {"type": "message", "role": "developer", "skill_names": names}}
            return None
        if role in ("user", "assistant"):
            return {"type": "response_item", "payload": {"type": "message", "role": role, "text": _cut(text, 500, tail=(role == "user"))}}
    return None


def filter_lines(lines, runtime):
    fn = _claude if runtime == "claude-code" else _codex
    out = []
    for line in lines:
        if not line.strip():
            continue
        r = fn(json.loads(line))
        if r is not None:
            out.append(sanitize(json.dumps(r, ensure_ascii=False)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("filter")
    f.add_argument("src")
    f.add_argument("dst")
    f.add_argument("--runtime", required=True, choices=["claude-code", "codex"])
    a = ap.parse_args(argv)
    lines = Path(a.src).read_text(encoding="utf-8").splitlines()
    Path(a.dst).write_text("\n".join(filter_lines(lines, a.runtime)) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
