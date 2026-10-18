import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "transcripts"
spec = importlib.util.spec_from_file_location("activation", ROOT / "evals" / "tools" / "activation.py")
activation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activation)

SKILL = "data-quality-audit"


class ActivationCountTests(unittest.TestCase):
    def test_naive_grep_is_fooled_by_catalogue(self):
        """Why the counter exists: a raw text search finds the name in a session that never used the skill."""
        for name in ("claude_negative.jsonl", "codex_negative.jsonl"):
            self.assertIn(SKILL, (FIX / name).read_text(encoding="utf-8"), name)

    def test_claude_negative_with_name_in_catalogue_is_not_triggered(self):
        r = activation.count(FIX / "claude_negative.jsonl", SKILL, "claude-code")
        self.assertFalse(r["triggered"])
        self.assertEqual([], r["hits"])
        self.assertEqual("transcript", r["evidence"])

    def test_claude_positive_via_skill_tool(self):
        r = activation.count(FIX / "claude_positive.jsonl", SKILL, "claude-code")
        self.assertTrue(r["triggered"])
        self.assertEqual("Skill", r["hits"][0]["via"])
        self.assertEqual(1, len(r["scripts"]))

    def test_claude_positive_via_read_skill_md(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.jsonl"
            row = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "C:\\w\\skills\\data-quality-audit\\SKILL.md"}}]}}
            p.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertTrue(activation.count(p, SKILL, "claude-code")["triggered"])
            self.assertFalse(activation.count(p, "skill-creator-studio", "claude-code")["triggered"])

    def test_codex_positive_and_negative(self):
        pos = activation.count(FIX / "codex_positive.jsonl", SKILL, "codex")
        self.assertTrue(pos["triggered"])
        self.assertEqual(1, len(pos["hits"]))
        self.assertEqual(1, len(pos["scripts"]))
        neg = activation.count(FIX / "codex_negative.jsonl", SKILL, "codex")
        self.assertFalse(neg["triggered"])

    def test_codex_commands_in_a_cmds_array_count(self):
        """Codex JS can batch commands as `const cmds = ["...", ...]; cmds.map(cmd => ...)`; a read inside the array is a hit."""
        r = activation.count(FIX / "codex_real_cmds_array.jsonl", SKILL, "codex")
        self.assertTrue(r["triggered"])
        self.assertEqual([2], [h["line"] for h in r["hits"]])
        self.assertIn("SKILL.md", r["hits"][0]["match"])
        # a batch that reads other files only (second call) is not a hit
        self.assertEqual(1, len(r["hits"]))

    def test_codex_js_strings_without_read_or_skill_path_do_not_count(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.jsonl"
            js = 'const cmds = ["echo data-quality-audit/SKILL.md", "Get-Content a.txt"];'
            row = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": js}}
            p.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertFalse(activation.count(p, SKILL, "codex")["triggered"])

    def _codex_js(self, js):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.jsonl"
            row = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": js}}
            p.write_text(json.dumps(row) + "\n", encoding="utf-8")
            return activation.count(p, SKILL, "codex")

    def test_codex_patch_and_description_strings_are_not_commands(self):
        """Opus RF2: only `cmd:` values and strings of an array that is mapped into exec_command are commands."""
        patch = ('const patch = "*** Begin Patch\\n*** Update File: notes.md\\n+Run python .agents/skills/data-quality-audit/scripts/validate_csv.py --file a.csv\\n'
                 '+Get-Content data-quality-audit/SKILL.md\\n*** End Patch"; text(await tools.apply_patch(patch));')
        r = self._codex_js(patch)
        self.assertFalse(r["triggered"])
        self.assertEqual([], r["scripts"])
        r = self._codex_js('const note = "Read more in .agents/skills/data-quality-audit/SKILL.md"; text(note);')
        self.assertFalse(r["triggered"])
        # an array nobody maps into exec_command is not a command batch
        r = self._codex_js('const notes = ["Get-Content .agents/skills/data-quality-audit/SKILL.md"]; text(notes.join(","));')
        self.assertFalse(r["triggered"])

    def test_codex_cmd_key_and_mapped_array_still_count(self):
        r = self._codex_js('const r = await tools.exec_command({cmd:"Get-Content .agents/skills/data-quality-audit/SKILL.md", "workdir":"w"});')
        self.assertTrue(r["triggered"])
        r = self._codex_js('const cmds = ["Get-Content .agents/skills/data-quality-audit/SKILL.md"]; await Promise.all(cmds.map(cmd=>tools.exec_command({cmd})));')
        self.assertTrue(r["triggered"])
        r = self._codex_js('const r = await tools.exec_command({cmd:"python .agents/skills/data-quality-audit/scripts/validate_csv.py --file a.csv"});')
        self.assertEqual(1, len(r["scripts"]))

    def test_unknown_runtime_rejected(self):
        with self.assertRaises(ValueError):
            activation.count(FIX / "codex_positive.jsonl", SKILL, "gemini-cli")


def naive_count(path, skill):
    """The sloppy counter this tool replaces: any line naming the skill next to SKILL.md."""
    return any(skill in line and "SKILL.md" in line for line in Path(path).read_text(encoding="utf-8").splitlines())


class Transcripts:
    def make(self, rows):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "t.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return p


def use(name, inp, tid="t1"):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def result(tid, text):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": True}]}}


class ActivationPrecisionTests(Transcripts, unittest.TestCase):
    def claude(self, name, inp):
        return activation.count(self.make([use(name, inp)]), SKILL, "claude-code")

    def test_red_naive_counter_is_wrong_where_count_is_right(self):
        p = self.make([use("Bash", {"command": "find . -type f -path '*/data-quality-audit/SKILL.md'"})])
        self.assertTrue(naive_count(p, SKILL))
        self.assertFalse(activation.count(p, SKILL, "claude-code")["triggered"])
        self.assertTrue(naive_count(FIX / "codex_negative.jsonl", SKILL))
        self.assertFalse(activation.count(FIX / "codex_negative.jsonl", SKILL, "codex")["triggered"])

    def test_find_type_flag_is_not_a_read(self):
        self.assertFalse(self.claude("Bash", {"command": "find . -type f -path '*/data-quality-audit/SKILL.md'"})["triggered"])

    def test_description_field_is_not_scanned(self):
        r = self.claude("PowerShell", {"command": "Test-Path C:/w/skills/data-quality-audit/SKILL.md", "description": "read the skill"})
        self.assertFalse(r["triggered"])

    def test_verb_and_path_must_share_one_command(self):
        self.assertFalse(self.claude("PowerShell", {"command": "Get-ChildItem C:/w/skills/data-quality-audit/SKILL.md; echo type"})["triggered"])
        self.assertTrue(self.claude("PowerShell", {"command": "echo hi; Get-Content C:/w/skills/data-quality-audit/SKILL.md"})["triggered"])

    def test_skill_name_matches_whole_segment(self):
        self.assertFalse(self.claude("Skill", {"skill": "other:data-quality-audit-v2"})["triggered"])
        self.assertTrue(self.claude("Skill", {"skill": "agent-skill-studio:data-quality-audit"})["triggered"])
        self.assertTrue(self.claude("Skill", {"skill": "data-quality-audit"})["triggered"])
        self.assertFalse(self.claude("Bash", {"command": "cat C:/w/skills/data-quality-audit-v2/SKILL.md"})["triggered"])

    def test_path_used_as_filter_pattern_downstream_of_a_pipe_is_a_listing_not_a_read(self):
        self.assertFalse(self.claude("Bash", {"command": "rg --files | rg data-quality-audit/SKILL.md"})["triggered"])
        self.assertFalse(self.claude("PowerShell", {"command": "Get-ChildItem -Recurse -Name | Select-String data-quality-audit/SKILL.md"})["triggered"])
        self.assertTrue(self.claude("Bash", {"command": "cat skills/data-quality-audit/SKILL.md | head -20"})["triggered"])

    def test_other_ways_to_read_skill_md(self):
        self.assertTrue(self.claude("Bash", {"command": "rg -n description skills/data-quality-audit/SKILL.md"})["triggered"])
        self.assertTrue(self.claude("Grep", {"pattern": "name", "path": "C:/w/skills/data-quality-audit/SKILL.md"})["triggered"])
        self.assertTrue(self.claude("PowerShell", {"command": "[IO.File]::ReadAllText('C:/w/skills/data-quality-audit/SKILL.md')"})["triggered"])

    def test_scripts_count_only_successful_runs(self):
        run = "python -I C:/w/skills/data-quality-audit/scripts/validate_csv.py --file f.csv"
        ok = activation.count(self.make([use("Bash", {"command": run}), result("t1", "Exit code 1 {...}")]), SKILL, "claude-code")
        self.assertEqual(1, len(ok["scripts"]))
        denied = activation.count(self.make([use("Bash", {"command": run}), result("t1", "This Bash command contains multiple operations. The following parts require approval: ls")]), SKILL, "claude-code")
        self.assertEqual([], denied["scripts"])
        read = self.claude("PowerShell", {"command": "Get-Content C:/w/skills/data-quality-audit/scripts/validate_csv.py"})
        self.assertEqual([], read["scripts"])
        self.assertFalse(read["triggered"])

    def test_codex_real_exec_format(self):
        r = activation.count(FIX / "codex_real_exec.jsonl", SKILL, "codex")
        self.assertTrue(r["triggered"])
        self.assertEqual(1, len(r["hits"]))
        self.assertEqual(1, len(r["scripts"]), r["scripts"])
        self.assertEqual(2, r["hits"][0]["line"])
        self.assertEqual(4, r["scripts"][0]["line"])


class HashAndSummarizeTests(unittest.TestCase):
    def test_tree_hash_ignores_crlf_and_detects_change(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = Path(t) / "a", Path(t) / "b"
            for d in (a, b):
                (d / "scripts").mkdir(parents=True)
            (a / "SKILL.md").write_bytes(b"x\ny\n")
            (b / "SKILL.md").write_bytes(b"x\r\ny\r\n")
            (a / "scripts" / "s.py").write_bytes(b"1\n")
            (b / "scripts" / "s.py").write_bytes(b"1\n")
            self.assertEqual(activation.skill_tree_sha256(a), activation.skill_tree_sha256(b))
            (b / "scripts" / "s.py").write_bytes(b"2\n")
            self.assertNotEqual(activation.skill_tree_sha256(a), activation.skill_tree_sha256(b))

    def test_freeze_then_verify_detects_edits_and_version_drift(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            ev, main, cache = t / "ev", t / "main", t / "cache"
            (ev / "expected").mkdir(parents=True)
            (ev / "fixtures").mkdir()
            (ev / "cases.json").write_text("{}\n", encoding="utf-8")
            (ev / "rubric.md").write_text("r\n", encoding="utf-8")
            (ev / "expected" / "a.json").write_text("{}\n", encoding="utf-8")
            (ev / "fixtures" / "f.csv").write_text("a\n", encoding="utf-8")
            for d in (main, cache):
                d.mkdir()
                (d / "SKILL.md").write_text("s\n", encoding="utf-8")
            m = activation.freeze(ev, main, main, cache, "2026-10-17T00:00:00Z")
            self.assertEqual(["cases.json", "expected/a.json", "fixtures/f.csv", "rubric.md"], sorted(m["files"]))
            self.assertEqual([], activation.verify(m, ev, main, cache))
            (ev / "fixtures" / "f.csv").write_text("b\n", encoding="utf-8")
            (cache / "SKILL.md").write_text("old\n", encoding="utf-8")
            problems = activation.verify(m, ev, main, cache)
            self.assertIn("changed or missing: fixtures/f.csv", problems)
            self.assertIn("claude cache skill hash changed", problems)
            self.assertIn("repo and claude cache differ (invalid-version)", problems)

    def test_summarize_counts_only_ran_with_skill_logs(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            logs = [
                {"runtime": "codex", "with_skill": True, "kind": "typical", "status": "ran", "triggered": True},
                {"runtime": "codex", "with_skill": True, "kind": "edge", "status": "ran", "triggered": False},
                {"runtime": "codex", "with_skill": True, "kind": "near-miss", "status": "ran", "triggered": False},
                {"runtime": "codex", "with_skill": False, "kind": "typical", "status": "ran", "triggered": False},
                {"runtime": "codex", "with_skill": True, "kind": "typical", "status": "not_run", "triggered": True},
            ]
            for i, log in enumerate(logs):
                (d / ("%d.json" % i)).write_text(json.dumps(log), encoding="utf-8")
            self.assertEqual({"codex": {"pos": 2, "pos_trig": 1, "neg": 1, "neg_trig": 0}}, activation.summarize(d))


if __name__ == "__main__":
    unittest.main()
