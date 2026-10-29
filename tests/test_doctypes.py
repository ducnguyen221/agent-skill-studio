"""SPR-04 TK8 (FR8, SC7): `check` lints workflow and agent-rules files by `standards/DOC_TYPES.md`, and `doctor --docs` reports them.

Every code has a red case and a green case (WC1-WC4, RL1-RL4, SEC); the green rules case holds the `📜 … CHANGELOG … mốc` pointer line.
The Studio's own AGENTS.md, CLAUDE.md and GEMINI.md exit 0. A file of no known type still exits 2.

Run: python -X utf8 -m unittest tests.test_doctypes -v
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine as E  # noqa: E402

D = importlib.import_module("studio_doctypes")  # the engine put its folder on sys.path when _engine loaded it
ROOT = E.ROOT
FIX = ROOT / "tests" / "fixtures" / "doctypes"
engine, fs, doctor = E.engine, E.fs, E.doctor


def cli(*argv):
    """(exit code, stdout, stderr) of `studio.py <argv>` run in this process."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = engine.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def codes(findings) -> list:
    return sorted(f["code"] for f in findings)


def workflow(path: Path) -> list:
    return D.lint_workflow(path, path.read_text(encoding="utf-8"))


def rules(path: Path, siblings=None) -> list:
    return D.lint_rules(path, path.read_text(encoding="utf-8"), D.siblings_of(path) if siblings is None else siblings)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        E.clear_caches()
        self.addCleanup(E.clear_caches)

    def write(self, rel: str, text: str) -> Path:
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path


GOOD_WORKFLOW = "# Việc\n\n> **Kết luận:** việc này làm một thứ.\n\n## Bước\n\n1. Làm; kiểm bằng lệnh.\n\n## Xong khi\n\nXong; lỗi thì quay lại.\n"


class DocTypeTests(unittest.TestCase):
    def test_doc_type_by_name_type_and_folder(self):
        """tương-đương: FR8.1 SKILL.md is a skill; AGENTS.md, CLAUDE.md, GEMINI.md (any case) are rules; `type:` names workflow or rules; a file under workflows/ is a workflow."""
        self.assertEqual("skill", D.doc_type(Path("x/SKILL.md"), {}))
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "agents.md"):
            self.assertEqual("rules", D.doc_type(Path("x") / name, {}), name)
        self.assertEqual("workflow", D.doc_type(Path("x/note.md"), {"type": "workflow"}))
        self.assertEqual("rules", D.doc_type(Path("x/note.md"), {"type": "rules"}))
        self.assertEqual("workflow", D.doc_type(Path("plugin/workflows/deep/note.md"), {}))
        self.assertEqual("workflow", D.doc_type(Path("plugin/Workflows/note.md"), {}))

    def test_doc_type_none_when_nothing_tells(self):
        """bắt-lỗi (red at e92d4d2: no studio_doctypes): FR8.1 no type, no rules name, no workflows/ folder, or a type that is not ours -> None (check exits 2)."""
        self.assertIsNone(D.doc_type(Path("x/README.md"), {}))
        self.assertIsNone(D.doc_type(Path("x/note.md"), {"type": "poem"}))
        self.assertIsNone(D.doc_type(Path("x/note.md"), {"type": ["workflow"]}))
        self.assertIsNone(D.doc_type(Path("x/workflows-notes/note.md"), {}))

    def test_declared_type_beats_the_folder(self):
        """tương-đương: FR8.1 a file in workflows/ that says `type: rules` is a rules file."""
        self.assertEqual("rules", D.doc_type(Path("plugin/workflows/x.md"), {"type": "rules"}))


