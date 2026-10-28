"""Generate skills/skill-creator-studio/references/CORE_RULES.md from standards/SKILL_AUTHORING_STANDARD.md (SPR-03 FR5).

Run `python tests/gen_core_rules.py` from the repo root to rewrite the file. The output is a pure function of the
standard's text: the `updated` date is copied from the standard's frontmatter, never from the clock.
"""
import posixpath
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STANDARD = ROOT / "standards" / "SKILL_AUTHORING_STANDARD.md"
TARGET = ROOT / "skills" / "skill-creator-studio" / "references" / "CORE_RULES.md"
CONTENTS_OVER_LINES = 100  # SK-15: a reference longer than this needs a `## Contents`
HEAD_RE = re.compile(r"^### (SK-\d\d) — (.+? \[[^\]]+\] · kiểm: \S.*)$")


def _frontmatter_value(text: str, key: str) -> str:
    match = re.search(r"^%s:\s*(.+?)\s*$" % key, text.split("\n---\n", 1)[0], re.M)
    if not match:
        raise ValueError("standard frontmatter has no '%s'" % key)
    return match.group(1)


LINK_RE = re.compile(r"\[([^\]]+)\]\((?!https?:|#|mailto:)([^)\s]+)\)")


def _unlink(text: str) -> str:
    """The skill folder cannot reach the repo's files, so a relative link becomes `label (`repo path`)`."""
    def repl(match):
        path, _, anchor = match.group(2).partition("#")
        target = posixpath.normpath(posixpath.join("standards", path)) + ("#" + anchor if anchor else "")
        return "%s (`%s`)" % (match.group(1), target)
    return LINK_RE.sub(repl, text)


def _body(block: list) -> str:
    """The block's lines without leading or trailing blank lines; only relative links are rewritten."""
    lines = list(block)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return _unlink("\n".join(lines))


def _rules(text: str) -> list:
    """(id, 'title [level] · kiểm: check', body) per `### SK-xx` block, in file order."""
    found, current = [], None
    for line in text.split("\n"):
        if line.startswith("## ") or line.startswith("### ") and not line.startswith("### SK-"):
            current = None
        if line.startswith("### SK-"):
            match = HEAD_RE.match(line)
            if not match:
                raise ValueError("SK heading lacks '[level] · kiểm: <check>': %s" % line)
            current = (match.group(1), match.group(2), [])
            found.append(current)
        elif current is not None:
            current[2].append(line)
    return [(rid, rest, _body(body)) for rid, rest, body in found]


def render(standard_text: str) -> str:
    text = standard_text.replace("\r\n", "\n")
    updated = _frontmatter_value(text, "updated")
    rules = _rules(text)
    if not rules:
        raise ValueError("no '### SK-xx' blocks in the standard")
    body = ["## Rules", ""]
    for rid, rest, text_body in rules:
        body += ["### %s — %s" % (rid, rest), text_body, ""]
    head = [
        "---",
        'title: "Core Rules (SK-00…SK-15)"',
        "status: generated",
        "updated: %s" % updated,
        "---",
        "# Core Rules",
        "",
        "> Generated from standards/SKILL_AUTHORING_STANDARD.md of the agent-skill-studio repository — do not edit; edit the standard.",
        "",
    ]
    contents = ["## Contents", "", "- Rules — each SK rule with its level, check and full text", ""]
    out = head + body
    if len(out) > CONTENTS_OVER_LINES:
        out = head + contents + body
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> int:
    TARGET.write_bytes(render(STANDARD.read_bytes().decode("utf-8")).encode("utf-8"))
    print("wrote %s" % TARGET.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
