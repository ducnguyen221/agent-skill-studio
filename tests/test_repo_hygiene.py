"""Repo hygiene: line endings are pinned by .gitattributes and the index holds LF.

Label: bắt-lỗi (fails without .gitattributes eol=lf, so a CRLF checkout can no longer break `fmt --check`).
"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _eol_listing():
    if not shutil.which("git"):
        raise unittest.SkipTest("git not available")
    probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
    if probe.returncode != 0:
        raise unittest.SkipTest("not a git repository")
    out = subprocess.run(["git", "ls-files", "--eol"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         encoding="utf-8", check=True).stdout
    return out.splitlines()


class RepoHygieneTests(unittest.TestCase):
    def test_gitattributes_pins_lf(self):
        """bắt-lỗi: .gitattributes exists and pins eol=lf (red at df875ce: the file was missing)."""
        path = ROOT / ".gitattributes"
        self.assertTrue(path.is_file(), ".gitattributes is missing")
        self.assertIn("eol=lf", path.read_text(encoding="utf-8"))

    def test_index_text_files_are_lf(self):
        """tương-đương (skipped at df875ce, not shown red): every tracked text file is LF in the index."""
        bad = []
        for line in _eol_listing():
            meta, _, name = line.partition("\t")
            parts = meta.split()
            index = parts[0]
            attr = parts[2] if len(parts) > 2 else ""
            if index == "i/none" or index == "i/-text" or attr == "attr/-text":
                continue
            if index != "i/lf":
                bad.append(f"{index} {name}")
        self.assertEqual([], bad)


if __name__ == "__main__":
    unittest.main()
