import importlib.util
import json
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


if __name__ == "__main__":
    unittest.main()
