"""SPR-03 TK4 (FR7.1): templates/starter-project/ tells Claude, Codex and Antigravity how to load the same AGENTS.md."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "templates" / "starter-project"
INSTALL = re.compile(r"python3? studio\.py install <skill>((?: --[a-z-]+(?: [^\s`]+)?)*)")


def read(name: str) -> str:
    return (STARTER / name).read_text(encoding="utf-8")


def install_lines(text: str) -> list:
    return INSTALL.findall(text)


class StarterProjectTests(unittest.TestCase):
    def test_starter_project_loads_rules(self):
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md"):
            self.assertTrue((STARTER / name).is_file(), "missing templates/starter-project/" + name)
        self.assertIn("@AGENTS.md", read("CLAUDE.md").splitlines(), "CLAUDE.md needs a line that is exactly @AGENTS.md")
        self.assertIn("AGENTS.md", read("GEMINI.md"))
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            self.assertIn("install", read(name), name + " needs an install line")

    def test_old_folder_is_gone(self):
        self.assertFalse((ROOT / "templates" / "project").exists(), "templates/project must be renamed, not copied")

    def test_agents_md_has_loading_table_and_keeps_rules(self):
        text = read("AGENTS.md")
        self.assertIn("## Loading these rules", text)
        section = text.split("## Loading these rules", 1)[1].split("\n## ", 1)[0]
        for harness, how in (("Claude", "CLAUDE.md"), ("Codex", "AGENTS.md"), ("Antigravity", "GEMINI.md")):
            row = [ln for ln in section.splitlines() if ln.startswith("|") and harness in ln]
            self.assertEqual(len(row), 1, "one table row for " + harness)
            self.assertIn(how, row[0])
        self.assertEqual(len(text.split("## Shared working rules", 1)[1].split("\n## ", 1)[0].strip().splitlines()), 6, "the 6 shared working rules stay")
        self.assertIn("## Development checks", text)

    def test_install_lines_use_real_flags_per_harness(self):
        help_text = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), "install", "--help"], capture_output=True, text=True,
                                   encoding="utf-8", cwd=str(ROOT), timeout=60).stdout
        seen = {}
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            for flags in install_lines(read(name)):
                agent = re.search(r"--agent (\w+)", flags)
                self.assertIsNotNone(agent, "%s: install line without --agent: %s" % (name, flags))
                self.assertRegex(help_text, r"--agent \{[^}]*\b%s\b" % agent.group(1), "unknown agent " + agent.group(1))
                for flag in re.findall(r"--[a-z-]+", flags):
                    self.assertIn(flag, help_text, "%s: flag %s is not in `install --help`" % (name, flag))
                seen.setdefault(agent.group(1), []).append(flags)
        self.assertEqual(sorted(seen), ["antigravity", "claude", "codex"], "each harness has an install line")
        self.assertTrue(all("--user" in f for f in seen["codex"] + seen["antigravity"]), "Codex and Antigravity use --user")
        self.assertFalse(any("--user" in f for f in seen["claude"]), "the engine refuses --user for claude (exit 2)")
        self.assertTrue(all("--workspace" in f for f in seen["claude"]), "Claude installs into the workspace")


if __name__ == "__main__":
    unittest.main()
