import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "transcripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "evals" / "tools" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


redact = load("redact")
activation = load("activation")


class RedactTests(unittest.TestCase):
    def filtered(self, name, runtime):
        return [json.loads(x) for x in redact.filter_lines((FIX / name).read_text(encoding="utf-8").splitlines(), runtime)]

    def test_codex_catalog_names_survive_but_descriptions_do_not(self):
        rows = self.filtered("codex_real_catalog.jsonl", "codex")
        catalog = [r for r in rows if r["payload"].get("skill_names")]
        self.assertEqual(1, len(catalog))
        names = catalog[0]["payload"]["skill_names"]
        for n in ("agent-skill-studio:data-quality-audit", "agent-skill-studio:skill-creator-studio", "skill-creator"):
            self.assertIn(n, names)
        text = json.dumps(rows, ensure_ascii=False)
        self.assertNotIn("Audits CSV", text)
        self.assertIn("agent-skill-studio:data-quality-audit", text)

    def test_codex_keeps_the_final_answer_and_the_tail_of_the_prompt(self):
        rows = self.filtered("codex_real_catalog.jsonl", "codex")
        text = json.dumps(rows, ensure_ascii=False)
        self.assertIn("anthropic-skills:skill-creator", text)  # assistant output_text
        self.assertIn('Write \\"none\\" if there are none', text)  # prompt tail

    def test_claude_skill_listing_keeps_names_not_content(self):
        row = {"type": "attachment", "attachment": {"type": "skill_listing", "skillCount": 2, "names": ["a:x", "b"], "content": "- a:x: very long description"}}
        out = [json.loads(x) for x in redact.filter_lines([json.dumps(row)], "claude-code")]
        self.assertEqual(["a:x", "b"], out[0]["attachment"]["names"])
        self.assertNotIn("content", out[0]["attachment"])

    def test_counts_are_identical_before_and_after_filtering(self):
        cases = [("codex_real_exec.jsonl", "codex"), ("codex_positive.jsonl", "codex"), ("claude_positive.jsonl", "claude-code"), ("claude_negative.jsonl", "claude-code")]
        for name, runtime in cases:
            with tempfile.TemporaryDirectory() as t:
                out = Path(t) / "f.jsonl"
                out.write_text("\n".join(redact.filter_lines((FIX / name).read_text(encoding="utf-8").splitlines(), runtime)) + "\n", encoding="utf-8")
                a = activation.count(FIX / name, "data-quality-audit", runtime)
                b = activation.count(out, "data-quality-audit", runtime)
                self.assertEqual((a["triggered"], len(a["hits"]), len(a["scripts"])), (b["triggered"], len(b["hits"]), len(b["scripts"])), name)

    def test_sanitize_removes_email_and_user_path(self):
        s = redact.sanitize('mail me@example.com path C:\\\\Users\\\\SomeUser\\\\x and C:/Users/SomeUser/y')
        self.assertNotIn("@", s)
        self.assertNotIn("SomeUser", s)

    def test_sanitize_is_generic_not_tied_to_one_user_name(self):
        for raw in ("C:\\\\Users\\\\OtherPerson\\\\x", "C:\\Users\\OtherPerson\\x", "C:/Users/OtherPerson/x", "c:\\\\users\\\\OtherPerson"):
            self.assertNotIn("OtherPerson", redact.sanitize(raw), raw)

    def test_sanitize_removes_a_path_cut_in_the_middle(self):
        for raw in ("C:\\\\Users\\\\SomeUser...[cut]", "[cut]...C:/Users/SomeUser...[cut]", '"C:\\\\Users\\\\Some...[cut]"'):
            s = redact.sanitize(raw)
            self.assertNotIn("SomeUser", s, raw)
            self.assertNotIn("Some", s.replace("[cut]", ""), raw)

    def test_sanitize_removes_the_runtime_user_name_from_the_environment(self):
        import os
        old = os.environ.get("USERNAME")
        os.environ["USERNAME"] = "RuntimeName"
        try:
            self.assertNotIn("runtimename", redact.sanitize("owner RuntimeName ok").lower())
        finally:
            if old is None:
                del os.environ["USERNAME"]
            else:
                os.environ["USERNAME"] = old

    def test_path_pattern_has_no_literal_user_name(self):
        """The Users-folder pattern must be generic: its only literal words are C, Users and the separators."""
        self.assertEqual("C:[\\\\/]+Users[\\\\/]+[^\\\\/\"\\s]+", redact.PATH_RE.pattern)


