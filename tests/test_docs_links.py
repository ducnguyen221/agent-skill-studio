"""Check local Markdown links outside code blocks as a repository hygiene gate (evals/*.md and evals/<skill>/*.md included, fixtures left out)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class LinkTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self):
        failures = []
        for file in ROOT.rglob("*.md"):
            if any(x in file.parts for x in (".git", "dist")):
                continue
            rel = file.relative_to(ROOT).parts
            if rel[0] == "evals" and (len(rel) > 3 or "fixtures" in rel):  # evals/*.md and evals/<skill>/*.md only; fixtures and anything deeper are data
                continue
            in_fence = False
            for i, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
                if line.lstrip().startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                for raw in LINK.findall(line):
                    target = raw.strip().strip("<>").split("#", 1)[0].split("?", 1)[0]
                    if not target or target.startswith(("http:", "https:", "mailto:")):
                        continue
                    if not (file.parent / target).exists():
                        failures.append("%s:%s -> %s" % (file.relative_to(ROOT), i, target))
        self.assertFalse(failures, "Broken local links:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
