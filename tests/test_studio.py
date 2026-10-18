"""Offline tests for Studio manifest, CLI, package and install.

Run: python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "skills" / "skill-creator-studio" / "scripts" / "studio.py"
SPEC = importlib.util.spec_from_file_location("studio_impl", CODE)
studio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(studio)


class StudioTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "studio.py"), *map(str, args)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_canonical_skills_have_no_static_errors(self):
        for path in studio.skill_dirs(ROOT):
            findings = studio.validate_skill(path, eval_root=ROOT / "evals", require_evals=True)
            self.assertEqual([], [x for x in findings if x["level"] == "ERROR"], path.as_posix())

    def test_every_evals_manifest_is_structurally_valid(self):
        for path in (ROOT / "evals").iterdir():
            if path.is_dir() and any((path / m).exists() for m in ("cases.json", "rubric.md", "fixtures", "baselines", "expected")):
                self.assertFalse([x for x in studio.check_evals(path) if x["level"] == "ERROR"])

    def test_frontmatter_name_and_unsupported_fields_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            skill = Path(t) / "correct-name"
            skill.mkdir()
            (skill / "SKILL.md").write_text('---\nname: Wrong_Name\ndescription: "A test skill. Use when testing name compliance."\ntriggers: all\n---\n\n# Test\n', encoding="utf-8")
            codes = {f["code"] for f in studio.validate_skill(skill) if f["level"] == "ERROR"}
            self.assertIn("FM2", codes)
            self.assertIn("FM4", codes)

    def test_relative_link_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            skill = Path(t) / "sample-safe"
            skill.mkdir()
            (skill / "SKILL.md").write_text('---\nname: sample-safe\ndescription: "Validates names. Use when testing a link."\n---\n\nRead [unsafe](../secret.txt).\n', encoding="utf-8")
            codes = {f["code"] for f in studio.validate_skill(skill) if f["level"] == "ERROR"}
            self.assertIn("ST6", codes)

    def test_new_refuses_overwrite_and_creates_external_empty_evals(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            out = base / "skills"
            evals = base / "evals"
            args = ["new", "test-deep-skill", "--output", str(out), "--eval-root", str(evals), "--description", "Checks data carefully. Use when testing safe skill creation."]
            p = self.run_cli(*args)
            self.assertEqual(0, p.returncode, p.stderr)
            self.assertTrue((out / "test-deep-skill" / "SKILL.md").exists())
            self.assertFalse((out / "test-deep-skill" / "evals").exists())
            cases = json.loads((evals / "test-deep-skill" / "cases.json").read_text())["cases"]
            self.assertEqual(3, len(cases))
            self.assertEqual({True, False}, {c["should_trigger"] for c in cases})
            self.assertTrue(all(c["prompt"].startswith("STUDIO-DRAFT: ") for c in cases))
            name = "test-deep-skill"
            self.assertEqual([(name + "-typical", "typical", True), (name + "-edge", "edge", True), (name + "-negative", "near-miss", False)],
                             [(c["id"], c["kind"], c["should_trigger"]) for c in cases])
            self.assertTrue(all(c["fixtures"] == [] for c in cases))
            self.assertTrue(all(c["expected_behaviors"] and all(b.startswith("STUDIO-DRAFT: ") for b in c["expected_behaviors"]) for c in cases))
            self.assertNotIn(">=3 eval cases", p.stdout)
            self.assertFalse([f for f in studio.check_evals(evals / "test-deep-skill") if f["level"] == "ERROR"])
            self.assertEqual(1, self.run_cli(*args).returncode, "second creation should refuse overwrite")
            self.assertEqual(1, self.run_cli("package", out / "test-deep-skill", "--out", base / "dist").returncode, "draft cannot publish")

    def test_ev4_message_names_plural_key(self):
        with tempfile.TemporaryDirectory() as t:
            ef = Path(t) / "x"
            ef.mkdir()
            (ef / "cases.json").write_text(json.dumps({"skill_name": "x", "cases": [
                {"id": "a", "prompt": "p", "should_trigger": True, "expected_behaviors": []}]}), encoding="utf-8")
            msgs = [f["message"] for f in studio.check_evals(ef) if f["code"] == "EV4"]
            self.assertTrue(any("expected_behaviors" in m for m in msgs), msgs)

    def run_evals_all(self, er):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), "evals", "--all", "--eval-root", str(er)],
                              cwd=ROOT, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_evals_all_skips_folder_with_no_eval_files_but_not_a_broken_eval(self):
        with tempfile.TemporaryDirectory() as t:
            er = Path(t)
            (er / "misc-helpers").mkdir()
            (er / "misc-helpers" / "helper.py").write_text("x = 1\n", encoding="utf-8")
            p = self.run_evals_all(er)
            self.assertEqual(0, p.returncode, p.stdout + p.stderr)
            (er / "half-done").mkdir()
            (er / "half-done" / "rubric.md").write_text("# r\n", encoding="utf-8")
            p = self.run_evals_all(er)
            self.assertEqual(1, p.returncode, "a folder with eval files but no cases.json is still an error")
            self.assertIn("EV1", p.stdout)

    def test_packaged_factory_matches_root_studio(self):
        self.assertEqual((ROOT / "studio.py").read_bytes(), (ROOT / "skills/skill-creator-studio/scripts/studio.py").read_bytes())

    def test_package_is_runtime_only(self):
        with tempfile.TemporaryDirectory() as t:
            package_dir = Path(t)
            run = self.run_cli("package", "skills/data-quality-audit", "--out", package_dir)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            zip_path = package_dir / "data-quality-audit.zip"
            self.assertTrue(zip_path.is_file())
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                self.assertIn("data-quality-audit/SKILL.md", names)
                self.assertFalse(any("evals/" in x or "__pycache__" in x for x in names))

    def test_package_rejects_secret_file(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t) / "demo-skill"
            folder.mkdir()
            (folder / "SKILL.md").write_text('---\nname: demo-skill\ndescription: "Checks inputs. Use when testing security."\n---\n\n# Demo\n', encoding="utf-8")
            (folder / ".env").write_text("PASSWORD=secret", encoding="utf-8")
            files, findings = studio.ensure_distributable(folder)
            self.assertTrue(any(x["code"] == "SEC" and x["level"] == "ERROR" for x in findings))

    def test_install_copy_and_no_implicit_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            workspace = Path(t)
            first = self.run_cli("install", "skills/data-quality-audit", "--agent", "codex", "--workspace", workspace)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            self.assertTrue((workspace / ".agents" / "skills" / "data-quality-audit" / "SKILL.md").is_file())
            self.assertEqual(1, self.run_cli("install", "skills/data-quality-audit", "--agent", "antigravity", "--workspace", workspace).returncode)
            claude = self.run_cli("install", "skills/data-quality-audit", "--agent", "claude", "--workspace", workspace)
            self.assertEqual(0, claude.returncode, claude.stdout + claude.stderr)
            self.assertTrue((workspace / ".claude" / "skills" / "data-quality-audit" / "SKILL.md").exists())

    def test_install_refuses_self_overwrite_even_with_force(self):
        with tempfile.TemporaryDirectory() as t:
            workspace = Path(t)
            src = workspace / ".agents" / "skills" / "data-quality-audit"
            src.parent.mkdir(parents=True)
            import shutil
            shutil.copytree(ROOT / "skills" / "data-quality-audit", src)
            attempt = self.run_cli("install", src, "--agent", "codex", "--workspace", workspace, "--force")
            self.assertEqual(1, attempt.returncode)
            self.assertTrue((src / "SKILL.md").exists())

    def test_standalone_factory_runs_from_packaged_skill(self):
        with tempfile.TemporaryDirectory() as t:
            temp = Path(t)
            packed = self.run_cli("package", "skills/skill-creator-studio", "--out", temp)
            self.assertEqual(0, packed.returncode, packed.stdout + packed.stderr)
            with zipfile.ZipFile(temp / "skill-creator-studio.zip") as zf:
                zf.extractall(temp / "installed")
            factory = temp / "installed" / "skill-creator-studio" / "scripts" / "studio.py"
            run = subprocess.run([sys.executable, str(factory), "new", "external-skill", "--output", str(temp / "skills"), "--eval-root", str(temp / "evals"), "--description", "Checks external data. Use when testing portability outside Studio."], text=True, capture_output=True)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertTrue((temp / "skills" / "external-skill" / "SKILL.md").is_file())
            self.assertTrue((temp / "evals" / "external-skill" / "cases.json").is_file())

    def test_template_mirror_matches(self):
        run = self.run_cli("sync-template", "--check")
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)

    def test_registry_matches_skill_folders(self):
        obj = json.loads((ROOT / "registry" / "catalog.json").read_text(encoding="utf-8"))
        catalog_names = {x["name"] for x in obj["skills"]}
        actual_names = {x.name for x in studio.skill_dirs(ROOT)}
        self.assertEqual(actual_names, catalog_names)
        for x in obj["skills"]:
            self.assertTrue((ROOT / x["path"] / "SKILL.md").is_file())
            self.assertTrue((ROOT / x["evals"] / "cases.json").is_file())
            self.assertFalse(x["model_evaluated"], "avoid fabricated model-test claims in initial delivery")


if __name__ == "__main__":
    unittest.main()