class WorkflowTests(TmpCase):
    def test_good_workflow_is_clean(self):
        """tương-đương: FR8.2 a workflow with Kết luận, numbered Bước and Xong khi has no finding."""
        self.assertEqual([], workflow(FIX / "workflows" / "ok.md"))
        self.assertEqual([], workflow(FIX / "typed" / "flow-by-type.md"))  # English headings: Steps, Done when

    def test_wf1_conclusion_missing_or_too_far(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): WC1 ERROR when the Kết luận line is missing, or comes after the first 15 body lines."""
        found = workflow(FIX / "workflows" / "wf1-no-conclusion.md")
        self.assertEqual(["WC1"], codes(found))
        self.assertEqual("ERROR", found[0]["level"])
        self.assertEqual(["WC1"], codes(D.lint_workflow(Path("w.md"), GOOD_WORKFLOW.replace("> **Kết luận:**", "Việc này:"))))

    def test_wf1_conclusion_forms_and_the_window(self):
        """tương-đương: WC1 accepts `> **Kết luận:**` and `**Kết luận:**`, counts 15 lines from the body start (after the frontmatter), and ignores one inside a code fence."""
        plain = GOOD_WORKFLOW.replace("> **Kết luận:**", "**Kết luận:**")
        self.assertEqual([], D.lint_workflow(Path("w.md"), plain))
        framed = "---\ntitle: x\ntype: workflow\n---\n" + plain
        self.assertEqual([], D.lint_workflow(Path("w.md"), framed))
        fenced = GOOD_WORKFLOW.replace("> **Kết luận:** việc này làm một thứ.", "```\n> **Kết luận:** trong khối mã.\n```")
        self.assertEqual(["WC1"], codes(D.lint_workflow(Path("w.md"), fenced)))
        last = "# T\n" + "x\n" * 13 + "**Kết luận:** dòng thứ 15 của thân.\n" + GOOD_WORKFLOW.split("\n", 3)[3]
        self.assertEqual([], [f for f in D.lint_workflow(Path("w.md"), last) if f["code"] == "WC1"])
        late = "# T\n" + "x\n" * 14 + "**Kết luận:** dòng thứ 16.\n" + GOOD_WORKFLOW.split("\n", 3)[3]
        self.assertEqual(["WC1"], [f["code"] for f in D.lint_workflow(Path("w.md"), late) if f["code"] == "WC1"])

    def test_wf1_conclusion_in_decomposed_unicode(self):
        """tương-đương: WC1 a file saved with decomposed (NFD) Vietnamese still has its Kết luận."""
        import unicodedata
        self.assertEqual([], D.lint_workflow(Path("w.md"), unicodedata.normalize("NFD", GOOD_WORKFLOW)))

    def test_wf2_steps_not_numbered(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): WC2 ERROR when no numbered list sits under a heading with Bước or Steps."""
        self.assertEqual(["WC2"], codes(workflow(FIX / "workflows" / "wf2-no-steps.md")))

    def test_wf2_list_must_be_under_the_steps_heading(self):
        """bắt-lỗi (red at e92d4d2: no studio_doctypes): WC2 a numbered list under another heading, or one inside a code fence, is not the steps; a list under a sub-heading of Bước is."""
        other = GOOD_WORKFLOW.replace("## Bước\n\n1. Làm; kiểm bằng lệnh.", "## Bước\n\nLàm theo thứ tự.\n\n## Ghi chú\n\n1. Một điều.")
        self.assertEqual(["WC2"], codes(D.lint_workflow(Path("w.md"), other)))
        fenced = GOOD_WORKFLOW.replace("1. Làm; kiểm bằng lệnh.", "```\n1. Làm; kiểm bằng lệnh.\n```")
        self.assertEqual(["WC2"], codes(D.lint_workflow(Path("w.md"), fenced)))
        nested = GOOD_WORKFLOW.replace("## Bước\n\n1. Làm;", "## Bước\n\n### Chuẩn bị\n\n1. Làm;")
        self.assertEqual([], D.lint_workflow(Path("w.md"), nested))
        paren = GOOD_WORKFLOW.replace("1. Làm;", "1) Làm;")
        self.assertEqual([], D.lint_workflow(Path("w.md"), paren))

    def test_wf3_done_when_missing(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): WC3 ERROR when there is no Xong khi / Done when heading."""
        self.assertEqual(["WC3"], codes(workflow(FIX / "workflows" / "wf3-no-done.md")))

    def test_wf4_over_300_lines_is_a_warning(self):
        """bắt-lỗi (red at e92d4d2: no studio_doctypes): WC4 WARN at 301 lines; 300 lines is clean."""
        pad = "Một dòng đệm.\n"
        base = GOOD_WORKFLOW.count("\n")
        ok = D.lint_workflow(Path("w.md"), GOOD_WORKFLOW + pad * (300 - base))
        self.assertEqual([], ok)
        found = D.lint_workflow(Path("w.md"), GOOD_WORKFLOW + pad * (301 - base))
        self.assertEqual(["WC4"], codes(found))
        self.assertEqual("WARN", found[0]["level"])
        self.assertEqual(301, found[0]["line"])

    def test_secret_in_a_workflow_is_sec(self):
        """bắt-lỗi (red at e92d4d2: no studio_doctypes): SEC ERROR on the line that holds a key; the same text without the key is clean."""
        key = "sk-" + "a1" * 20
        found = D.lint_workflow(Path("w.md"), GOOD_WORKFLOW + "Khoá: %s\n" % key)
        self.assertEqual(["SEC"], codes(found))
        self.assertEqual("ERROR", found[0]["level"])
        self.assertEqual(GOOD_WORKFLOW.count("\n") + 1, found[0]["line"])
        self.assertEqual([], D.lint_workflow(Path("w.md"), GOOD_WORKFLOW + "Khoá: sk-ngắn\n"))


class RulesTests(TmpCase):
    def test_rules_ok_folder_is_clean(self):
        """tương-đương: FR8.3 a rules set with the 📜 pointer (hash and all), superseded keys, one check block and an install line in a sentence has no finding."""
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            self.assertEqual([], rules(FIX / "rules-ok" / name), name)

    def test_rl1_over_200_lines_is_a_warning(self):
        """bắt-lỗi (red at e92d4d2: no studio_doctypes): RL1 WARN at 201 lines; 200 lines is clean."""
        self.assertEqual([], D.lint_rules(Path("AGENTS.md"), "- luật, vì lý do.\n" * 200, set()))
        found = D.lint_rules(Path("AGENTS.md"), "- luật, vì lý do.\n" * 201, set())
        self.assertEqual(["RL1"], codes(found))
        self.assertEqual("WARN", found[0]["level"])

    def test_rl2_history_lines(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): RL2 ERROR on «đổi từ bản» and on a hash after the word commit, each on its own line."""
        found = rules(FIX / "rl2-bad" / "AGENTS.md")
        self.assertEqual(["RL2", "RL2"], codes(found))
        self.assertEqual([3, 5], sorted(f["line"] for f in found))
        self.assertEqual(["RL2"], codes(D.lint_rules(Path("AGENTS.md"), "- Luật này changed from v2 sang v3.\n", set())))

    def test_rl2_pointer_and_supersede_keys_are_not_history(self):
        """tương-đương: FR8.3 the `📜 … CHANGELOG … mốc` pointer and the superseded / supersedes: keys are exempt, even with a hash or «đổi từ bản» on the line."""
        text = ("📜 Lịch sử: docs/CHANGELOG.md — mốc 2026-10-28 (commit 1a2b3c4d5e)\n"
                "supersedes: luật đổi từ bản 1\n"
                "status: superseded\n"
                "- superseded_by: commit 1a2b3c4d5e\n")
        self.assertEqual([], D.lint_rules(Path("AGENTS.md"), text, set()))
        no_mark = "📜 Lịch sử: docs/CHANGELOG.md (commit 1a2b3c4d5e)\n"  # no `mốc`: an ordinary history line
        self.assertEqual(["RL2"], codes(D.lint_rules(Path("AGENTS.md"), no_mark, set())))

    def test_rl2_commit_without_hash_or_hash_without_commit_is_fine(self):
        """tương-đương: RL2 the word commit alone, or a hex-looking token with no commit before it, is not a history line."""
        self.assertEqual([], D.lint_rules(Path("AGENTS.md"), "- Không commit secret, vì lộ khoá.\n- Mã 1a2b3c4d5e là id.\n", set()))
        self.assertEqual(["RL2"], codes(D.lint_rules(Path("AGENTS.md"), "- Xem commit 1a2b3c4 để biết thêm.\n", set())))

    def test_rl3_command_block_outside_the_check_section(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): RL3 ERROR for a fenced shell block under a heading without kiểm or check."""
        found = rules(FIX / "rl3-bad" / "AGENTS.md")
        self.assertEqual(["RL3"], codes(found))
        self.assertEqual(7, found[0]["line"])

    def test_rl3_allowed_and_not_commands(self):
        """tương-đương: RL3 a block under Kiểm / Check (also an outer heading), a block that is data (json, text, diff), and an install line in a sentence are fine."""
        check = "# Luật\n\n## Local checks\n\n### Chạy\n\n```bash\npython -m unittest\n```\n"
        self.assertEqual([], D.lint_rules(Path("AGENTS.md"), check, set()))
        data = "# Luật\n\n```json\n{\"a\": 1}\n```\n\n```text\nmột đoạn văn thường\n```\n\n```\nchỉ là chữ, không phải lệnh\n```\n"
        self.assertEqual([], D.lint_rules(Path("AGENTS.md"), data, set()))
        self.assertEqual([], D.lint_rules(Path("AGENTS.md"), "# Luật\n\n```bash\n# chỉ có chú thích\n```\n", set()))
        inline = "# Luật\n\nCài bằng `python3 studio.py install skills/x --agent claude` rồi mở phiên mới.\n"
        self.assertEqual([], D.lint_rules(Path("AGENTS.md"), inline, set()))

    def test_rl3_unlabelled_and_unclosed_blocks(self):
        """bắt-lỗi (red at e92d4d2: no studio_doctypes): RL3 an unlabelled fence whose line starts like a command, a `~~~` fence and a fence never closed are all caught."""
        bare = "# Luật\n\n```\n$ python studio.py install x\n```\n"
        self.assertEqual(["RL3"], codes(D.lint_rules(Path("AGENTS.md"), bare, set())))
        tilde = "# Luật\n\n~~~sh\nnpm install\n~~~\n"
        self.assertEqual(["RL3"], codes(D.lint_rules(Path("AGENTS.md"), tilde, set())))
        unclosed = "# Luật\n\n```powershell\ndocker build .\n"
        self.assertEqual(["RL3"], codes(D.lint_rules(Path("AGENTS.md"), unclosed, set())))
        longer = "# Luật\n\n````bash\npip install x\n```\nvẫn trong khối\n````\n\nHết.\n"
        self.assertEqual(["RL3"], codes(D.lint_rules(Path("AGENTS.md"), longer, set())))

    def test_rl4_adapter_must_name_agents_md(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): RL4 ERROR for a CLAUDE.md that does not name AGENTS.md while AGENTS.md sits beside it."""
        found = rules(FIX / "rl4-bad" / "CLAUDE.md")
        self.assertEqual(["RL4"], codes(found))
        self.assertEqual([], rules(FIX / "rl4-bad" / "AGENTS.md"))

    def test_rl4_quiet_without_sibling_or_with_the_name(self):
        """tương-đương: RL4 stays quiet when no AGENTS.md is in the folder (any case of the name counts when there is), and for AGENTS.md itself; GEMINI.md is judged like CLAUDE.md."""
        text = "# Adapter\n\nKhông nêu file nguồn.\n"
        self.assertEqual([], D.lint_rules(Path("CLAUDE.md"), text, {"README.md"}))
        self.assertEqual(["RL4"], codes(D.lint_rules(Path("CLAUDE.md"), text, {"agents.md"})))
        self.assertEqual(["RL4"], codes(D.lint_rules(Path("GEMINI.md"), text, {"AGENTS.md"})))
        self.assertEqual([], D.lint_rules(Path("AGENTS.md"), text, {"AGENTS.md"}))
        self.assertEqual([], D.lint_rules(Path("CLAUDE.md"), "@AGENTS.md\n", {"AGENTS.md"}))

    def test_secret_in_a_rules_file_is_sec(self):
        """bắt-lỗi (red at e92d4d2: no studio_doctypes): SEC ERROR for a key in a rules file; one AKIA key and one private-key header are both found."""
        for secret in ("AKIA" + "ABCDEFGHIJKLMNOP", "ghp_" + "a1" * 16, "-----BEGIN " + "PRIVATE KEY-----"):
            with self.subTest(secret=secret[:6]):
                found = D.lint_rules(Path("AGENTS.md"), "# Luật\n\n- Khoá: %s\n" % secret, set())
                self.assertEqual(["SEC"], codes(found))
                self.assertEqual(3, found[0]["line"])

    def test_siblings_of_a_folder_that_cannot_be_listed(self):
        """độ-phủ: a folder that cannot be listed gives no siblings, so RL4 stays quiet instead of crashing."""
        self.assertEqual(set(), D.siblings_of(self.tmp / "gone" / "CLAUDE.md"))
        self.write("CLAUDE.md", "x")
        self.assertEqual({"CLAUDE.md"}, D.siblings_of(self.tmp / "CLAUDE.md"))

    def test_rules_file_of_studio_clean(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): SC7 the Studio's AGENTS.md, CLAUDE.md and GEMINI.md exit 0 from `check`, in the repo and as the copies kept in the fixtures."""
        for base in (ROOT, FIX / "studio-rules"):
            for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
                with self.subTest(base=base.name, name=name):
                    code, out, err = cli("check", str(base / name))
                    self.assertEqual((0, ""), (code, err), out)
                    self.assertIn("0 errors; 0 warnings", out)


