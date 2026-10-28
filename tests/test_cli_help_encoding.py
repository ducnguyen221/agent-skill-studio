"""SPR-04 TK9 fix: `--help` of every command prints on a cp1252 console (no PYTHONUTF8), where one non-ASCII letter in a help text
raises UnicodeEncodeError. CI sets PYTHONUTF8=1, so only a child process with the legacy codec catches it. Label: hồi-quy-mã-hoá.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "studio.py"
CURATOR = ROOT / "skills" / "skill-curator" / "scripts" / "curator.py"


def run(argv, utf8):
    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8" if utf8 else "cp1252", "PYTHONUTF8": "1" if utf8 else "0"})
    return subprocess.run([sys.executable] + [str(a) for a in argv], cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)


def studio_commands():
    """The sub-commands, read from the parser's own usage line `{new,check,...}`, not a hard-coded list."""
    out = run([STUDIO, "--help"], True).stdout.decode("utf-8")
    found = re.search(r"\{([a-z,\-]+)\}", out)
    return found.group(1).split(",") if found else []


class HelpEncodingTest(unittest.TestCase):
    def check(self, argv):
        done = run(argv, False)
        err = done.stderr.decode("utf-8", "replace")
        self.assertNotIn("Traceback", err, "%s: %s" % (argv, err[-300:]))
        self.assertEqual(done.returncode, 0, "%s exit %s: %s" % (argv, done.returncode, err[-300:]))
        done.stdout.decode("ascii")  # every help text is plain ASCII, as the other commands' are

    def test_studio_commands_found(self):
        self.assertGreaterEqual(len(studio_commands()), 8)

    def test_studio_top_level_help(self):
        self.check([STUDIO, "--help"])

    def test_studio_every_subcommand_help(self):
        for name in studio_commands():
            with self.subTest(command=name):
                self.check([STUDIO, name, "--help"])

    def test_curator_help(self):
        for name in ("catalog", "doctor"):
            with self.subTest(command=name):
                self.check([CURATOR, name, "--help"])


if __name__ == "__main__":
    unittest.main()
