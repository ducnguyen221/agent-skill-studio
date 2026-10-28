"""The `check` command (SPR-02 TK5, FR5): one command for every document type; `validate` and `audit` stay as aliases.

`check <skill>` gives the result of `validate` plus `"type": "skill"` on every report. A Markdown file that is a workflow
or a rules file is named in an exit-2 message (the checks for those types come in a later stage); a file of no known
type is refused with exit 2. The engine is started as a subprocess, as a user does.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

ROOT = E.ROOT
SKILL = "skills/data-quality-audit"
BROKEN = "evals/skill-creator-studio/fixtures/broken-skill"


def run_engine(*args, cwd=None):
    """(exit code, stdout, stderr) of `python studio.py <args>` with the engine under test."""
    proc = subprocess.run([sys.executable, "-X", "utf8", str(E.ENGINE_PATH)] + list(args), cwd=str(cwd or ROOT), stdin=subprocess.DEVNULL,
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
        self.assertGreaterEqual(len(json.loads(out_c)["reports"]), 2)

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

    def test_workflow_and_rules_types_exit_2_not_available_yet(self):
        """bắt-lỗi (red at 395e621: argparse `invalid choice`, no `not available yet`): FR5.3 `type: workflow` / `type: rules` in the frontmatter -> exit 2 naming the type."""
        for kind in ("workflow", "rules"):
            with self.subTest(type=kind):
                path = self._doc("doc-%s.md" % kind, "---\nname: doc\ntype: %s\n---\n\n# Body\n" % kind)
                code, out, err = run_engine("check", str(path), cwd=self.tmp)
                self.assertEqual(2, code)
                self.assertIn("check for type %s is not available yet" % kind, err)
                self.assertEqual("", out)

    def test_agent_instruction_file_names_exit_2_not_available_yet(self):
        """bắt-lỗi (red at 395e621: no `not available yet`): FR5.3 AGENTS.md, CLAUDE.md and GEMINI.md are rules files even without frontmatter."""
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            with self.subTest(name=name):
                sub = self.tmp / name.split(".")[0].lower()
                sub.mkdir()
                path = sub / name
                path.write_bytes(b"# Instructions\n\nNo frontmatter here.\n")
                code, out, err = run_engine("check", str(path), cwd=self.tmp)
                self.assertEqual(2, code)
                self.assertIn("check for type rules is not available yet", err)
                self.assertEqual("", out)

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
        folder = ROOT / "skills" / "data-quality-audit"
        self.assertEqual(folder, E.validate.resolve_check_path(str(folder)))
        self.assertEqual(folder, E.validate.resolve_check_path(str(folder / "SKILL.md")))
        missing = self.tmp / "no-such-skill"
        self.assertEqual(missing, E.validate.resolve_check_path(str(missing)))
        self.assertEqual(self.tmp / "gone", E.validate.resolve_check_path(str(self.tmp / "gone" / "SKILL.md")))


if __name__ == "__main__":
    unittest.main()
