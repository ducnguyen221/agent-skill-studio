"""Shape of the repository tree and the README (SPR-03 TK11; SPEC FR1, FR3.3, FR8, SC1, SC10).

The tree is read from `git ls-files` (what ships), never from the working folder, so a stray build folder cannot pass or fail it.
"""
import re
import shutil
import subprocess
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOP_DIRS = {"standards", "skills", "templates", "examples", "evals", "tests", "docs"}
README_MAX_LINES = 150  # a README must have fewer lines than this
MIN_LETTERS = 20        # shorter lines are labels, not prose
VIETNAMESE_SHARE = 0.9  # CQ2 (a): share of prose lines that carry a Vietnamese diacritic
# FR1.2: whole-folder exceptions to the depth limit of 3 folders.
DEEP_OK = (
    re.compile(r"^skills/[^/]+/"),            # a skill is moved as one block
    re.compile(r"^examples/[^/]+/"),          # so is an example skill
    re.compile(r"^evals/[^/]+/fixtures/"),    # fixtures keep the shape of the thing they imitate
    re.compile(r"^tests/fixtures/"),
    re.compile(r"^docs/"),                    # the website: generated pages mirror the Markdown tree
)


def tracked():
    if not shutil.which("git"):
        raise unittest.SkipTest("git not available")
    probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
    if probe.returncode != 0:
        raise unittest.SkipTest("not a git repository")
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, stdout=subprocess.PIPE, check=True).stdout
    return [x for x in out.decode("utf-8").split("\0") if x]


def prose(text):
    """Lines outside fenced code with their inline code and link targets removed (a command or a proper noun is not prose)."""
    found, fence = [], None
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            continue
        opened = re.match(r"^(`{3,}|~{3,})", stripped)
        if opened:
            fence = opened.group(1)
            continue
        line = re.sub(r"`[^`]*`", " ", raw)
        line = re.sub(r"\]\([^)]*\)", "]", line)
        line = re.sub(r"https?://\S+", " ", line)
        found.append((number, line))
    return found


def letters(line):
    return [c for c in unicodedata.normalize("NFC", line).lower() if c.isalpha()]


def accented(line):
    return any(c in _engine.const.VI_CHARS for c in letters(line))


class LayoutTests(unittest.TestCase):
    def test_seven_top_dirs(self):
        """SC1/FR1.1: the tracked folders directly under the root (hidden ones aside) are exactly the seven (the six of the library plus `docs/` for the website)."""
        top = {x.split("/")[0] for x in tracked() if "/" in x and not x.startswith(".")}
        self.assertEqual(top, TOP_DIRS)

    def test_no_file_deeper_than_three(self):
        """SC1/FR1.2: a file sits in at most 3 folders, outside the four whole-folder exceptions."""
        deep = [x for x in tracked() if x.count("/") > 3 and not any(p.match(x) for p in DEEP_OK)]
        self.assertEqual(deep, [], "files deeper than 3 folders: %d, first: %s" % (len(deep), deep[:3]))

    def test_no_runs_in_git(self):
        """FR3.3: raw run logs live in the ledger, so no tracked path of the evals tree has a runs/ folder."""
        runs = [x for x in tracked() if x.startswith("evals/") and "/runs/" in x]
        self.assertEqual(runs, [], runs[:3])

    def test_readme_short_one_language(self):
        """SC10/FR8.1 with CQ2 (a): one Vietnamese README.md under 150 lines; every `##` heading and nearly every prose line is Vietnamese."""
        names = sorted(x for x in tracked() if Path(x).name.lower().startswith("readme"))
        self.assertIn("README.md", names)
        self.assertNotIn("README.vi.md", names, "CQ2 (a): a single README.md, no second language file")
        for name in names:
            count = len((ROOT / name).read_text(encoding="utf-8").splitlines())
            self.assertLess(count, README_MAX_LINES, "%s has %d lines" % (name, count))
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        lines = prose(text)
        bad_headings = [(n, t.strip()) for n, t in lines if t.startswith("## ") and not accented(t)]
        self.assertEqual(bad_headings, [], "## headings without Vietnamese diacritics")
        body = [(n, t) for n, t in lines if len(letters(t)) >= MIN_LETTERS]
        self.assertTrue(body)
        plain = [(n, t.strip()[:60]) for n, t in body if not accented(t)]
        share = 1 - len(plain) / len(body)
        self.assertGreaterEqual(share, VIETNAMESE_SHARE, "%.0f %% of %d prose lines are Vietnamese; first others: %s"
                                % (share * 100, len(body), plain[:3]))
        self.assertIn("standards/README.md", text, "FR8.1: the 'what to read when' section points to standards/README.md")


if __name__ == "__main__":
    unittest.main()
