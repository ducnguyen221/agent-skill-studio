"""Generate skills/skill-creator-studio/references/CORE_RULES.md from standards/SKILL_AUTHORING_STANDARD.md (SPR-03 FR5).

Run `python tests/gen_core_rules.py` from the repo root to rewrite the file. The output is a pure function of the
standard's text: the `updated` date is copied from the standard's frontmatter, never from the clock.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STANDARD = ROOT / "standards" / "SKILL_AUTHORING_STANDARD.md"
TARGET = ROOT / "skills" / "skill-creator-studio" / "references" / "CORE_RULES.md"
CONTENTS_OVER_LINES = 100  # SK-15: a reference longer than this needs a `## Contents`
HEAD_RE = re.compile(r"^### (SK-\d\d) — (.+? \[[^\]]+\] · kiểm: \S.*)$")
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s")


def _frontmatter_value(text: str, key: str) -> str:
    match = re.search(r"^%s:\s*(.+?)\s*$" % key, text.split("\n---\n", 1)[0], re.M)
    if not match:
        raise ValueError("standard frontmatter has no '%s'" % key)
    return match.group(1)


def _first_sentence(block: list) -> str:
    text = " ".join(line.strip() for line in block if line.strip())
    return SENTENCE_END_RE.split(text, 1)[0]


def _rules(text: str) -> list:
    """(id, 'title [level] · kiểm: check', first sentence) per `### SK-xx` block, in file order."""
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
    return [(rid, rest, _first_sentence(body)) for rid, rest, body in found]


def render(standard_text: str) -> str:
    text = standard_text.replace("\r\n", "\n")
    updated = _frontmatter_value(text, "updated")
    rules = _rules(text)
    if not rules:
        raise ValueError("no '### SK-xx' blocks in the standard")
    body = ["## Rules", ""]
    for rid, rest, sentence in rules:
        body += ["### %s — %s" % (rid, rest), sentence, ""]
    head = [
        "---",
        'title: "Core Rules (SK-00…SK-15)"',
        "status: generated",
        "updated: %s" % updated,
        "---",
        "# Core Rules",
        "",
        "> Generated from standards/SKILL_AUTHORING_STANDARD.md — do not edit. Full wording and the other standards live in the Studio repo; "
        "regenerate with `python tests/gen_core_rules.py`.",
        "",
    ]
    contents = ["## Contents", "", "- Rules — each SK rule with its level, check and first sentence", ""]
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
