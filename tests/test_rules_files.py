"""SPR-03 TK7 (FR6.1-FR6.3): the root rules files CLAUDE.md, AGENTS.md and GEMINI.md point only to paths that exist."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
ROOT_FILES = set(RULES) | {"studio.py"}
SPAN = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\]\((?!https?:|#|mailto:)([^)\s]+)\)")
PATHLIKE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.\-/]*$")  # no spaces, <placeholder>, ~, glob; a leading / is a slash command
INSTALL_TARGETS = (".agent/", ".agents/", ".claude/")
INSTALL = re.compile(r"python3? studio\.py install \S+((?: --[a-z-]+(?: [^\s`]+)?)*)")


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def repo_paths(text: str) -> list:
    """Backticked repo paths and relative links in a rules file; a bare name counts only when it is a root file."""
    found = []
    for span in SPAN.findall(text):
        if span.startswith(INSTALL_TARGETS):
            continue  # where a harness looks for skills in the user's project, not a path in this repo
        if PATHLIKE.match(span) and ("/" in span or span in ROOT_FILES):
            found.append(span)
    found += LINK.findall(text)
    return [p.partition("#")[0] for p in found]


class RulesFilesTests(unittest.TestCase):
    def test_rules_files_point_to_live_paths(self):
        # FR6: every path a rules file names exists; nothing points at the removed adapters/ or CORE_STANDARD.
        for name in RULES:
            text = read(name)
            paths = repo_paths(text)
            self.assertTrue(paths, name + " names no repo path at all (extraction broke?)")
            for path in paths:
                self.assertTrue((ROOT / path).exists(), "%s points to a missing path: %s" % (name, path))
            self.assertNotIn("adapters/", text, name)
            self.assertNotIn("CORE_STANDARD", text, name)

    def test_claude_md_imports_agents_md_and_stays_at_the_root(self):
        # FR6.1: Claude Code loads AGENTS.md through the root CLAUDE.md.
        self.assertIn("@AGENTS.md", read("CLAUDE.md").splitlines())

    def test_agents_md_routes_to_the_live_standards(self):
        # FR6.2: AGENTS.md routes to the merged standard, DOC_TYPES and HARNESSES.
        text = read("AGENTS.md")
        for needle in ("`standards/SKILL_AUTHORING_STANDARD.md`", "`standards/DOC_TYPES.md`", "`standards/HARNESSES.md`",
                       "`standards/SECURITY_AND_PERMISSIONS.md`", "`standards/EVALUATION_STANDARD.md`", "`evals/RUNBOOK.md`"):
            self.assertIn(needle, text)

    def test_agents_md_checks_before_done(self):
        # FR6.3: the three existing checks plus doctor and fmt --check, in the "before declaring completion" block.
        text = read("AGENTS.md")
        block = text.split("## Required local checks before declaring completion", 1)[1].split("```bash", 1)[1].split("```", 1)[0]
        lines = [ln for ln in block.splitlines() if ln.strip()]
        for command in ("python3 studio.py validate --all --require-evals", "python3 studio.py evals --all",
                        "python3 -m unittest discover -s tests -v", "python3 studio.py doctor", "python3 studio.py fmt --check"):
            self.assertTrue(any(ln.startswith(command) for ln in lines), "no check line starting with: " + command)

    def test_check_commands_in_agents_md_exist_in_the_engine(self):
        # The two new lines must be commands the engine accepts (no invented positional).
        result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), "doctor"], capture_output=True, text=True,
                                encoding="utf-8", cwd=str(ROOT), timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), "fmt", "--check", "--all"], capture_output=True,
                                text=True, encoding="utf-8", cwd=str(ROOT), timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_install_lines_use_flags_the_engine_accepts_per_harness(self):
        # Phán quyết TK4: Claude has no per-user install (`--user` exits 2), so CLAUDE.md uses --workspace .
        claude = INSTALL.findall(read("CLAUDE.md"))
        self.assertTrue(claude, "CLAUDE.md needs an install line")
        for flags in claude:
            self.assertIn("--agent claude", flags)
            self.assertIn("--workspace .", flags)
            self.assertNotIn("--user", flags)
        gemini = INSTALL.findall(read("GEMINI.md"))
        self.assertTrue(any("--agent antigravity" in f and "--user" in f for f in gemini), "GEMINI.md needs install --user")

    def test_gemini_md_points_to_agents_md_and_harnesses(self):
        text = read("GEMINI.md")
        self.assertIn("`AGENTS.md`", text)
        self.assertIn("`standards/HARNESSES.md`", text)

    def test_repo_paths_extraction(self):
        sample = "see `standards/A.md`, `SKILL.md`, `.claude/skills/<n>/SKILL.md`, `studio.py`, `/skill-creator-studio`, `.agent/`, `.claude-plugin/plugin.json`, [x](b/c.md#h), [y](https://e.org), `--user`"
        self.assertEqual(repo_paths(sample), ["standards/A.md", "studio.py", ".claude-plugin/plugin.json", "b/c.md"])


if __name__ == "__main__":
    unittest.main()
