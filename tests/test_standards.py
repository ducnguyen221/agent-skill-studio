"""Shape checks for the documents under standards/ (SPR-33)."""
import re
import unittest
from pathlib import Path

STANDARDS_DIR = Path(__file__).resolve().parent.parent / "standards"

SOURCE_TAGS: tuple[str, ...] = (
    "spec", "bp", "cc", "ab", "ae", "pb", "fable-5", "sonnet-5.5",
)


def read_std(name: str) -> str:
    return (STANDARDS_DIR / name).read_text(encoding="utf-8")


class StandardsTest(unittest.TestCase):
    def test_memo_v0_shape(self):
        p = STANDARDS_DIR / "MEMO-SKILL-V0.md"
        self.assertTrue(p.exists(), "standards/MEMO-SKILL-V0.md is missing")
        text = read_std("MEMO-SKILL-V0.md")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), 60)
        self.assertTrue(
            any(re.fullmatch(r"Date: 2026-10-2\d", ln) for ln in lines),
            "no standalone 'Date: 2026-10-2x' line",
        )
        allowed = {f"[{t}]" for t in SOURCE_TAGS} | {"[nội bộ]"}
        rows = [ln for ln in lines if ln.startswith(("| (a", "| (b"))]
        self.assertEqual(len(rows), 18, "expected 9 (a) rows and 9 (b) rows")
        for ln in rows:
            last_cell = ln.rstrip().rstrip("|").rsplit("|", 1)[-1]
            self.assertTrue(
                any(tag in last_cell for tag in allowed),
                f"row has no source tag in its last cell: {ln[:40]}",
            )
        self.assertIn("SPR-31", text)
        self.assertIn("SPR-32", text)


if __name__ == "__main__":
    unittest.main()
