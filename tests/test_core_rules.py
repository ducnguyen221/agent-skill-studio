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

    def test_file_shape(self):
        text = read_bytes_text(CORE_RULES)
        self.assertNotIn("\r", text)
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))
        self.assertIn("Generated from standards/SKILL_AUTHORING_STANDARD.md — do not edit", text)
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
            for n in range(60))
        out = gen_core_rules.render(many)
        self.assertIn("\n## Contents\n", out)
        self.assertNotIn("Second sentence", out)
        # short file: no Contents needed
        self.assertNotIn("\n## Contents\n", gen_core_rules.render(src))

    def test_render_rejects_a_heading_without_level_and_check(self):
        bad = "---\ntitle: T\nstatus: active\nupdated: 2026-01-01\n---\n### SK-00 — Name\nBody.\n"
        with self.assertRaises(ValueError):
            gen_core_rules.render(bad)


if __name__ == "__main__":
    unittest.main()