class CheckCommandTests(TmpCase):
    def test_check_workflow_text_and_exit_codes(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): FR8.1 a file in workflows/ with no `type:` is checked as a workflow: exit 0 clean, exit 1 with an ERROR, WARN alone exits 0."""
        code, out, err = cli("check", str(FIX / "workflows" / "ok.md"))
        self.assertEqual((0, ""), (code, err), out)
        code, out, err = cli("check", str(FIX / "workflows" / "wf1-no-conclusion.md"))
        self.assertEqual(1, code, err)
        self.assertIn("ERROR WC1", out)
        long_flow = self.write("workflows/long.md", GOOD_WORKFLOW + "Một dòng đệm.\n" * 300)
        code, out, err = cli("check", str(long_flow))
        self.assertEqual(0, code, err)
        self.assertIn("WARN  WC4", out)

    def test_check_workflow_by_type_outside_workflows_folder(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): FR8.1 `type: workflow` in the frontmatter is enough, wherever the file lies; --json reports type and findings."""
        code, out, err = cli("check", "--json", str(FIX / "typed" / "flow-by-type.md"))
        self.assertEqual(0, code, err)
        report = json.loads(out)["reports"][0]
        self.assertEqual(("workflow", []), (report["type"], report["findings"]))
        self.assertTrue(report["skill"].endswith("flow-by-type.md"))

    def test_check_rules_by_type_and_by_name(self):
        """bắt-lỗi (red at e92d4d2: exit 2 `not available yet`): FR8.1 `type: rules` or a rules name is checked as rules; the RL findings reach the report and exit 1."""
        code, out, err = cli("check", "--json", str(FIX / "typed" / "rules-by-type.md"))
        self.assertEqual((0, "rules"), (code, json.loads(out)["reports"][0]["type"]), err)
        code, out, err = cli("check", "--json", str(FIX / "rl4-bad" / "CLAUDE.md"))
        self.assertEqual(1, code, err)
        report = json.loads(out)["reports"][0]
        self.assertEqual(("rules", ["RL4"]), (report["type"], codes(report["findings"])))

    def test_unknown_type_exit_2(self):
        """tương-đương: FR8.1 a file with no type, rules name or workflows/ folder still exits 2 with the message of SPR-02, nothing on stdout."""
        for path in (FIX / "typed" / "plain.md", ROOT / "README.md"):
            code, out, err = cli("check", str(path))
            self.assertEqual(2, code, path)
            self.assertIn("cannot tell the document type", err)
            self.assertEqual("", out)

    def test_check_refuses_a_rules_file_that_is_a_cloud_placeholder_before_reading(self):
        """bắt-lỗi (red at e92d4d2: the name test ran before the link and cloud tests): AGENTS.md as a placeholder or a link is refused with exit 2 and never read."""
        path = self.write("AGENTS.md", "# Luật\n")
        with mock.patch.object(fs, "path_is_cloud", return_value=True), mock.patch.object(fs, "read_capped") as spy:
            code, out, err = cli("check", str(path))
        self.assertEqual(2, code)
        self.assertIn("cloud placeholder", err)
        spy.assert_not_called()
        with mock.patch.object(fs, "is_link", return_value=True), mock.patch.object(fs, "read_capped") as spy:
            code, out, err = cli("check", str(path))
        self.assertEqual(2, code)
        self.assertIn("symlink or junction", err)
        spy.assert_not_called()

    def test_check_refuses_a_rules_file_in_a_secret_zone_before_any_stat(self):
        """tương-đương: TK2 order kept: a CLAUDE.md under .secret is a zone line, exit 2, and the file is not read."""
        zone = self.tmp / ".secret"
        zone.mkdir()
        (zone / "CLAUDE.md").write_text("CANARY", encoding="utf-8")
        with mock.patch.object(fs, "read_capped") as spy:
            code, out, err = cli("check", str(zone / "CLAUDE.md"))
        self.assertEqual(2, code)
        self.assertIn("secret", err)
        spy.assert_not_called()

    def test_check_document_not_read_exits_2(self):
        """bắt-lỗi (red at e92d4d2: no studio_doctypes): a rules file that is too big or not UTF-8 is refused with exit 2 and the reason."""
        big = self.write("big/AGENTS.md", "- luật, vì lý do.\n" * 10)
        with mock.patch.object(E.const, "DOCTOR_MAX_FILE_BYTES", 20):
            code, out, err = cli("check", str(big))
        self.assertEqual(2, code)
        self.assertIn("larger than 20 bytes", err)
        raw = self.tmp / "raw" / "AGENTS.md"
        raw.parent.mkdir()
        raw.write_bytes(b"\xff\xfe\x00\x80")
        code, out, err = cli("check", str(raw))
        self.assertEqual(2, code)
        self.assertIn("UTF-8", err)

    def test_check_document_that_vanishes_between_the_type_and_the_read_exits_2(self):
        """độ-phủ: a file that cannot be read when the check opens it is exit 2 with a reason, not a crash."""
        path = self.write("workflows/gone.md", GOOD_WORKFLOW)
        with mock.patch.object(D, "read_document", return_value=(None, "cannot be read as UTF-8 text: gone")):
            code, out, err = cli("check", str(path))
        self.assertEqual(2, code)
        self.assertIn("cannot be read", err)

    def test_check_all_still_means_skills(self):
        """tương-đương: `check --all` and `check` with no path keep their SPR-02 behaviour; the document branch is not taken."""
        code, out, err = cli("check")
        self.assertEqual(2, code)
        self.assertIn("provide a skill path or --all", err)

    def test_read_document_reports_each_refusal(self):
        """độ-phủ: read_document says why for a zone, a link, a placeholder, a big file and a file that is not UTF-8; and gives the text otherwise."""
        path = self.write("a/AGENTS.md", "# Luật\n")
        self.assertEqual(("# Luật\n", None), D.read_document(path))
        with mock.patch.object(fs, "is_link", return_value=True):
            self.assertIn("symlink", D.read_document(path)[1])
        with mock.patch.object(fs, "path_is_cloud", return_value=True):
            self.assertIn("cloud placeholder", D.read_document(path)[1])
        with mock.patch.object(fs, "read_capped", side_effect=OSError("nope")):
            self.assertIn("cannot be read", D.read_document(path)[1])
        with mock.patch.object(E.const, "DOCTOR_MAX_FILE_BYTES", 3):
            self.assertIn("larger than 3 bytes", D.read_document(path)[1])
        raw = self.tmp / "b" / "AGENTS.md"
        raw.parent.mkdir()
        raw.write_bytes(b"\xff\xfe\x00\x80")
        self.assertIn("UTF-8", D.read_document(raw)[1])


