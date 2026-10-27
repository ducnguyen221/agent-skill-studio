import importlib.util
import json
import subprocess
import sys
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


# Output of the ORIGINAL df875ce functions (generated once; the regexes were then rewritten to run in linear time).
SEGMENTS_OLD = [('a ; b', [('a', False), ('b', False)]),
 ('a;;b', [('a', False), ('b', False)]),
 ('a && b', [('a', False), ('b', False)]),
 ('a&&b', [('a', False), ('b', False)]),
 ('a||b', [('a', False), ('b', False)]),
 ('a || b', [('a', False), ('b', False)]),
 ('a | b', [('a', False), ('b', True)]),
 ('a |\n b', [('a', False), ('b', True)]),
 ('a\n\nb', [('a', False), ('b', False)]),
 ('   ', []),
 ('', []),
 ('a ;\n b', [('a', False), ('b', False)]),
 ('a|\n|b', [('a', False), ('b', True)]),
 ('cat x | grep y && echo z', [('cat x', False), ('grep y', True), ('echo z', False)]),
 ('a\n| b', [('a', False), ('b', True)]),
 ('  lead and trail  ', [('lead and trail', False)]),
 ('a ; | b', [('a', False), ('b', True)]),
 ('x ||| y', [('x', False), ('y', True)]),
 ('a & b', [('a & b', False)]),
 ('a\r\nb', [('a', False), ('b', False)]),
 ('a |\n\n  b', [('a', False), ('b', True)]),
 ('|a', [('a', True)]),
 ('a|', [('a', False)]),
 (';', []),
 ('a ;; ; b', [('a', False), ('b', False)]),
 ('a | b | c', [('a', False), ('b', True), ('c', True)]),
 ('a |\t\n c ; d', [('a', False), ('c', True), ('d', False)]),
 ('one\ntwo | three\nfour', [('one', False), ('two', False), ('three', True), ('four', False)]),
 ('a &&\n| b', [('a', False), ('b', True)]),
 ('a ||\n b', [('a', False), ('b', False)])]

