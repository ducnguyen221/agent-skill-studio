"""The `check` command (SPR-02 TK5, FR5): one command for every document type; `validate` and `audit` stay as aliases.

`check <skill>` gives the result of `validate` plus `"type": "skill"` on every report. A Markdown file that is a workflow
or a rules file is named in an exit-2 message (the checks for those types come in a later stage); a file of no known
type is refused with exit 2. The engine is started as a subprocess, as a user does.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

ROOT = E.ROOT
SKILL = "examples/data-quality-audit"
BROKEN = "evals/skill-creator-studio/fixtures/broken-skill"


def run_engine(*args, cwd=None, engine=None):
    """(exit code, stdout, stderr) of `python studio.py <args>` with the engine under test."""
    proc = subprocess.run([sys.executable, "-X", "utf8", str(engine or E.ENGINE_PATH)] + list(args), cwd=str(cwd or ROOT), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", timeout=300)
    return proc.returncode, proc.stdout, proc.stderr


def with_type(report_json):
    """What `validate --json` prints, with `"type": "skill"` added to every element of `reports` (FR5.2)."""
    data = json.loads(report_json)
    data["reports"] = [{"skill": r["skill"], "type": "skill", "findings": r["findings"]} for r in data["reports"]]
    return data


def can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as t:
        try:
            os.symlink(str(Path(t) / "a"), str(Path(t) / "b"))
        except (OSError, NotImplementedError):
            return False
    return True


class CheckSkillTests(unittest.TestCase):
    def test_check_skill_folder_json_is_validate_plus_type(self):
        """bắt-lỗi (red at 395e621: argparse `invalid choice: 'check'`, exit 2): FR5.2 `check <skill> --json` = `validate` with `"type": "skill"` in every report, same exit code."""
        code_v, out_v, _ = run_engine("validate", SKILL, "--json")
        code_c, out_c, err_c = run_engine("check", SKILL, "--json")
        self.assertEqual((code_v, err_c), (code_c, ""))
        self.assertEqual(with_type(out_v), json.loads(out_c))
        self.assertFalse(json.loads(out_c)["audit"])
        self.assertTrue(all(r["type"] == "skill" for r in json.loads(out_c)["reports"]))

    def test_check_skill_md_file_is_the_same_as_its_folder(self):
        """bắt-lỗi (red at 395e621: exit 2): FR5.2 `check <folder>/SKILL.md` checks that skill; the report names the folder, as `validate <folder>` does."""
        code_v, out_v, _ = run_engine("validate", SKILL, "--json")
        code_c, out_c, err_c = run_engine("check", SKILL + "/SKILL.md", "--json")
        self.assertEqual((code_v, err_c), (code_c, ""))
        self.assertEqual(with_type(out_v), json.loads(out_c))

    def test_check_all_puts_type_on_every_report(self):
        """bắt-lỗi (red at 395e621: exit 2): FR5.2 `check --all --require-evals --json` = `validate --all ...` with `type` on each of the reports."""
        code_v, out_v, _ = run_engine("validate", "--all", "--require-evals", "--json")
        code_c, out_c, err_c = run_engine("check", "--all", "--require-evals", "--json")
        self.assertEqual((code_v, err_c), (code_c, ""))
        self.assertEqual(with_type(out_v), json.loads(out_c))
        # SPR-03 FR15.1, SPR-04 FR9.1 / FR11.5: `--all` walks skills/ only and two skills ship (skill-creator-studio, skill-curator), so two reports
        reports = json.loads(out_c)["reports"]
        self.assertEqual(2, len(reports))
        self.assertTrue(all(r.get("type") == "skill" for r in reports), reports)

    def test_check_text_mode_is_validate_text_mode(self):
        """bắt-lỗi (red at 395e621: exit 2): FR5.2 the text mode of `check` prints exactly what `validate` prints and ends with the same exit code."""
        code_v, out_v, _ = run_engine("validate", BROKEN)
        code_c, out_c, err_c = run_engine("check", BROKEN)
        self.assertEqual((code_v, out_v), (code_c, out_c))
        self.assertEqual(1, code_c)
        self.assertEqual("", err_c)

    def test_check_takes_the_validate_flags(self):
        """bắt-lỗi (red at 395e621: exit 2): FR5.2 --require-evals, --eval-root and --target are accepted and act as in `validate`."""
        for flags in (["--require-evals"], ["--target", "claude-code"], ["--eval-root", str(ROOT / "evals")],
                      ["--require-evals", "--eval-root", str(ROOT / "evals"), "--target", "claude-code"]):
            with self.subTest(flags=flags):
                code_v, out_v, _ = run_engine("validate", BROKEN, "--json", *flags)
                code_c, out_c, err_c = run_engine("check", BROKEN, "--json", *flags)
                self.assertEqual((code_v, err_c), (code_c, ""))
                self.assertEqual(with_type(out_v), json.loads(out_c))

    def test_check_with_nothing_to_check_exits_2_like_validate(self):
        """bắt-lỗi (red at 395e621: the message is argparse's `invalid choice`): FR5.2 no path and no --all -> the `validate` message, exit 2."""
        code_v, _, err_v = run_engine("validate")
        code_c, _, err_c = run_engine("check")
        self.assertEqual((2, 2), (code_v, code_c))
        self.assertIn("provide a skill path or --all", err_c)
        self.assertEqual(err_v, err_c)

    def test_check_missing_path_is_reported_like_validate(self):
        """bắt-lỗi (red at 395e621: exit 2, not 1): FR5.2 a path that is not there gets what `validate` gives (FM1 ERROR, exit 1)."""
        code_v, out_v, _ = run_engine("validate", "skills/no-such-skill", "--json")
        code_c, out_c, _ = run_engine("check", "skills/no-such-skill", "--json")
        self.assertEqual((1, 1), (code_v, code_c))
        self.assertEqual(with_type(out_v), json.loads(out_c))
        self.assertEqual("FM1", json.loads(out_c)["reports"][0]["findings"][0]["code"])

    def test_validate_and_audit_keep_their_answer(self):
        """tương-đương: FR5.1 `validate` JSON has no `type`; `audit` keeps `"audit": true` and its closing line."""
        _, out_v, _ = run_engine("validate", SKILL, "--json")
        self.assertTrue(all("type" not in r for r in json.loads(out_v)["reports"]))
        _, out_a, _ = run_engine("audit", SKILL, "--json")
        self.assertTrue(json.loads(out_a)["audit"])
        self.assertTrue(all("type" not in r for r in json.loads(out_a)["reports"]))
        _, text_a, _ = run_engine("audit", SKILL)
        self.assertIn("AUDIT IS READ-ONLY.", text_a)
        _, text_c, _ = run_engine("check", SKILL)
        self.assertNotIn("AUDIT IS READ-ONLY.", text_c)


class CheckOtherTypesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _doc(self, name, text):
        path = self.tmp / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def test_workflow_and_rules_types_are_checked_not_refused(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): FR8.1 `type: workflow` / `type: rules` in the frontmatter -> the file is checked and the report names the type (SPR-04 TK8; exit 2 in SPR-02)."""
        for kind in ("workflow", "rules"):
            with self.subTest(type=kind):
                path = self._doc("doc-%s.md" % kind, "---\nname: doc\ntype: %s\n---\n\n# Body\n" % kind)
                code, out, err = run_engine("check", "--json", str(path), cwd=self.tmp)
                self.assertEqual(1 if kind == "workflow" else 0, code, err)  # a body with no Kết luận, Bước or Xong khi is a workflow with errors
                self.assertEqual(kind, json.loads(out)["reports"][0]["type"])
                self.assertNotIn("not available yet", err)

    def test_agent_instruction_file_names_are_rules_files(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): FR8.1 AGENTS.md, CLAUDE.md and GEMINI.md are rules files even without frontmatter and are checked (SPR-04 TK8)."""
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            with self.subTest(name=name):
                sub = self.tmp / name.split(".")[0].lower()
                sub.mkdir()
                path = sub / name
                path.write_bytes(b"# Instructions\n\nNo frontmatter here.\n")
                code, out, err = run_engine("check", "--json", str(path), cwd=self.tmp)
                self.assertEqual(0, code, err)
                self.assertEqual("rules", json.loads(out)["reports"][0]["type"])

    def test_markdown_of_unknown_type_exits_2_with_a_message(self):
        """bắt-lỗi (red at 395e621: the message is argparse's, not ours): FR5.3 a .md file with no recognisable type -> exit 2 and a message that names the file."""
        cases = {"plain.md": "# Just a note\n",
                 "other.md": "---\nname: other\ntype: poem\n---\n\ntext\n",
                 "notype.md": "---\nname: notype\ndescription: no type key\n---\n\ntext\n"}
        for name, text in cases.items():
            with self.subTest(name=name):
                path = self._doc(name, text)
                code, out, err = run_engine("check", str(path), cwd=self.tmp)
                self.assertEqual(2, code)
                self.assertIn("cannot tell the document type", err)
                self.assertIn(name, err)
                self.assertNotIn("not available yet", err)
                self.assertEqual("", out)

    def test_file_that_is_not_markdown_exits_2(self):
        """bắt-lỗi (red at 395e621: no `cannot tell the document type`): FR5.3 a file that is not .md has no type either -> exit 2."""
        path = self._doc("notes.txt", "---\ntype: workflow\n---\n")
        code, _, err = run_engine("check", str(path), cwd=self.tmp)
        self.assertEqual(2, code)
        self.assertIn("cannot tell the document type", err)

    @unittest.skipUnless(can_symlink(), "cannot create a symlink here")
    def test_markdown_that_is_a_link_is_not_read(self):
        """bắt-lỗi (red at 395e621: no `link` in the message): the safe-read rules of `validate` hold for `check`: a link is refused with exit 2 and its target is not read."""
        target = self._doc("real.md", "---\nname: real\ntype: workflow\n---\n")
        link = self.tmp / "linked.md"
        os.symlink(str(target), str(link))
        code, out, err = run_engine("check", str(link), cwd=self.tmp)
        self.assertEqual(2, code)
        self.assertIn("link", err)
        self.assertNotIn("not available yet", err)
        self.assertEqual("", out)

    def test_cloud_placeholder_markdown_is_not_read(self):
        """bắt-lỗi (red at 395e621: `resolve_check_path` does not exist): a file Windows marks as a cloud placeholder is refused and never opened (mock: the cloud test says yes, the read is a spy)."""
        path = self._doc("cloudy.md", "---\nname: cloudy\ntype: workflow\n---\n")
        with mock.patch.object(E.fs, "path_is_cloud", return_value=True), mock.patch.object(E.fs, "read_capped") as spy:
            with self.assertRaises(ValueError) as caught:
                E.validate.resolve_check_path(str(path))
        self.assertIn("cloud", str(caught.exception))
        spy.assert_not_called()

    def test_resolve_check_path_unit(self):
        """đơn-vị-hàm-mới: `resolve_check_path` maps a folder or SKILL.md to the skill folder and leaves a missing path to `validate`."""
        folder = ROOT / "examples" / "data-quality-audit"
        self.assertEqual(("skill", folder), E.validate.resolve_check_path(str(folder)))
        self.assertEqual(("skill", folder), E.validate.resolve_check_path(str(folder / "SKILL.md")))
        missing = self.tmp / "no-such-skill"
        self.assertEqual(("skill", missing), E.validate.resolve_check_path(str(missing)))
        self.assertEqual(("skill", self.tmp / "gone"), E.validate.resolve_check_path(str(self.tmp / "gone" / "SKILL.md")))


class Rq029CheckTests(unittest.TestCase):
    """SPR-04 TK2 (FR11.4, FR11.5, RQ-029)."""

    def test_rq029_resolve_check_path_decides_zone_before_any_stat(self):
        """bắt-lỗi (red at c3deee2: `path.is_file()` runs first, so the file in ~/.secret is stat-ed): FR11.4 `check ~/.secret/x.md` is a zone line and no stat, open or is_file reaches the path."""
        home = Path(tempfile.mkdtemp(prefix="studio-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        secret = home / ".secret"
        secret.mkdir()
        (secret / "x.md").write_text("CANARY", encoding="utf-8")
        seen = []
        real = {"stat": os.stat, "lstat": os.lstat, "open": open, "is_file": Path.is_file}

        def spy(name, original):
            def wrapper(target, *a, **k):
                text = os.fspath(target) if not isinstance(target, int) else ""
                if ".secret" in text:
                    seen.append((name, text))
                return original(target, *a, **k)
            return wrapper

        with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
            E.clear_caches()
            self.addCleanup(E.clear_caches)
            with mock.patch.object(os, "stat", spy("stat", real["stat"])), mock.patch.object(os, "lstat", spy("lstat", real["lstat"])),                     mock.patch("builtins.open", spy("open", real["open"])),                     mock.patch.object(Path, "is_file", lambda self, *a, **k: spy("is_file", real["is_file"])(self, *a, **k)):
                with self.assertRaises(ValueError) as caught:
                    E.validate.resolve_check_path(str(secret / "x.md"))
        self.assertIn("secret-zone", str(caught.exception))
        self.assertEqual([], seen, "the path in the forbidden zone was touched")

    def test_rq029_check_all_merges_several_reports_on_a_real_repo(self):
        """bắt-lỗi (red at c3deee2: no test ran `check --all` on two skills): FR11.5 the merged report of two skills is one `reports` list in folder order, the exit code is the worst, and the text output names both."""
        tmp = Path(tempfile.mkdtemp(prefix="studio-two-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / ".claude-plugin").mkdir()
        (tmp / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
        (tmp / "standards").mkdir()
        (tmp / "standards" / "SKILL_AUTHORING_STANDARD.md").write_text("x\n", encoding="utf-8")
        shutil.copytree(E.ENGINE_DIR, tmp / "engine", ignore=shutil.ignore_patterns("__pycache__"))
        good = (ROOT / SKILL / "SKILL.md").read_bytes()
        for name, body in (("alpha", good), ("beta", b"---\nname: beta\n---\n")):
            (tmp / "skills" / name).mkdir(parents=True)
            (tmp / "skills" / name / "SKILL.md").write_bytes(body)
        engine = tmp / "engine" / "studio.py"
        code, out, err = run_engine("check", "--all", "--json", cwd=tmp, engine=engine)
        self.assertEqual(1, code, err)
        reports = json.loads(out)["reports"]
        self.assertEqual(["alpha", "beta"], [Path(r["skill"]).name for r in reports])
        self.assertTrue(all(r["type"] == "skill" for r in reports), reports)
        self.assertFalse([f for f in reports[0]["findings"] if f["level"] == "ERROR" and f["code"] in ("INPUT", "FM1")], reports[0])
        self.assertTrue([f for f in reports[1]["findings"] if f["level"] == "ERROR"], reports[1])
        code_t, out_t, err_t = run_engine("check", "--all", cwd=tmp, engine=engine)
        self.assertEqual(1, code_t)
        self.assertIn("alpha", out_t + err_t)
        self.assertIn("beta", out_t + err_t)


if __name__ == "__main__":
    unittest.main()