class DoctorDocsTests(TmpCase):
    def plugin(self, name="demo") -> Path:
        base = self.tmp / name
        (base / ".claude-plugin").mkdir(parents=True)
        (base / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
        skill = base / "skills" / "one"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: one\ndescription: Checks a toy. Use when testing docs.\n---\n\n# Title\n\nShort body.\n", encoding="utf-8")
        return base

    def report(self, base: Path, **kw) -> dict:
        return doctor.doctor_run([base / "skills"], "portable", "portable", False, None, **kw)

    def test_docs_lists_rules_and_workflow_files_of_each_plugin(self):
        """bắt-lỗi (red at e92d4d2: no `docs` key): FR8.4 `docs` holds the rules files at the plugin root and the files under workflows/, each with type and codes; clean files have no codes."""
        base = self.plugin()
        shutil.copy(FIX / "rl4-bad" / "AGENTS.md", base / "AGENTS.md")
        shutil.copy(FIX / "rl4-bad" / "CLAUDE.md", base / "CLAUDE.md")
        (base / "workflows").mkdir()
        shutil.copy(FIX / "workflows" / "ok.md", base / "workflows" / "ok.md")
        shutil.copy(FIX / "workflows" / "wf3-no-done.md", base / "workflows" / "wf3.md")
        (base / "workflows" / "notes.txt").write_text("not a document", encoding="utf-8")
        docs = {Path(d["path"]).name: d for d in self.report(base, docs=True)["docs"]}
        self.assertEqual(["AGENTS.md", "CLAUDE.md", "ok.md", "wf3.md"], sorted(docs))
        self.assertEqual(("rules", []), (docs["AGENTS.md"]["type"], docs["AGENTS.md"]["codes"]))
        self.assertEqual(["RL4"], [c["code"] for c in docs["CLAUDE.md"]["codes"]])
        self.assertEqual("workflow", docs["wf3.md"]["type"])
        wf3 = docs["wf3.md"]["codes"][0]
        self.assertEqual(("WC3", "ERROR", "workflows/wf3.md"), (wf3["code"], wf3["level"], wf3["file"]))
        self.assertEqual([], docs["ok.md"]["codes"])

    def test_docs_key_absent_without_the_flag_and_totals_unchanged(self):
        """tương-đương: FR8.4 without `docs=True` the report has no `docs` key; with it the skill totals are the same (documents are not skills)."""
        base = self.plugin()
        (base / "AGENTS.md").write_text("- luật, vì lý do.\n" * 201, encoding="utf-8")
        plain, with_docs = self.report(base), self.report(base, docs=True)
        self.assertNotIn("docs", plain)
        self.assertEqual(plain["totals"], with_docs["totals"])
        self.assertEqual(["RL1"], [c["code"] for c in with_docs["docs"][0]["codes"]])

    def test_docs_asks_each_plugin_once_and_skips_skills_outside_a_plugin(self):
        """tương-đương: FR8.4 two skills of one plugin list its documents once; a skill folder with no plugin manifest above it adds none."""
        base = self.plugin()
        second = base / "skills" / "two"
        second.mkdir()
        shutil.copy(base / "skills" / "one" / "SKILL.md", second / "SKILL.md")
        (base / "AGENTS.md").write_text("- luật, vì lý do.\n", encoding="utf-8")
        self.assertEqual(1, len(self.report(base, docs=True)["docs"]))
        loose = self.tmp / "loose" / "skills" / "one"
        loose.mkdir(parents=True)
        shutil.copy(base / "skills" / "one" / "SKILL.md", loose / "SKILL.md")
        (self.tmp / "loose" / "AGENTS.md").write_text("- luật.\n", encoding="utf-8")
        self.assertEqual([], doctor.doctor_run([self.tmp / "loose" / "skills"], "portable", "portable", False, None, docs=True)["docs"])

    def test_docs_a_document_that_cannot_be_read_is_a_warning_not_a_crash(self):
        """bắt-lỗi (red at e92d4d2: no studio_doctypes): a rules file Windows calls a cloud placeholder gets one WARN INPUT and is not opened; the others are still checked."""
        base = self.plugin()
        (base / "AGENTS.md").write_text("- luật, vì lý do.\n", encoding="utf-8")
        (base / "GEMINI.md").write_text("Dùng `AGENTS.md`.\n", encoding="utf-8")
        real = fs.path_is_cloud
        with mock.patch.object(fs, "path_is_cloud", side_effect=lambda p, *a, **k: Path(p).name == "AGENTS.md" or real(p, *a, **k)):
            docs = {Path(d["path"]).name: d for d in self.report(base, docs=True)["docs"]}
        self.assertEqual([("INPUT", "WARN")], [(c["code"], c["level"]) for c in docs["AGENTS.md"]["codes"]])
        self.assertEqual([], docs["GEMINI.md"]["codes"])

    def test_docs_links_and_unlistable_folders(self):
        """độ-phủ: a rules name that is a link is listed (and refused as INPUT); a plugin folder that cannot be listed gives no documents."""
        base = self.plugin()
        (base / "AGENTS.md").write_text("- luật.\n", encoding="utf-8")
        with mock.patch.object(fs, "is_link", side_effect=lambda p: Path(p).name == "AGENTS.md"):
            docs = self.report(base, docs=True)["docs"]
        self.assertEqual("INPUT", docs[0]["codes"][0]["code"])
        self.assertEqual([], D.plugin_documents(self.tmp / "nowhere"))

    def test_cli_docs_flag_text_json_and_exit_code(self):
        """bắt-lỗi (red at e92d4d2: argparse `unrecognized arguments: --docs`): `doctor --docs` prints the bad documents in text, puts `docs` in --json, and does not change the exit code."""
        base = self.plugin()
        shutil.copy(FIX / "rl2-bad" / "AGENTS.md", base / "AGENTS.md")
        code, out, err = cli("doctor", "--roots", str(base / "skills"), "--docs")
        self.assertEqual((0, ""), (code, err), out)  # documents are reported, they do not decide the exit code
        self.assertIn("(rules): 2 errors, 0 warnings (RL2)", out)
        self.assertIn("docs: 1 files checked", out)
        code, out, err = cli("doctor", "--roots", str(base / "skills"), "--docs", "--json")
        self.assertEqual(0, code, err)
        data = json.loads(out)
        self.assertEqual("rules", data["docs"][0]["type"])
        self.assertEqual(["RL2", "RL2"], [c["code"] for c in data["docs"][0]["codes"]])
        code, out, err = cli("doctor", "--roots", str(base / "skills"), "--json")
        self.assertNotIn("docs", json.loads(out))

    def test_docs_of_the_studio_repo_are_clean(self):
        """tương-đương: SC7 `doctor --docs` on the Studio repo finds its three rules files and reports no finding."""
        code, out, err = cli("doctor", "--docs", "--json")
        self.assertIn(code, (0, 1), err)
        docs = json.loads(out)["docs"]
        self.assertEqual(["AGENTS.md", "CLAUDE.md", "GEMINI.md"], sorted(Path(d["path"]).name for d in docs))
        self.assertEqual([], [c for d in docs for c in d["codes"]])


if __name__ == "__main__":
    unittest.main()