SCRIPT_RE_OLD = [('data-quality-audit', 'python data-quality-audit/scripts/validate_csv.py', True),
 ('data-quality-audit', 'py -3 C:/s/data-quality-audit\\scripts\\validate_csv.py', True),
 ('data-quality-audit', 'python3.exe x && data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'cat python.txt data-quality-audit/scripts/validate_csv.py', True),
 ('data-quality-audit', 'pythonx data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'xpython data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'py data-quality-audit/scripts/other.py', False),
 ('data-quality-audit', 'python a | data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'python\ndata-quality-audit/scripts/validate_csv.py', True),
 ('data-quality-audit', 'PYTHON data-quality-audit/scripts/validate_csv.py', True),
 ('data-quality-audit', 'my-data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'py', False),
 ('data-quality-audit', 'python data-quality-audit/scripts/validate_csv.pyc', False),
 ('data-quality-audit', 'echo py; python x/data-quality-audit/scripts/validate_csv.py', True),
 ('data-quality-audit', 'python-3 data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'python3 python data-quality-audit/scripts/validate_csv.py', True),
 ('data-quality-audit', 'python3.exedata-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'py data-quality-audit/scripts/validate_csv.py', True),
 ('data-quality-audit', 'python . & data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'run.py data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'python -m x ; data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'python "data-quality-audit/scripts/validate_csv.py"', True),
 ('data-quality-audit', 'python3  --version py data-quality-audit\\scripts\\validate_csv.py', True),
 ('data-quality-audit', 'x.python data-quality-audit/scripts/validate_csv.py', False),
 ('data-quality-audit', 'python;py data-quality-audit/scripts/validate_csv.py', True),
 ('data-quality-audit', 'py &py data-quality-audit/scripts/validate_csv.py', True),
 ('skill-creator-studio', 'python skill-creator-studio/scripts/studio.py', True),
 ('skill-creator-studio', 'py -3 C:/s/skill-creator-studio\\scripts\\studio.py', True),
 ('skill-creator-studio', 'python3.exe x && skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'cat python.txt skill-creator-studio/scripts/studio.py', True),
 ('skill-creator-studio', 'pythonx skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'xpython skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'py skill-creator-studio/scripts/other.py', False),
 ('skill-creator-studio', 'python a | skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'python\nskill-creator-studio/scripts/studio.py', True),
 ('skill-creator-studio', 'PYTHON skill-creator-studio/scripts/studio.py', True),
 ('skill-creator-studio', 'my-skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'py', False),
 ('skill-creator-studio', 'python skill-creator-studio/scripts/studio.pyc', False),
 ('skill-creator-studio', 'echo py; python x/skill-creator-studio/scripts/studio.py', True),
 ('skill-creator-studio', 'python-3 skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'python3 python skill-creator-studio/scripts/studio.py', True),
 ('skill-creator-studio', 'python3.exeskill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'py skill-creator-studio/scripts/studio.py', True),
 ('skill-creator-studio', 'python . & skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'run.py skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'python -m x ; skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'python "skill-creator-studio/scripts/studio.py"', True),
 ('skill-creator-studio', 'python3  --version py skill-creator-studio\\scripts\\studio.py', True),
 ('skill-creator-studio', 'x.python skill-creator-studio/scripts/studio.py', False),
 ('skill-creator-studio', 'python;py skill-creator-studio/scripts/studio.py', True),
 ('skill-creator-studio', 'py &py skill-creator-studio/scripts/studio.py', True)]

JS_OLD = [('cmd: "cat a/SKILL.md"', ['cat a/SKILL.md'], []),
 ('{ cmd: "x", "y": 1 }', ['x'], []),
 ('const cmds = ["a", "b"]; cmds.map(c => run(c))', ['a', 'b'], [(14, 23)]),
 ('const x = ["a"]; for (const c of x) run(c)', ['a'], [(11, 15)]),
 ('const x = ["a"]; unused', [], []),
 ('const x = [ "a]", "b" ]; x.forEach(f)', ['a]', 'b'], [(11, 23)]),
 ('x = ["a"', [], []),
 ('unclosed "abc', [], []),
 ('cmd:\n  "z"', ['z'], []),
 ('cmd": "q"', [], []),
 ('a = [ [ "n" ], "m" ]; a.map(f)', ['n', 'm'], [(5, 20)]),
 ('"a\\"b"', [], []),
 ('"a\\\n"b"', [], []),
 ('x.map(f); x = ["a"]', [], []),
 ('b = ["1"]; a = [ "2" ]; a.map(f); b.map(f)', ['1', '2'], [(5, 9), (16, 22)]),
 ('$v = ["s"]; $v.map(f)', ['s'], [(6, 10)]),
 ('a = ["p", "q" ; a.map(f)', ['p', 'q'], [(5, 24)]),
 ('a = ["x"]; a . forEach(g); of a', ['x'], [(5, 9)]),
 ('const k = ["a\\"]", "b"]; for (c of k) r(c)', ['a"]', 'b'], [(11, 23)]),
 ('cmd: "one", cmd: "two" "three"', ['one', 'two'], []),
 ('q = ["a"]; r = ["b"]; for (const c of r) f(c)', ['b'], [(16, 20)]),
 ('cmd:"a"cmd:"b"', ['a', 'b'], []),
 ('', [], []),
 ('"', [], []),
 ('""', [], []),
 ('cmd: ""', [''], []),
 ('xcmd: "no"', [], []),
 ('m = ["a", m = ["b"]]; m.map(f)', ['a', 'b'], [(5, 20), (15, 19)]),
 ('u = ["a"]; u2.map(f)', [], []),
 ('w = ["a"]; of wx', [], [])]


CHILD = r'''
import importlib.util, json, sys, tempfile, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("mod", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def count_cmd(mod, command):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.jsonl"
        row = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "1", "name": "Bash", "input": {"command": command}}]}}
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        return mod.count(p, "data-quality-audit", "claude-code")


def best(gen, call, n):
    t = eval(gen, {"n": n})
    times = []
    for _ in range(2):
        t0 = time.perf_counter()
        eval(call, {"m": m, "t": t, "count_cmd": count_cmd})
        times.append(time.perf_counter() - t0)
    return min(times)


print(best(sys.argv[2], sys.argv[3], 10000), best(sys.argv[2], sys.argv[3], 100000))
'''

LINEAR_RATIO = 20   # t(100k) / t(10k) of a linear function is ~10
HARD_CEILING = 5.0  # seconds at 100 000 characters
CHILD_TIMEOUT = 25  # a quadratic function never finishes 100 000 characters: killed here and reported as a failure


def assert_linear(test, module_file, label, gen, call):
    try:
        out = subprocess.run([sys.executable, "-X", "utf8", "-c", CHILD, str(module_file), gen, call], capture_output=True, text=True, timeout=CHILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        test.fail("%s: not finished within %d s (100 000 chars) - super-linear" % (label, CHILD_TIMEOUT))
    test.assertEqual(0, out.returncode, "%s: %s" % (label, out.stderr[-400:]))
    t10, t100 = (float(x) for x in out.stdout.split())
    test.assertLess(t100, HARD_CEILING, "%s: %.2f s at 100k" % (label, t100))
    test.assertLess(t100 / max(t10, 0.005), LINEAR_RATIO, "%s: t(100k)/t(10k) = %.1f (10k %.3f s, 100k %.3f s)" % (label, t100 / max(t10, 0.005), t10, t100))


class ActivationLinearTimeTests(unittest.TestCase):
    SKILL_PATH = '" data-quality-audit/scripts/validate_csv.py"'
    CASES = [
        ("segments: blanks", '" " * n', "m._segments(t)"),
        ("segments: word then blanks", '"a" + " " * n', "m._segments(t)"),
        ("segments: blanks then word", '" " * n + "a"', "m._segments(t)"),
        ("segments: ' ; '", '" ; " * (n // 3)', "m._segments(t)"),
        ("segments: &&", '"&&" * (n // 2)', "m._segments(t)"),
        ("segments: ||", '"||" * (n // 2)', "m._segments(t)"),
        ("segments: '| '", '"| " * (n // 2)', "m._segments(t)"),
        ("segments: newlines", '"\\n" * n', "m._segments(t)"),
        ("script_re: many py", '"py " * (n // 3)', "m._script_re('data-quality-audit').search(t)"),
        ("script_re: many python.exe", '"python.exe " * (n // 11)', "m._script_re('skill-creator-studio').search(t)"),
        ("script_re: many py then path", '"py " * (n // 3) + " data-quality-audit/scripts/validate_csv.py"', "m._script_re('data-quality-audit').search(t)"),
        ("script_re: operators", '"&" * n', "m._script_re('data-quality-audit').search(t)"),
        ("js: unclosed quote", '"\\"" + "a" * n', "m._codex_commands(t)"),
        ("js: quotes", '"\\"" * n', "m._codex_commands(t)"),
        ("js: escaped quotes", '"\\"\\\\" * (n // 2)', "m._codex_commands(t)"),
        ("js: cmd: keys", '"cmd:\\"" * (n // 5)', "m._codex_commands(t)"),
        ("js: unclosed array assignments", '"a=[" * (n // 3) + "a.map(x)"', "m._codex_commands(t)"),
        ("js: array assignments with open quotes", '"a=[\\"" * (n // 4) + "a.map(x)"', "m._js_command_spans(t)"),
        ("count: blanks in a Bash command", '"cat " + " " * n', "count_cmd(m, t)"),
        ("count: py repeated", '"py " * (n // 3)', "count_cmd(m, t)"),
    ]

    def test_bat_loi_activation_is_linear_on_adversarial_input(self):
        """bắt-lỗi (RQ-185): segment split, script regex and the Codex JS scan must take linear time on 100 000 hostile characters."""
        for label, gen, call in self.CASES:
            with self.subTest(label):
                assert_linear(self, ROOT / "evals" / "tools" / "activation.py", label, gen, call)

    def test_tuong_duong_segments_match_the_pre_fix_output(self):
        """tương-đương: _segments of the original df875ce on 30 edge cases (&& adjacent, ||, ;;, newline, blanks both sides, empty)."""
        for text, expected in SEGMENTS_OLD:
            with self.subTest(text=text):
                self.assertEqual(expected, [(p.strip(), piped) for p, piped in activation._segments(text) if p.strip()])

    def test_tuong_duong_script_re_matches_the_pre_fix_output(self):
        """tương-đương: _script_re(...).search of the original on 52 command lines for both skills."""
        for skill, text, expected in SCRIPT_RE_OLD:
            with self.subTest(skill=skill, text=text):
                self.assertEqual(expected, bool(activation._script_re(skill).search(text)))

    def test_tuong_duong_codex_js_matches_the_pre_fix_output(self):
        """tương-đương: command strings and array spans the original finds in 30 JS snippets (nested arrays, escapes, unclosed, $ names)."""
        for text, commands, spans in JS_OLD:
            with self.subTest(text=text):
                self.assertEqual(commands, activation._codex_commands(text))
                self.assertEqual(spans, activation._js_command_spans(text))


if __name__ == "__main__":
    unittest.main()
