"""CORE_RULES.md is generated from the authoring standard and must match it byte for byte (SPR-03 FR5.1, FR5.2)."""
import re
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_core_rules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STANDARD = ROOT / "standards" / "SKILL_AUTHORING_STANDARD.md"
CORE_RULES = ROOT / "skills" / "skill-creator-studio" / "references" / "CORE_RULES.md"
SK_IDS = ["SK-%02d" % n for n in range(16)]
LEVEL_RE = re.compile(r"\[[^\]]+\] · kiểm: \S")


def read_bytes_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def block_body(text: str, sk: str) -> str:
    """Lines between `### SK-xx ...` and the next `#`-heading, blank edges removed."""
    lines, grabbing, out = text.split("\n"), False, []
    for line in lines:
        if grabbing and line.startswith("#"):
            break
        if grabbing:
            out.append(line)
        elif line.startswith("### %s " % sk):
            grabbing = True
    return "\n".join(out).strip("\n")


def section_body(text: str, name: str) -> str:
    """Lines between `## <name>` and the next `## ` heading, blank edges removed."""
    lines, grabbing, out = text.split("\n"), False, []
    for line in lines:
        if grabbing and line.startswith("## "):
            break
        if grabbing:
            out.append(line)
        elif line == "## %s" % name:
            grabbing = True
    return "\n".join(out).strip("\n")


class CoreRulesTests(unittest.TestCase):
    def test_core_rules_in_sync(self):
        # FR5.1: regenerating from the standard gives the same bytes as the file on disk.
        self.assertEqual(gen_core_rules.render(read_bytes_text(STANDARD)), read_bytes_text(CORE_RULES))

    def test_core_rules_all_sk(self):
        # FR5.2: every SK-00..SK-15 is present with its level and its check.
        lines = read_bytes_text(CORE_RULES).split("\n")
        heads = [ln for ln in lines if ln.startswith("### SK-")]
        self.assertEqual([h.split()[1] for h in heads], SK_IDS)
        for head in heads:
            self.assertRegex(head, LEVEL_RE, head)

    def test_bodies_are_verbatim(self):
        # Coordinator ruling: the full body of every block, not the first sentence (SK-05 and SK-10 lose their point otherwise).
        std, core = read_bytes_text(STANDARD), read_bytes_text(CORE_RULES)
        for sk in SK_IDS:
            self.assertEqual(block_body(core, sk), gen_core_rules._unlink(block_body(std, sk)), sk)
        for sk in ("SK-05", "SK-10"):
            self.assertGreater(len(block_body(core, sk).split(". ")), 1, sk)

    def test_relative_links_become_repo_paths(self):
        # A link out of the skill folder would break; the target stays readable as a repo path.
        core = read_bytes_text(CORE_RULES)
        self.assertNotRegex(core, r"\]\((?!https?:|#)")
        self.assertIn("(`evals/RUNBOOK.md`)", core)
        self.assertIn("(`standards/EVALUATION_STANDARD.md#", core)
        self.assertEqual(gen_core_rules._unlink("[a](../x/y.md) [b](B.md#z) [c](https://e.org/q) [d](#h)"),
                         "a (`x/y.md`) b (`standards/B.md#z`) [c](https://e.org/q) [d](#h)")

    def test_file_shape(self):
        text = read_bytes_text(CORE_RULES)
        self.assertNotIn("\r", text)
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))
        self.assertIn("Generated from standards/SKILL_AUTHORING_STANDARD.md of the agent-skill-studio repository — do not edit; edit the standard.", text)
        self.assertNotIn("gen_core_rules", text)
        front = text.split("---\n")[1]
        self.assertIn("status: generated", front)
        # `updated` comes from the source frontmatter, not from today's date.
        source_updated = re.search(r"^updated: (\S+)$", read_bytes_text(STANDARD), re.M).group(1)
        self.assertIn("updated: %s" % source_updated, front)

    def test_render_is_deterministic_and_adds_contents_when_long(self):
        src = read_bytes_text(STANDARD)
        self.assertEqual(gen_core_rules.render(src), gen_core_rules.render(src.replace("\n", "\r\n")))
        many = "---\ntitle: T\nstatus: active\nupdated: 2026-01-01\n---\n# H\n\n" + "".join(
            "### SK-%02d — Rule %d [MUST] · kiểm: review\nFirst sentence %d. Second sentence.\n\n" % (n, n, n)
            for n in range(60)) + "".join("## %s\nBody of it.\n\n" % name for name in gen_core_rules.EXTRA_SECTIONS)
        out = gen_core_rules.render(many)
        self.assertIn("\n## Contents\n", out)
        self.assertIn("Second sentence", out)  # the whole body is kept
        # short file: no Contents needed
        self.assertNotIn("\n## Contents\n", gen_core_rules.render(src))

    def test_contents_threshold_counts_real_lines(self):
        # TK6 follow-up: SK-15 counts lines of the file, not elements of an internal list. Few rules with long bodies
        # (a handful of list elements, > 100 real lines) still need `## Contents`.
        head = "---\ntitle: T\nstatus: active\nupdated: 2026-01-01\n---\n# H\n\n"
        tail = "\n".join("## %s\nx.\n" % name for name in gen_core_rules.EXTRA_SECTIONS)

        def render_filled(extra: int) -> str:
            body = "\n".join("line %d of the body." % n for n in range(extra))
            return gen_core_rules.render(head + "### SK-00 — Long [MUST] · kiểm: review\n" + body + "\n\n" + tail)

        long_out = render_filled(150)
        self.assertGreater(long_out.count("\n"), 100)
        self.assertIn("\n## Contents\n", long_out)
        self.assertNotIn("\n## Contents\n", render_filled(5))
        # Boundary: Contents appears exactly when the file would be longer than 100 lines without it.
        switch = next(k for k in range(0, 200) if "\n## Contents\n" in render_filled(k))
        self.assertEqual(render_filled(switch - 1).count("\n"), gen_core_rules.CONTENTS_OVER_LINES)

    def test_extra_sections_are_verbatim(self):
        # Coordinator ruling (US3): priority, lifecycle and Definition of Done of the standard travel with the skill.
        std, core = read_bytes_text(STANDARD), read_bytes_text(CORE_RULES)
        self.assertEqual(gen_core_rules.EXTRA_SECTIONS, ("Ưu tiên khi luật mâu thuẫn", "Vòng đời", "Definition of Done"))
        for name in gen_core_rules.EXTRA_SECTIONS:
            self.assertEqual(section_body(core, name), gen_core_rules._unlink(section_body(std, name)), name)
            self.assertGreater(len(section_body(core, name)), 100, name)

    def test_missing_extra_section_is_rejected(self):
        src = read_bytes_text(STANDARD).replace("## Vòng đời", "## Khác")
        with self.assertRaises(ValueError):
            gen_core_rules.render(src)

    def test_render_rejects_a_heading_without_level_and_check(self):
        bad = "---\ntitle: T\nstatus: active\nupdated: 2026-01-01\n---\n### SK-00 — Name\nBody.\n"
        with self.assertRaises(ValueError):
            gen_core_rules.render(bad)


if __name__ == "__main__":
    unittest.main()