# Output of the ORIGINAL df875ce functions (generated once; the regexes were then rewritten to run in linear time).
SANITIZE_OLD = [('mail a@b.co now', 'mail <email> now'),
 ('see https://x.io/u/me@mail.example.org/p', 'see https://x.io/u/<email>/p'),
 ('a.b@c.d', '<email>'),
 ('a..b@c.d', '<email>'),
 ('x@y', 'x@y'),
 ('x@y.z.w', '<email>'),
 ('@a.b', '@a.b'),
 ('a@@b.c', 'a@@b.c'),
 ('a@b.c@d.e', '<email>@d.e'),
 ('me@sub-dom.example.com.', '<email>.'),
 ('-a@b.c', '<email>'),
 ('a+tag@b.c', '<email>'),
 ('foo.bar@baz', 'foo.bar@baz'),
 ('a@b-.c', '<email>'),
 ('q@r.s,t@u.v', '<email>,<email>'),
 ('e@x.io\nf@y.io', '<email>\n<email>'),
 ('', ''),
 ('a@', 'a@'),
 ('@', '@'),
 ('u@ex.com/path', '<email>/path'),
 ('ünï@cödé.io', '<email>'),
 ('x=a@b.c;y=d@e.f', 'x=<email>;y=<email>'),
 ('a@b.c.', '<email>.'),
 ('(a@b.c)', '(<email>)'),
 ('<a@b.c>', '<<email>>'),
 ('a b@c.d e', 'a <email> e'),
 ('a@b..c', 'a@b..c'),
 ('a@.b', 'a@.b'),
 ('http://u:p@h.example/x', 'http://u:<email>/x'),
 ('m@n.o-p@q.r', '<email>@q.r'),
 ('a@b.c+x@y.z', '<email><email>'),
 ('a@b.c..d@e.f', '<email><email>'),
 ('.@b.c.@b.c.', '<email><email>.'),
 ('a@b.c.-x@y.zz', '<email>@y.zz'),
 ('a@b.c.', '<email>.'),
 ('p@q.r+s@t.u+v@w.x', '<email><email><email>')]


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


class RedactLinearTimeTests(unittest.TestCase):
    CASES = [
        ("word run, no @", '"a" * n', "m.sanitize(t)"),
        ("dotted run, no @", '"." * n', "m.sanitize(t)"),
        ("a.a.a. run", '"a." * (n // 2)', "m.sanitize(t)"),
        ("dotted run then @", '"a." * (n // 2) + "@"', "m.sanitize(t)"),
        ("repeated a@", '"a@" * (n // 2)', "m.sanitize(t)"),
        ("email-like, no domain dot", '"a@a" + ".a" * (n // 2)', "m.sanitize(t)"),
        ("many emails", '"a@a.a " * (n // 6)', "m.sanitize(t)"),
        ("blanks", '" " * n', "m.sanitize(t)"),
        ("repeated C:/", '"C:/" * (n // 3)', "m.sanitize(t)"),
        ("one long catalogue-like line", '"- " + "a" * n', "m.CATALOG_NAME_RE.findall(t)"),
    ]

    def test_bat_loi_redact_is_linear_on_adversarial_input(self):
        """bắt-lỗi (RQ-185): the public filter must finish 100 000 hostile characters in linear time (ratio < 20, < 5 s)."""
        for label, gen, call in self.CASES:
            with self.subTest(label):
                assert_linear(self, ROOT / "evals" / "tools" / "redact.py", label, gen, call)

    def test_tuong_duong_sanitize_matches_the_pre_fix_output(self):
        """tương-đương: output of the original df875ce `sanitize` on 36 edge cases (email inside a URL, adjacent dots, an address right after another one, '@' runs ...)."""
        for text, expected in SANITIZE_OLD:
            with self.subTest(text=text):
                self.assertEqual(expected, redact.sanitize(text))


if __name__ == "__main__":
    unittest.main()
