"""Offline checks: plugin manifests are valid JSON and agree on one version.

Run: python3 -m unittest discover -s tests -v
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
CODEX_PLUGIN = ROOT / ".codex-plugin" / "plugin.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class PluginManifestTests(unittest.TestCase):
    def test_manifests_are_valid_json(self):
        for path in (CLAUDE_PLUGIN, MARKETPLACE, CODEX_PLUGIN):
            self.assertIsInstance(load(path), dict, path.as_posix())

    def test_three_manifests_share_studio_version(self):
        studio_version = re.search(r'^VERSION = "([^"]+)"', (ROOT / "studio.py").read_text(encoding="utf-8"), re.M).group(1)
        versions = {
            "claude": load(CLAUDE_PLUGIN)["version"],
            "codex": load(CODEX_PLUGIN)["version"],
            "marketplace": load(MARKETPLACE)["plugins"][0]["version"],
        }
        self.assertEqual({studio_version}, set(versions.values()), versions)

    def test_names_and_skills_dir(self):
        self.assertEqual("agent-skill-studio", load(MARKETPLACE)["name"])
        entry = load(MARKETPLACE)["plugins"][0]
        self.assertEqual("agent-skill-studio", entry["name"])
        self.assertEqual("./", entry["source"])
        for path in (CLAUDE_PLUGIN, CODEX_PLUGIN):
            data = load(path)
            self.assertEqual("agent-skill-studio", data["name"])
            self.assertTrue((ROOT / data["skills"]).is_dir())
        self.assertEqual("./skills/", load(CLAUDE_PLUGIN)["skills"])
        self.assertEqual("./skills/", load(CODEX_PLUGIN)["skills"])
        skill_dirs = [d for d in (ROOT / "skills").iterdir() if d.is_dir()]
        self.assertTrue(skill_dirs)
        for d in skill_dirs:
            self.assertTrue((d / "SKILL.md").is_file(), d.as_posix())


if __name__ == "__main__":
    unittest.main()
