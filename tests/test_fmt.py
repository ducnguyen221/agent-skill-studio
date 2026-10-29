"""SPR-33 TK10: `studio.py fmt --check|--fix` (SPEC 9.12, 9.13, FR18, SC11). `fmt_text` is pure: it never reads or writes a file."""
import contextlib
import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402

studio = _engine.engine
studio_const = _engine.const  # constants live in studio_const (SPR-02 TK4a)
studio_fs = _engine.fs  # file-system helpers live in studio_fs
studio_fmt = _engine.fmt  # SPR-02 TK4c

SKILL = "---\nname: demo-skill\ndescription: Checks a toy example. Use when testing fmt.\n---\n\n# Demo\n\nBody text here.\n"


def run(*argv, root=None):
    """Run `studio.py fmt ...` in-process; returns (exit code, stdout, stderr). `root` stands in for the repo root."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        if root is not None:
            stack.enter_context(mock.patch.object(studio_fs, "repo_root", lambda start: Path(root)))
        try:
            code = studio.main(["fmt", *argv])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def codes(findings):
    return [f["code"] for f in findings]


def body_of(text: str) -> str:
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:])
    return text


class FmtTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_fmt_check_detects_crlf_bom_trailing(self):
        for label, text in (("crlf", SKILL.replace("\n", "\r\n")),
                            ("bom", "\ufeff" + SKILL),
                            ("trailing", SKILL.replace("Body text here.", "Body text here.   ")),
                            ("no-final-newline", SKILL.rstrip("\n")),
                            ("two-final-newlines", SKILL + "\n")):
            with self.subTest(label):
                _, found = studio_fmt.fmt_text(text, "skill")
                self.assertEqual(set(codes(found)), {"FT1"}, found)
                path = write(self.tmp / label / "SKILL.md", text)
                before = path.read_bytes()
                code, out, _ = run("--check", str(path))
                self.assertEqual(code, 1, out)
                self.assertIn("FT1", out)
                self.assertEqual(path.read_bytes(), before, "--check must not write")

    def test_fmt_fix_idempotent(self):
        text = "\ufeff---\r\ndescription: Checks. Use when testing.\r\nname: demo\r\nmetadata:\r\n  version: 1\r\n---\r\n\r\n# Demo  \r\n\r\nBody.   \r\n\r\n\r\n"
        path = write(self.tmp / "SKILL.md", text)
        self.assertEqual(run("--fix", str(path))[0], 0)
        first = path.read_bytes()
        self.assertNotEqual(first, text.encode("utf-8"))
        self.assertEqual(run("--fix", str(path))[0], 0)
        self.assertEqual(path.read_bytes(), first, "second --fix must change no byte")
        self.assertEqual(run("--check", str(path))[0], 0)
        again, found = studio_fmt.fmt_text(first.decode("utf-8"), "skill")
        self.assertEqual((again, found), (first.decode("utf-8"), []))

    def test_fmt_fix_never_changes_body_text(self):
        fence = "`" * 3
        text = ("---\nmetadata:\n  version: 2\ndescription: Checks. Use when testing.\nname: demo\n---\n\n"
                "# Demo   \r\n\r\n" + fence + "bash\r\npython studio.py new x  \r\n" + fence + "\r\n\r\n| a | b |\r\n|---|---|\r\n| 1 | 2 |   \r\n\r\nSee C:/Users/x/y.md and ../a/b.md.\r\n\r\n\r\n")
        new, _ = studio_fmt.fmt_text(text, "skill")
        self.assertEqual(body_of(new).split(), body_of(text).split())
        path = write(self.tmp / "SKILL.md", text)
        self.assertEqual(run("--fix", str(path))[0], 0)
        self.assertEqual(body_of(path.read_bytes().decode("utf-8")).split(), body_of(text).split())
        self.assertIn("C:/Users/x/y.md", path.read_text(encoding="utf-8"))

    def test_fmt_orders_frontmatter_keys(self):
        text = ("---\nmetadata:\n  author: x\ndescription: Checks. Use when testing.\nx-extra: 1\nname: demo\n"
                "allowed-tools: Read\nlicense: MIT\ncompatibility: any\nzeta: 2\n---\n\n# Demo\n")
        new, found = studio_fmt.fmt_text(text, "skill")
        self.assertIn("FT2", codes(found))
        keys = [m.group(1) for m in re.finditer(r"(?m)^([A-Za-z][\w-]*):", new.split("---")[1])]
        self.assertEqual(keys, ["name", "description", "license", "compatibility", "allowed-tools", "metadata", "x-extra", "zeta"])
        self.assertIn("metadata:\n  author: \"x\"\n", new)  # the indented block travelled with its key
        self.assertEqual(studio_fmt.fmt_text(new, "skill")[1], [])
        _, found = studio_fmt.fmt_text(text, "studio-doc")
        self.assertNotIn("FT2", codes(found), "FT2 is for skills only")

    def test_fmt_quotes_metadata_values(self):
        text = "---\nname: demo\ndescription: Checks. Use when testing.\nmetadata:\n  version: 1\n  stable: true\n  note: 'it''s'\n  quoted: \"already\"\n  word: plain\n---\n\n# Demo\n"
        new, found = studio_fmt.fmt_text(text, "skill")
        self.assertEqual(codes(found).count("FT3"), 4, found)
        self.assertIn('  version: "1"\n', new)
        self.assertIn('  stable: "true"\n', new)
        self.assertIn('  note: "it\'s"\n', new)
        self.assertIn('  quoted: "already"\n', new)
        self.assertIn('  word: "plain"\n', new)
        parsed, problems, _ = studio_fs.parse_frontmatter(new, Path("SKILL.md"))
        self.assertEqual(problems, [])
        self.assertEqual(parsed["metadata"], {"version": "1", "stable": "true", "note": "it's", "quoted": "already", "word": "plain"})
        self.assertNotIn("FT3", codes(studio_fmt.fmt_text(text, "studio-doc")[1]), "FT3 is for skills only")

    def test_fmt_doc_missing_min_frontmatter_ft4(self):
        base = self.tmp / "repo"
        doc = write(base / "standards" / "X.md", "# Title\n\nBody.\n")
        self.assertEqual(studio_fmt.classify_md(doc, base), "studio-doc")
        _, found = studio_fmt.fmt_text("# Title\n\nBody.\n", "studio-doc")
        self.assertEqual(codes(found), ["FT4"])
        self.assertIn("title", found[0]["message"])
        before = doc.read_bytes()
        code, out, _ = run("--fix", str(doc), root=base)
        self.assertEqual(code, 1, out)
        self.assertIn("FT4", out)
        self.assertEqual(doc.read_bytes(), before, "--fix never adds frontmatter")
        _, found = studio_fmt.fmt_text("---\ntitle: \"T\"\nstatus: active\n---\n\n# T\n", "studio-doc")
        self.assertEqual(codes(found), ["FT4"])
        self.assertIn("updated", found[0]["message"])
        self.assertEqual(studio_fmt.fmt_text("---\ntitle: \"T\"\nstatus: active\nupdated: 2026-10-23\nkind: entry\n---\n\n# T\n", "studio-doc")[1], [])

    def test_fmt_pr1_process_shape(self):
        base = self.tmp / "repo"
        bad = write(base / "references" / "NEW_WORKFLOW.md", "# New\n\n## Contents\n\nSome text only.\n")
        self.assertEqual(studio_fmt.classify_md(bad, base), "process")
        found = studio_fmt.check_process_shape("# New\n\nSome text only.\n")
        self.assertTrue(found and set(codes(found)) == {"PR1"})
        self.assertTrue(all(f["level"] == "WARN" for f in found))
        code, out, _ = run("--check", str(bad), root=base)
        self.assertEqual(code, 0, "PR1 is a warning: the exit code does not change")
        self.assertIn("PR1", out)
        en = ("# Name\n\n> **Conclusion:** x.\n\n## When to use / not\n\n- a\n\n## Steps\n\n### Step 1 — Do\n\n- Command: c\n- Expect: e\n- Stop if: s\n\n## Gotchas\n\n- g\n\n## Done when\n\n- d\n")
        vi = ("# Tên\n\n> **Kết luận:** x.\n\n## Khi nào dùng / Không dùng\n\n- a\n\n## Bước\n\n### Bước 1 — Làm\n\n- Lệnh: c\n- Kỳ vọng: e\n- Dừng nếu: s\n\n## Gotchas\n\n- g\n\n## Kiểm xong\n\n- d\n")
        self.assertEqual(studio_fmt.check_process_shape(en), [])
        self.assertEqual(studio_fmt.check_process_shape(vi), [])
        self.assertEqual(codes(studio_fmt.check_process_shape(en.replace("- Stop if: s\n", ""))), ["PR1"])

    def test_fmt_never_adds_contents(self):
        text = "---\ntitle: \"T\"\nstatus: active\nupdated: 2026-10-23\n---\n\n# T\n" + "\n".join("## Section %d  \n\ntext\n" % i for i in range(1, 40)) + "\n\n"
        self.assertGreater(len(text.splitlines()), 100)
        new, _ = studio_fmt.fmt_text(text, "studio-doc")
        headings = lambda t: [ln.rstrip() for ln in t.splitlines() if ln.startswith("#")]
        self.assertEqual(headings(new), headings(text))
        self.assertEqual(sum(1 for ln in new.splitlines() if ln.startswith("## ")), sum(1 for ln in text.splitlines() if ln.startswith("## ")))
        self.assertNotRegex(new, r"(?im)^##\s+(table of contents|contents|mục lục)")


def make_dir_link(test, link: Path, target: Path) -> None:
    """A directory symlink, or a junction on Windows without the symlink privilege; skips the test when neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if link.exists():
            return
    test.skipTest("cannot create a symlink or junction here")


def tree_snapshot(base: Path):
    return sorted((p.relative_to(base).as_posix(), p.read_bytes()) for p in base.rglob("*") if p.is_file())


class FmtMoreTests(unittest.TestCase):
    """Negative and edge cases around the nine named tests."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_fmt_clean_file_zero_changes(self):
        path = write(self.tmp / "SKILL.md", SKILL)
        before = path.stat().st_mtime_ns
        for mode in ("--check", "--fix"):
            code, out, _ = run(mode, str(path))
            self.assertEqual(code, 0, out)
        self.assertEqual(path.stat().st_mtime_ns, before, "a clean file is not rewritten")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["SKILL.md"], "no backup, no temp file")
        self.assertEqual(studio_fmt.fmt_text(SKILL, "skill"), (SKILL, []))
        self.assertEqual(studio_fmt.fmt_text("", "other"), ("", []))

    def test_fmt_body_with_code_block_and_paths_keeps_every_word(self):
        fence = "`" * 3
        body = "# T\n\n" + fence + "powershell\nGet-Content C:\\Users\\x\\a.txt   \n" + fence + "\n\nSee [a](../b/c.md) and `x  y`.\n"
        new, _ = studio_fmt.fmt_text(SKILL.split("# Demo")[0] + body, "skill")
        self.assertEqual(new.split(), (SKILL.split("# Demo")[0] + body).split())
        self.assertIn("C:\\Users\\x\\a.txt\n", new)

    def test_fmt_frontmatter_crlf_and_bom_fixed(self):
        text = "\ufeff---\r\nname: demo\r\ndescription: Checks. Use when testing.\r\nmetadata:\r\n  version: 1\r\n---\r\n\r\n# T\r\n"
        new, found = studio_fmt.fmt_text(text, "skill")
        self.assertEqual(set(codes(found)), {"FT1", "FT3"})
        self.assertEqual(new, "---\nname: demo\ndescription: Checks. Use when testing.\nmetadata:\n  version: \"1\"\n---\n\n# T\n")

    def test_fmt_check_exit_1_for_each_code(self):
        fence = "`" * 3
        cases = {
            "FT1": SKILL.replace("Demo", "Demo  "),
            "FT2": "---\ndescription: Checks. Use when testing.\nname: demo\n---\n\n# T\n",
            "FT3": SKILL.replace("---\n\n#", "metadata:\n  version: 1\n---\n\n#"),
            "FT5": "\n\n" + SKILL,
        }
        for code_name, text in cases.items():
            with self.subTest(code_name):
                path = write(self.tmp / code_name / "SKILL.md", text)
                code, out, _ = run("--check", str(path))
                self.assertEqual(code, 1, out)
                self.assertIn(code_name, out)
                self.assertEqual(run("--fix", str(path))[0], 0, "fixable: --fix clears it")
        base = self.tmp / "repo"
        doc = write(base / "examples" / "d.md", "# T\n")
        self.assertEqual(run("--check", str(doc), root=base)[0], 1)
        late = write(base / "examples" / "late.md", "# T\n\n---\ntitle: \"T\"\nstatus: active\nupdated: 2026-10-23\n---\n\nbody\n")
        code, out, _ = run("--fix", str(late), root=base)
        self.assertEqual(code, 1, "frontmatter that starts late is reported, not moved")
        self.assertIn("FT5", out)
        quiet = "# T\n\n" + fence + "\n---\nname: x\n---\n" + fence + "\n"
        self.assertEqual([f["code"] for f in studio_fmt.fmt_text(quiet, "skill")[1]], [])

    def test_fmt_fix_skips_symlink_and_junction(self):
        real = self.tmp / "real"
        write(real / "SKILL.md", SKILL.replace("\n", "\r\n"))
        outer = self.tmp / "outer"
        outer.mkdir()
        link = outer / "linked"
        make_dir_link(self, link, real)
        code, out, _ = run("--fix", str(outer))
        self.assertEqual(code, 0, out)
        if os.name == "nt":
            self.assertIn("skipped (link)", out)
        else:
            # POSIX: a directory symlink is reported as `skipped (link)` like a junction (SPR-01 TK3, FR3.2) and still never followed
            self.assertIn("skipped (link)", out)
        self.assertEqual((real / "SKILL.md").read_bytes(), SKILL.replace("\n", "\r\n").encode("utf-8"), "nothing written through a link")
        code, out, _ = run("--fix", str(link / "SKILL.md"), root=self.tmp)  # a file reached through a link below the repo root
        self.assertEqual(code, 1, "named directly and not checked: exit 1 ('exit 0' means every file was checked)")
        self.assertIn("skipped (link)", out)
        self.assertEqual((real / "SKILL.md").read_bytes(), SKILL.replace("\n", "\r\n").encode("utf-8"))

    def test_fmt_given_link_is_skipped(self):
        real = self.tmp / "real"
        write(real / "a.md", "# A  \n")
        link = self.tmp / "lnk"
        make_dir_link(self, link, real)
        code, out, _ = run("--fix", str(link))
        self.assertEqual(code, 1)
        self.assertIn("skipped (link)", out)
        self.assertEqual((real / "a.md").read_bytes(), b"# A  \n")

    def test_fmt_missing_path_exit_2(self):
        code, _, err = run("--check", str(self.tmp / "nope.md"))
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err)
        good = write(self.tmp / "SKILL.md", SKILL.replace("\n", "\r\n"))
        code, _, _ = run("--fix", str(good), str(self.tmp / "nope.md"))
        self.assertEqual(code, 2)
        self.assertEqual(good.read_bytes(), SKILL.replace("\n", "\r\n").encode("utf-8"), "nothing is written when a path is missing")
        self.assertEqual(run()[0], 2, "no path and no --all")
        self.assertEqual(run("--check", "--fix", str(good))[0], 2, "--check and --fix exclude each other")

    def test_fmt_all_does_not_touch_runs_or_pruned_dirs(self):
        base = self.tmp / "repo"
        for rel in ("evals/s/runs/r1/out.md", "evals/s/cases.md", ".tmp/x.md", ".worktrees/w/y.md", "dist/z.md", "node_modules/m/n.md", ".git/g.md", "docs/ok.md"):
            write(base / rel, "# T  \n")
        before = tree_snapshot(base)
        code, out, _ = run("--all", root=base)
        self.assertEqual(code, 1, out)  # the two reachable files have trailing whitespace
        self.assertEqual(tree_snapshot(base), before, "--all only reports")
        listed = [str(Path(f["path"]).relative_to(base).as_posix()) for f in __import__("json").loads(run("--all", "--json", root=base)[1])["files"]]
        self.assertEqual(listed, ["docs/ok.md", "evals/s/cases.md"])
        code, _, err = run("--all", "--fix", root=base)
        self.assertEqual(code, 2)
        self.assertIn("--all only reports", err)
        self.assertEqual(tree_snapshot(base), before)

    def _listed(self, base, *extra):
        out = run("--all", "--json", *extra, root=base)[1]
        return sorted(str(Path(f["path"]).relative_to(base).as_posix()) for f in __import__("json").loads(out)["files"])

    def test_fmt_all_skips_fixtures(self):
        base = self.tmp / "repo"
        for rel in ("tests/fixtures/x.md", "tests/fixtures/deep/more/z.md", "evals/s/fixtures/y.md", "evals/s/cases.md", "tests/notes.md", "docs/ok.md"):
            write(base / rel, "# T  \n")
        self.assertEqual(self._listed(base), ["docs/ok.md", "evals/s/cases.md", "tests/notes.md"])
        code, out, _ = run("--all", root=base)
        self.assertNotIn("fixtures", out, "a skipped fixture is not even reported")

    def test_fmt_all_fixtures_rule_is_only_for_tests_and_evals_skill(self):
        base = self.tmp / "repo"
        for rel in ("skills/s/fixtures/a.md", "examples/e/fixtures/b.md", "fixtures/c.md", "tests/sub/fixtures/d.md", "evals/fixtures/e.md",
                    "evals/s/x/fixtures/f.md", "docs/tests/fixtures/g.md"):
            write(base / rel, "# T  \n")
        self.assertEqual(self._listed(base), sorted(["skills/s/fixtures/a.md", "examples/e/fixtures/b.md", "fixtures/c.md", "tests/sub/fixtures/d.md",
                                                     "evals/fixtures/e.md", "evals/s/x/fixtures/f.md", "docs/tests/fixtures/g.md"]),
                         "'fixtures' elsewhere (skills/, examples/, a deeper tests/ or evals/ path) is documentation like any other")

    def test_fmt_explicit_folder_still_reads_fixtures(self):
        base = self.tmp / "repo"
        for rel in ("tests/fixtures/x.md", "tests/notes.md", "evals/s/fixtures/y.md", "docs/ok.md"):
            write(base / rel, "# T  \n")
        got = lambda *a: sorted(str(Path(f["path"]).relative_to(base).as_posix()) for f in __import__("json").loads(run("--check", "--json", *a, root=base)[1])["files"])
        self.assertEqual(got(str(base / "tests")), ["tests/fixtures/x.md", "tests/notes.md"], "no --all: a named folder is read whole")
        self.assertEqual(got(str(base / "tests" / "fixtures")), ["tests/fixtures/x.md"])
        self.assertEqual(got(str(base / "evals")), ["evals/s/fixtures/y.md"])
        self.assertEqual(self._listed(base), ["docs/ok.md", "tests/notes.md"], "--all still skips them")
        self.assertEqual(sorted(p.relative_to(base).as_posix() for p in studio_fmt.iter_md([base / "tests"], False, None)),
                         ["tests/fixtures/x.md", "tests/notes.md"], "no repo root: nothing is skipped")
        self.assertEqual(sorted(p.relative_to(base).as_posix() for p in studio_fmt.iter_md([base / "tests"], False, base)),
                         ["tests/fixtures/x.md", "tests/notes.md"], "a root without all_repo does not skip")
        self.assertEqual(sorted(p.relative_to(base).as_posix() for p in studio_fmt.iter_md([base / "tests"], True, base)),
                         ["docs/ok.md", "tests/notes.md"], "all_repo skips fixtures")

    def test_fmt_all_scans_examples(self):
        base = self.tmp / "repo"
        for rel in ("examples/csv/SKILL.md", "examples/csv/references/r.md", "examples/README.md"):
            write(base / rel, "# T  \n")
        self.assertEqual(self._listed(base), sorted(["examples/README.md", "examples/csv/SKILL.md", "examples/csv/references/r.md"]))
        self.assertEqual(run("--all", root=base)[0], 1, "examples/ is checked like normal docs")

    def test_fmt_skips_secret_names_cloud_zone_and_big_files(self):
        base = self.tmp / "repo"
        write(base / ".env.md", "# S  \n")
        write(base / "auth.json.md", "# ok  \n")
        write(base / "OneDrive - X" / "a.md", "# C  \n")
        write(base / ".secret" / "s.md", "# C  \n")
        write(base / "big.md", "# B  \n" + "x" * (studio_const.DOCTOR_MAX_FILE_BYTES + 1))
        (base / "bad.md").write_bytes(b"\xff\xfe\x00bad")
        before = tree_snapshot(base)
        code, out, _ = run("--fix", str(base))
        self.assertEqual(code, 1, "bad.md is not UTF-8: it was not checked")
        after = dict(tree_snapshot(base))
        for name in (".env.md", "OneDrive - X/a.md", ".secret/s.md", "big.md", "bad.md"):
            self.assertEqual(after[name], dict(before)[name], name)
        self.assertEqual(after["auth.json.md"], b"# ok\n")
        for reason in ("secret-name", "cloud-or-secret-zone", "limit", "not-utf8"):
            self.assertIn("skipped (%s)" % reason, out)

    def test_fmt_json_report_schema(self):
        path = write(self.tmp / "SKILL.md", SKILL.replace("Demo", "Demo "))
        code, out, _ = run("--check", "--json", str(path))
        report = __import__("json").loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(set(report), {"schema", "mode", "files", "skipped", "totals"})
        self.assertEqual((report["schema"], report["mode"]), (1, "check"))
        self.assertEqual(set(report["files"][0]), {"path", "kind", "changed", "backup", "findings"})
        self.assertEqual(set(report["files"][0]["findings"][0]), {"level", "code", "line", "message", "fixable"})
        self.assertEqual(report["totals"], {"files": 1, "changed": 0, "errors": 1, "warnings": 0, "blocked": 0})

    def test_fmt_refuses_to_write_if_words_would_change(self):
        path = write(self.tmp / "SKILL.md", SKILL.replace("Demo", "Demo "))
        before = path.read_bytes()
        with mock.patch.object(studio_fmt, "fmt_text", lambda text, kind, profile="portable": (text.replace("Body", "Other").rstrip() + "\n", [])):
            code, out, _ = run("--fix", str(path))
        self.assertEqual(code, 1, "a refused write is not a clean run")
        self.assertIn("skipped (would-change-text)", out)
        self.assertEqual(path.read_bytes(), before)

    def test_fmt_write_failure_exit_2(self):
        path = write(self.tmp / "SKILL.md", SKILL.replace("Demo", "Demo "))
        with mock.patch.object(studio_fmt, "_write_fixed", side_effect=OSError(13, "denied")):
            code, _, err = run("--fix", str(path))
        self.assertEqual(code, 2)
        self.assertIn("cannot write", err)

    def test_fmt_backup_name_never_overwrites(self):
        path = write(self.tmp / "SKILL.md", "# T  \n")
        fixed = {"stamp": None}
        real_now = studio_fmt.datetime

        class Fixed(real_now):
            @classmethod
            def now(cls, tz=None):
                return real_now(2026, 10, 23, 1, 2, 3)

        with mock.patch.object(studio_fmt, "datetime", Fixed):
            studio_fmt._write_fixed(path, b"# T\n", True)
            path.write_bytes(b"# T  \n")
            studio_fmt._write_fixed(path, b"# T\n", True)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["SKILL.md", "SKILL.md.bak-20261023T010203", "SKILL.md.bak-20261023T010203-1"])

    def test_fmt_text_rejects_unknown_profile_and_accepts_opcos(self):
        with self.assertRaises(ValueError):
            studio_fmt.fmt_text(SKILL, "skill", "nope")
        self.assertEqual(studio_fmt.fmt_text(SKILL, "skill", "opcos"), (SKILL, []))
        self.assertEqual(run("--check", "--profile", "opcos", str(write(self.tmp / "SKILL.md", SKILL)))[0], 0)

    def test_classify_md(self):
        base = self.tmp
        self.assertEqual(studio_fmt.classify_md(base / "x" / "SKILL.vi.md", base), "skill")
        self.assertEqual(studio_fmt.classify_md(base / "standards" / "A.md", base), "studio-doc")
        self.assertEqual(studio_fmt.classify_md(base / "examples" / "A.md", base), "studio-doc")
        self.assertEqual(studio_fmt.classify_md(base / "examples" / "exemplar" / "A.md", base), "other")
        self.assertEqual(studio_fmt.classify_md(base / "content" / "A.md", base), "other", "content/ moved to examples/ (SPR-03 TK2)")
        self.assertEqual(studio_fmt.classify_md(base / "templates" / "README.md", base), "studio-doc")
        self.assertEqual(studio_fmt.classify_md(base / "templates" / "starter-project" / "README.md", base), "other")
        self.assertEqual(studio_fmt.classify_md(base / "references" / "PROCESS_TEMPLATE.md", base), "process")
        self.assertEqual(studio_fmt.classify_md(base / "references" / "AUDIT_WORKFLOW.md", base), "process")
        self.assertEqual(studio_fmt.classify_md(base / "standards" / "A.md", None), "other")
        self.assertEqual(studio_fmt.classify_md(base / "standards" / "A.md", self.tmp / "elsewhere"), "other")

    def test_shipped_process_template_matches_pr1(self):
        path = ROOT / "skills" / "skill-creator-studio" / "assets" / "skill-template-full" / "references" / "PROCESS_TEMPLATE.md"
        self.assertEqual(studio_fmt.check_process_shape(path.read_text(encoding="utf-8")), [])

    def test_fmt_misplaced_blank_lines_before_frontmatter(self):
        new, found = studio_fmt.fmt_text("\n\n" + SKILL, "skill")
        self.assertEqual(codes(found), ["FT5"])
        self.assertEqual(new, SKILL)
        self.assertEqual(studio_fmt.fmt_text("\n\n# plain\n", "other"), ("\n\n# plain\n", []), "blank lines are only removed ahead of a frontmatter")


# ---- round 3 (Opus re-review of round 2) --------------------------------------------------------------------------------------------

class FmtRound3Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    # (3) a metadata value ends where the line ends, not at the first Unicode space
    def test_fmt_keeps_a_unicode_space_at_the_end_of_a_metadata_value(self):
        self.assertEqual(studio_fmt._quote_meta("  v: abc\u00a0"), ('  v: "abc\u00a0"', "fixed"))
        text = "---\nname: demo\ndescription: Checks. Use when testing.\nmetadata:\n  v: abc\u00a0\n---\n\n# T\n"
        new, found = studio_fmt.fmt_text(text, "skill")
        self.assertEqual(codes(found), ["FT3"])
        self.assertEqual(new, text.replace("v: abc\u00a0", 'v: "abc\u00a0"'))
        self.assertEqual(studio_fmt.fmt_text(new, "skill")[1], [])

    # (4) a file over the size limit was not checked: exit 1, whichever way it was reached
    def test_fmt_file_over_the_size_limit_in_a_folder_is_exit_1(self):
        write(self.tmp / "ok.md", "# Ok\n")
        write(self.tmp / "big.md", "# B  \n" + "x" * (studio_const.DOCTOR_MAX_FILE_BYTES + 1))  # trailing spaces: an FT1 nobody saw
        for mode in ("--check", "--fix"):
            with self.subTest(mode):
                code, out, _ = run(mode, str(self.tmp))
                self.assertEqual(code, 1, out)
                self.assertIn("skipped (limit)", out)
                self.assertIn("1 of them block the exit", out)
                self.assertNotIn("not checked", out, "a summary that says 'not checked' next to exit 0 contradicts itself")
        report = __import__("json").loads(run("--check", "--json", str(self.tmp))[1])
        self.assertEqual((report["totals"]["blocked"], report["totals"]["errors"]), (1, 0))

    def test_fmt_summary_names_what_blocks_the_exit(self):
        write(self.tmp / "ok.md", "# Ok\n")
        code, out, _ = run("--check", str(self.tmp))
        self.assertEqual(code, 0, out)
        self.assertIn("0 skipped, 0 of them block the exit", out)

    # (5) the opening '---' is in column 0, like the closing one
    def test_fmt_indented_opening_line_is_reported_not_rewritten(self):
        for opening in (" ---", "\t---", "  ---"):
            with self.subTest(repr(opening)):
                text = SKILL.replace("---\nname", opening + "\nname", 1)
                self.assertIsNone(studio_fmt._fm_bounds(text.split("\n")))
                new, found = studio_fmt.fmt_text(text, "skill")
                self.assertEqual(codes(found), ["FT5"])
                self.assertFalse(found[0]["fixable"])
                self.assertEqual(found[0]["line"], 1)
                self.assertEqual(new, text, "fmt does not guess: the bytes stay as they are")
                path = write(self.tmp / "SKILL.md", text)
                self.assertEqual(run("--check", str(path))[0], 1)
                self.assertEqual(run("--fix", str(path))[0], 1)
                self.assertEqual(path.read_bytes(), text.encode("utf-8"))

    def test_fmt_indented_dashes_that_are_no_frontmatter_stay_quiet(self):
        text = " ---\nJust a rule line and a paragraph.\n---\n\n# T\n"
        self.assertEqual(studio_fmt.fmt_text(text, "skill"), (text, []))
        self.assertEqual(studio_fmt.fmt_text(" ---\nname: x\n---\n", "other"), (" ---\nname: x\n---\n", []))

    def test_fmt_indented_opening_after_blank_lines_is_reported_too(self):
        text = "\n\n" + SKILL.replace("---\nname", " ---\nname", 1)
        new, found = studio_fmt.fmt_text(text, "skill")
        self.assertEqual(codes(found), ["FT5"])
        self.assertEqual(new, text)

    # (6) a failure of the temp file also removes the backup that was just made
    def test_fmt_temp_file_failure_removes_the_backup(self):
        path = write(self.tmp / "SKILL.md", SKILL.replace("\n", "\r\n"))
        before = path.read_bytes()
        real_new = studio_fs._create_new_fd

        def deny_temp(name, dir_fd):  # SPR-05 round 1: the temp file is made by create-new under the pin, not by tempfile.mkstemp; the backup is made the same way and must work
            if os.path.basename(name).endswith(studio_const.REPLACE_TMP_SUFFIX):
                raise PermissionError(13, "denied")
            return real_new(name, dir_fd)

        with mock.patch.object(studio_fs, "_create_new_fd", deny_temp):
            code, _, err = run("--fix", str(path))
        self.assertEqual(code, 2, err)
        self.assertIn("cannot write", err)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["SKILL.md"], "no backup left behind")

    def test_fmt_failed_copy_removes_the_half_made_backup(self):
        path = write(self.tmp / "SKILL.md", SKILL.replace("\n", "\r\n"))

        def half_copy(source, target, *args, **kwargs):
            target.write(b"half")  # the backup is now created exclusively and copied with copyfileobj (SPR-01 TK3)
            target.flush()
            raise OSError(28, "no space")

        with mock.patch.object(shutil, "copyfileobj", half_copy):
            code, _, err = run("--fix", str(path))
        self.assertEqual(code, 2, err)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["SKILL.md"])



def backups_of(folder: Path):
    return sorted(p for p in folder.iterdir() if ".bak-" in p.name)


DIRTY = SKILL.replace("Demo", "Demo ")  # one fixable finding: trailing space


class FmtBackupTests(unittest.TestCase):
    """Round 5: no git is asked. `fmt --fix` copies every file it really changes to <file>.bak-<ISO>; --no-backup skips the copy."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_fmt_fix_backs_up_every_changed_file_by_default(self):
        plain, marked = self.tmp / "plain", self.tmp / "marked"
        (marked / ".git" / "info").mkdir(parents=True)  # a folder called .git (no git is installed or asked for here)
        for folder in (plain, marked):
            with self.subTest(folder.name):
                path = write(folder / "SKILL.md", DIRTY)
                code, out, err = run("--fix", str(path))
                self.assertEqual(code, 0, out + err)
                (backup,) = backups_of(folder)
                self.assertEqual(backup.read_bytes(), DIRTY.encode("utf-8"), "the backup holds the original bytes")
                self.assertRegex(backup.name, r"^SKILL\.md\.bak-\d{8}T\d{6}")
                self.assertEqual(path.read_bytes(), SKILL.encode("utf-8"))
                self.assertIn("1 backups", out)

    def test_fmt_fix_no_backup_writes_none(self):
        path = write(self.tmp / "SKILL.md", DIRTY)
        code, out, err = run("--fix", "--no-backup", str(path))
        self.assertEqual(code, 0, out + err)
        self.assertEqual(path.read_bytes(), SKILL.encode("utf-8"))
        self.assertEqual(backups_of(self.tmp), [])
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["SKILL.md"], "no backup, no temp file")
        self.assertIn("0 backups", out)

    def test_fmt_fix_unchanged_file_makes_no_backup(self):
        path = write(self.tmp / "SKILL.md", DIRTY)
        self.assertEqual(run("--fix", str(path))[0], 0)
        self.assertEqual(len(backups_of(self.tmp)), 1)
        fixed, stamp = path.read_bytes(), path.stat().st_mtime_ns
        code, out, err = run("--fix", str(path))
        self.assertEqual(code, 0, out + err)
        self.assertEqual(path.read_bytes(), fixed, "second run: 0 bytes changed")
        self.assertEqual(path.stat().st_mtime_ns, stamp, "second run: not rewritten")
        self.assertEqual(len(backups_of(self.tmp)), 1, "second run: 0 new .bak")
        self.assertIn("0 backups", out)
        clean = write(self.tmp / "clean" / "SKILL.md", SKILL)
        self.assertEqual(run("--fix", str(clean))[0], 0)
        self.assertEqual(backups_of(clean.parent), [])

    def test_no_backup_needs_fix_exit_2(self):
        path = write(self.tmp / "SKILL.md", DIRTY)
        for argv in (("--no-backup",), ("--check", "--no-backup")):
            with self.subTest(argv):
                code, out, err = run(*argv, str(path))
                self.assertEqual(code, 2, out)
                self.assertIn("needs --fix", err)
                self.assertEqual(path.read_bytes(), DIRTY.encode("utf-8"))
        self.assertEqual(backups_of(self.tmp), [])

    def test_fmt_json_reports_backup_path(self):
        import json
        changed = write(self.tmp / "a" / "SKILL.md", DIRTY)
        clean = write(self.tmp / "b" / "SKILL.md", SKILL)
        report = json.loads(run("--fix", "--json", str(changed), str(clean))[1])
        by_name = {Path(f["path"]).parent.name: f for f in report["files"]}
        (backup,) = backups_of(changed.parent)
        self.assertEqual(Path(by_name["a"]["backup"]), backup)
        self.assertTrue(by_name["a"]["changed"])
        self.assertIsNone(by_name["b"]["backup"], "a file that did not change has no backup")
        for argv in (("--check",), ("--fix", "--no-backup")):
            with self.subTest(argv):
                again = write(self.tmp / "c" / "SKILL.md", DIRTY)
                report = json.loads(run(*argv, "--json", str(again))[1])
                self.assertIsNone(report["files"][0]["backup"])

    def test_studio_runs_no_subprocess(self):
        import ast
        paths = [*_engine.ENGINE_FILES, *sorted((ROOT / "evals" / "tools").glob("*.py"))]
        self.assertGreaterEqual(len(paths), 4, "the engine and the eval tools")
        banned_os = ("system", "popen", "startfile")
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            found = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found += [a.name for a in node.names if a.name.split(".")[0] == "subprocess"]
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").split(".")[0] == "subprocess":
                        found.append(node.module)
                    if node.module == "os":
                        found += ["os." + a.name for a in node.names if a.name in banned_os or a.name.startswith(("exec", "spawn", "posix_spawn"))]
                elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
                    if node.attr in banned_os or node.attr.startswith(("exec", "spawn", "posix_spawn")):
                        found.append("os." + node.attr)
                elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("__import__", "import_module"):
                    found += [a.value for a in node.args[:1] if isinstance(a, ast.Constant) and str(a.value).split(".")[0] in ("subprocess", "pty")]
            self.assertEqual(found, [], "%s starts a program" % path.relative_to(ROOT))


class FmtSafeWriteTests(unittest.TestCase):
    """The temp file of --fix: a new name each time (never a name an attacker can predict), cleaned up on every failure."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_fmt_does_not_write_through_a_planted_link(self):
        outside = write(self.tmp / "outside" / "canary.txt", "canary\n")
        folder = self.tmp / "d"
        tried = 0
        for label, plant in (("hard link", os.link), ("symlink", os.symlink)):
            path = write(folder / "SKILL.md", SKILL.replace("\n", "\r\n"))
            planted = folder / ".SKILL.md.fmt-tmp"  # the name the first version of fmt used
            try:
                plant(outside, planted)
            except (OSError, NotImplementedError):
                continue
            tried += 1
            with self.subTest(label):
                code, out, _ = run("--fix", str(path))
                self.assertEqual(code, 0, out)
                self.assertEqual(outside.read_bytes(), b"canary\n", "nothing is written through a link planted at a guessable name")
                self.assertEqual(path.read_bytes(), SKILL.encode("utf-8"))
                self.assertTrue(os.path.lexists(planted), "what was already there is not ours to delete")
                os.unlink(planted)
        if not tried:
            self.skipTest("cannot create a hard link or symlink here")

    def test_fmt_temp_name_is_not_fixed(self):
        path = write(self.tmp / "SKILL.md", SKILL.replace("\n", "\r\n"))
        seen = []
        real = os.replace
        with mock.patch.object(os, "replace", side_effect=lambda src, dst, **kw: (seen.append(Path(src).name), real(src, dst, **kw))[1]):
            self.assertEqual(run("--fix", str(path))[0], 0)
            write(path, SKILL.replace("\n", "\r\n"))
            self.assertEqual(run("--fix", str(path))[0], 0)
        self.assertEqual(len(seen), 2)
        self.assertNotIn(".SKILL.md.fmt-tmp", seen)
        self.assertNotEqual(seen[0], seen[1], "a fresh random name each time")

    def test_fmt_failed_replace_leaves_nothing_behind(self):
        path = write(self.tmp / "SKILL.md", SKILL.replace("\n", "\r\n"))
        before = path.read_bytes()
        with mock.patch.object(os, "replace", side_effect=OSError(5, "access denied")):
            code, _, err = run("--fix", str(path))
        self.assertEqual(code, 2, err)
        self.assertIn("cannot write", err)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["SKILL.md"], "no temp file and no backup of a write that did not happen")

    def test_fmt_read_only_file_is_refused_cleanly(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root ignores the read-only bit")
        path = write(self.tmp / "SKILL.md", SKILL.replace("Demo", "Demo  "))
        os.chmod(path, stat.S_IREAD)
        self.addCleanup(os.chmod, path, stat.S_IREAD | stat.S_IWRITE)
        before = path.read_bytes()
        with mock.patch.object(shutil, "copy2", side_effect=AssertionError("a read-only file must be refused before a backup is made")):
            code, _, err = run("--fix", str(path))
        self.assertEqual(code, 2, err)
        self.assertIn("cannot write", err)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["SKILL.md"], "no .fmt-tmp, no tmp*, no backup left behind")

    def test_fmt_copies_the_mode_to_the_new_file(self):
        path = write(self.tmp / "SKILL.md", SKILL.replace("\n", "\r\n"))
        real, calls = studio_fs.replace_with, []

        def spy(target, fill, anchor=None, mode=None):  # SPR-05 round 1: the mode travels to the new file as `mode` (set on the temp file before the rename), not by shutil.copymode
            calls.append((Path(target), mode))
            return real(target, fill, anchor=anchor, mode=mode)

        expected = stat.S_IMODE(os.lstat(path).st_mode)
        with mock.patch.object(studio_fs, "replace_with", spy):
            self.assertEqual(run("--fix", str(path))[0], 0)
        self.assertEqual(calls, [(path, expected)])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_fmt_keeps_the_posix_mode(self):
        path = write(self.tmp / "run.md", "# T  \n")
        os.chmod(path, 0o750)
        self.assertEqual(run("--fix", str(path))[0], 0)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o750)


class FmtPathTests(unittest.TestCase):
    """Paths handed over directly, outside any repo root: links in the middle, cloud and secret folders, the resolved spelling."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_fmt_direct_path_through_a_link_is_refused(self):
        fake = self.tmp / "OneDrive - Fake"  # a cloud folder reached through a harmless-looking name
        write(fake / "c.md", "# C  \n")
        write(fake / "sub" / "d.md", "# D  \n")
        work = self.tmp / "work"
        work.mkdir()
        make_dir_link(self, work / "j", fake)
        before = tree_snapshot(fake)
        for target in (work / "j" / "c.md", work / "j" / "sub", work / "j"):
            for root in (None, self.tmp / "elsewhere", work):
                with self.subTest(target=target.relative_to(work).as_posix(), root=None if root is None else root.name):
                    code, out, _ = run("--fix", str(target), root=root)
                    self.assertEqual(code, 1, out)
                    self.assertIn("skipped (link)", out)
                    self.assertEqual(tree_snapshot(fake), before, "nothing written through the link")

    def test_fmt_link_in_the_middle_of_a_direct_path(self):
        real = self.tmp / "real"
        write(real / "b" / "x.md", "# X  \n")
        (self.tmp / "a").mkdir()
        make_dir_link(self, self.tmp / "a" / "j2", real)
        before = tree_snapshot(real)
        for root in (None, self.tmp / "other"):
            code, out, _ = run("--fix", str(self.tmp / "a" / "j2" / "b" / "x.md"), root=root)
            self.assertEqual(code, 1, out)
            self.assertIn("skipped (link)", out)
            self.assertEqual(tree_snapshot(real), before)

    def test_fmt_direct_cloud_or_secret_path_is_refused(self):
        cloud = write(self.tmp / "OneDrive - X" / "a.md", "# C  \n")
        secret = write(self.tmp / ".secret" / "s.md", "# S  \n")
        real = os.path.realpath
        zones = ("onedrive", "." + "secret")

        def resolve(value, *args, **kwargs):  # RK15: a path that names a cloud or secret zone is refused on its spelling, before it is resolved
            if any(zone in os.fspath(value).casefold() for zone in zones):
                raise AssertionError("resolved %s" % value)
            return real(value, *args, **kwargs)

        for path, reason in ((cloud, "cloud"), (secret, "secret-zone")):
            with self.subTest(reason), mock.patch.object(os.path, "realpath", resolve):
                before = path.read_bytes()
                code, out, _ = run("--fix", str(path))
                self.assertEqual(code, 1, out)
                self.assertIn("skipped (%s)" % reason, out)
                self.assertEqual(path.read_bytes(), before)

    @unittest.skipUnless(os.name == "nt", "8.3 short names are a Windows thing")
    def test_fmt_resolved_spelling_is_checked_for_cloud(self):
        import ctypes
        folder = self.tmp / "OneDrive - Fake"
        target = write(folder / "c.md", "# C  \n")
        buffer = ctypes.create_unicode_buffer(600)
        if not ctypes.windll.kernel32.GetShortPathNameW(str(folder), buffer, 600) or "onedrive" in buffer.value.casefold():
            self.skipTest("this volume gives no 8.3 short name to the folder")
        before = target.read_bytes()
        code, out, _ = run("--fix", str(Path(buffer.value) / "c.md"))
        self.assertEqual(code, 1, out)
        self.assertIn("skipped (cloud)", out)
        self.assertEqual(target.read_bytes(), before)


class FmtExitCodeTests(unittest.TestCase):
    """Exit 0 means every file asked for was checked and is in house style (SC11)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_fmt_named_file_that_is_not_checked_is_exit_1(self):
        big = write(self.tmp / "big.md", "# B\n" + "x" * (studio_const.DOCTOR_MAX_FILE_BYTES + 1))
        secret = write(self.tmp / ".env.md", "# S\n")
        other = write(self.tmp / "notes.txt", "x\n")
        bad = self.tmp / "bad.md"
        bad.write_bytes(b"\xff\xfe\x00bad")
        for path, reason in ((big, "limit"), (secret, "secret-name"), (other, "not-markdown"), (bad, "not-utf8")):
            for mode in ("--check", "--fix"):
                with self.subTest(reason, mode=mode):
                    code, out, _ = run(mode, str(path))
                    self.assertEqual(code, 1, out)
                    self.assertIn("skipped (%s)" % reason, out)

    def test_fmt_not_utf8_file_found_in_a_folder_is_exit_1(self):
        write(self.tmp / "ok.md", "# Ok\n")
        (self.tmp / "bad.md").write_bytes(b"\xff\xfe\x00bad")
        code, out, _ = run("--check", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn("skipped (not-utf8)", out)

    def test_fmt_skips_found_while_walking_a_folder_stay_exit_0_but_are_listed(self):
        write(self.tmp / "ok.md", "# Ok\n")
        write(self.tmp / ".env.md", "# S\n")
        write(self.tmp / "OneDrive - X" / "a.md", "# C\n")
        real = write(self.tmp / "elsewhere" / "r.md", "# R\n")
        make_dir_link(self, self.tmp / "lnk", real.parent)
        code, out, _ = run("--check", str(self.tmp))
        self.assertEqual(code, 0, out)
        # FR3.2 (SPR-01): a directory symlink is reported as skipped (link) on every OS, never passed over silently
        reasons = ("secret-name", "cloud-or-secret-zone", "link")
        for reason in reasons:
            self.assertIn("skipped (%s)" % reason, out)
        report = __import__("json").loads(run("--check", "--json", str(self.tmp))[1])
        self.assertEqual(report["totals"]["blocked"], 0)
        self.assertGreaterEqual(len(report["skipped"]), len(reasons))
        if os.name != "nt":
            # the real thing it is safe for: the link is not followed, so r.md is read once, by its own path, never as lnk/r.md
            self.assertEqual(report["totals"]["files"], 2, out)
            self.assertNotIn("lnk/", out)  # reported as a skipped link, never entered
            self.assertFalse(any("lnk/" in str(item) for item in report["files"]), report["files"])

    def test_fmt_json_counts_the_files_that_block_the_exit(self):
        bad = self.tmp / "bad.md"
        bad.write_bytes(b"\xff\xfe\x00bad")
        code, out, _ = run("--check", "--json", str(bad))
        report = __import__("json").loads(out)
        self.assertEqual((code, report["totals"]["errors"], report["totals"]["blocked"]), (1, 0, 1))


class FmtStuckValueTests(unittest.TestCase):
    """FT3 for a metadata value fmt cannot quote on its own: reported, never rewritten, --check and --fix both exit 1."""

    HEAD = "---\nname: demo\ndescription: Checks. Use when testing.\nmetadata:\n"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_fmt_ft3_reports_a_value_it_cannot_quote(self):
        for value in ("x # c", ">-", "|", "'only", "[a, b]", "a: b", "{k: v}", "x\t# c"):
            with self.subTest(value):
                text = self.HEAD + "  note: " + value + "\n---\n\n# T\n"
                new, found = studio_fmt.fmt_text(text, "skill")
                self.assertEqual(new, text, "the line is left alone")
                self.assertEqual(codes(found), ["FT3"], found)
                self.assertFalse(found[0]["fixable"])
                self.assertEqual(found[0]["line"], 5)
                path = write(self.tmp / ("v%d" % abs(hash(value))) / "SKILL.md", text)
                for mode in ("--check", "--fix"):
                    code, out, _ = run(mode, str(path))
                    self.assertEqual(code, 1, out)
                    self.assertIn("FT3", out)
                    self.assertNotIn("fixable with --fix", out)
                self.assertEqual(path.read_bytes(), text.encode("utf-8"))

    def test_fmt_ft3_fixes_what_it_can_and_still_reports_the_rest(self):
        text = self.HEAD + "  version: 1\n  note: x # c\n---\n\n# T\n"
        new, found = studio_fmt.fmt_text(text, "skill")
        self.assertIn('  version: "1"\n', new)
        self.assertIn("  note: x # c\n", new)
        self.assertEqual([(f["code"], f["fixable"]) for f in found], [("FT3", True), ("FT3", False)])
        self.assertEqual([(f["code"], f["fixable"]) for f in studio_fmt.fmt_text(new, "skill")[1]], [("FT3", False)])
        path = write(self.tmp / "SKILL.md", text)
        self.assertEqual(run("--fix", str(path))[0], 1)
        first = path.read_bytes()
        self.assertEqual(run("--fix", str(path))[0], 1)
        self.assertEqual(path.read_bytes(), first, "idempotent")


class FmtFrontmatterEdgeTests(unittest.TestCase):
    def test_fmt_title_need_not_equal_the_heading(self):
        text = '---\ntitle: "Authoring Standard"\nstatus: active\nupdated: 2026-10-23\n---\n\n# Skill Authoring Standard\n'
        self.assertEqual(studio_fmt.fmt_text(text, "studio-doc"), (text, []), "FT4 asks for the keys, not for a title that equals the H1")

    def test_fmt_closing_line_is_only_a_dashes_line_in_column_zero(self):
        text = "---\ndescription: >\n  Checks.\n  ---\n  Use when testing.\nname: demo\n---\n\n# T\n"
        new, found = studio_fmt.fmt_text(text, "skill")
        self.assertEqual(codes(found), ["FT2"], "an indented '---' inside a block scalar does not close the frontmatter")
        self.assertEqual(new, "---\nname: demo\ndescription: >\n  Checks.\n  ---\n  Use when testing.\n---\n\n# T\n")
        self.assertEqual(studio_fmt.fmt_text(new, "skill")[1], [])
        self.assertEqual(studio_fmt._fm_bounds(text.split("\n")), (0, 6))

    def test_fmt_comment_in_column_zero_travels_with_the_key_before_it(self):
        text = "---\ndescription: Checks. Use when testing.\n# about the name\nname: demo\n---\n\n# T\n"
        new, found = studio_fmt.fmt_text(text, "skill")
        self.assertEqual(codes(found), ["FT2"])
        self.assertEqual(new, "---\nname: demo\ndescription: Checks. Use when testing.\n# about the name\n---\n\n# T\n")

    def test_pr1_demands_contents_over_100_lines(self):
        steps = "".join("### Step %d — Do\n\n- Command: c\n- Expect: e\n- Stop if: s\n\n" % i for i in range(1, 25))
        body = "# N\n\n> **Conclusion:** x.\n\n## When to use / not\n\n- a\n\n## Steps\n\n" + steps + "## Gotchas\n\n- g\n\n## Done when\n\n- d\n"
        self.assertGreater(len(body.splitlines()), 100)
        self.assertEqual([f["message"] for f in studio_fmt.check_process_shape(body)], ["process file is over 100 lines and has no '## Contents'"])
        self.assertEqual(studio_fmt.check_process_shape(body.replace("## When to use", "## Contents\n\n- x\n\n## When to use", 1)), [])
        self.assertEqual(studio_fmt.check_process_shape(body.replace("## When to use", "## Mục lục\n\n- x\n\n## When to use", 1)), [])


ATTACK_N = 100_000
ATTACK_BODIES = (" ", "\t", " \t", "---", "#", ":", "`", " #", "> ", "—", "*")
ATTACK_PREFIXES = ("", "  k:", "  k: a", "# ", "## x", "- ", "> **", "Step 1 ", "step 1 — ", "a:", "`" * 3)


class FmtSpeedTests(unittest.TestCase):
    """ReDoS and quadratic loops: every regex of fmt is linear and fmt_text / check_process_shape finish fast on 100 000-character attacks."""

    def patterns(self):
        found = {}
        for name, value in vars(studio_const).items():
            if name.startswith("FMT_") and isinstance(value, re.Pattern):
                found[name] = value
            elif name.startswith("FMT_") and isinstance(value, tuple):
                for index, item in enumerate(value):
                    pattern = item[0] if isinstance(item, tuple) else item
                    if isinstance(pattern, re.Pattern):
                        found["%s[%d]" % (name, index)] = pattern
        for name in ("CONTENTS_RE", "FENCE_OPEN_RE", "FRONT_KEY_RE"):
            found[name] = getattr(studio_const, name)
        return found

    def timed(self, label, call, limit=5.0):
        start = time.perf_counter()
        call()
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, limit, "%s took %.1f s" % (label, elapsed))

    def test_fmt_regexes_are_linear(self):
        patterns = self.patterns()
        self.assertGreaterEqual(len(patterns), 14)
        self.assertIn("FMT_META_LINE_RE", patterns)
        self.assertIn("FMT_HEADING_RE", patterns)
        slow = []
        for prefix in ATTACK_PREFIXES:
            for body in ATTACK_BODIES:
                for tail in ("", "b"):
                    text = prefix + body * (ATTACK_N // len(body)) + tail
                    for name, pattern in patterns.items():
                        for method in (pattern.search, pattern.fullmatch):
                            start = time.perf_counter()
                            method(text)
                            elapsed = time.perf_counter() - start
                            if elapsed > 1.0:
                                slow.append("%s %s on %r*%d+%r: %.1f s" % (name, method.__name__, prefix + body, ATTACK_N // len(body), tail, elapsed))
                    if slow:
                        self.fail("; ".join(slow))

    def test_fmt_text_and_process_shape_survive_long_lines(self):
        for width, label in ((" ", "space"), ("\t", "tab"), (" \t", "mixed")):
            run_of = width * (ATTACK_N // len(width))
            meta = "---\nname: demo\ndescription: Checks. Use when testing.\nmetadata:\n  k: a" + run_of + "b\n---\n\n# T\n"
            heading = "# a" + run_of + "b\n\n## Steps\n"
            self.timed("metadata line, %s" % label, lambda: studio_fmt.fmt_text(meta, "skill"))
            self.timed("heading in fmt_text, %s" % label, lambda: studio_fmt.fmt_text(heading, "process"))
            self.timed("heading in check_process_shape, %s" % label, lambda: studio_fmt.check_process_shape(heading))
            self.timed("trailing run, %s" % label, lambda: studio_fmt.fmt_text("# a" + run_of, "other"))
        for token in ("---", "#", ":", "`", " #", "> ", "*", "-"):
            run_of = token * (ATTACK_N // len(token))
            for text in ("---\nname: demo\ndescription: Checks. Use when testing.\nmetadata:\n  k: " + run_of + "\n---\n\n# T\n",
                         "---\nname: " + run_of + "\n---\n\n# T\n", "# " + run_of + "\n", run_of + "\n", "---\n" + run_of + "\n---\n",
                         "\n\n---\ntitle: " + run_of + "\n---\n"):
                for kind in ("skill", "studio-doc", "process", "other"):
                    self.timed("%r %s" % (token, kind), lambda: studio_fmt.fmt_text(text, kind))
                self.timed("%r process shape" % token, lambda: studio_fmt.check_process_shape(text))

    def test_check_process_shape_is_linear_in_the_number_of_steps(self):
        steps = "".join("### Step %d — Go\n\n- Command: c\n- Expect: e\n- Stop if: s\n\n" % i for i in range(1, 10_001))
        text = "# P\n\n> **Conclusion:** x.\n\n## Steps\n\n" + steps
        self.timed("10 000 steps", lambda: studio_fmt.check_process_shape(text))
        self.timed("10 000 headings", lambda: studio_fmt.check_process_shape("# P\n" + "".join("## S%d\n" % i for i in range(30_000))))
        self.timed("fmt_text on a long file", lambda: studio_fmt.fmt_text(text, "process"))


class FmtSmallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_remove_quietly_never_raises(self):
        studio_fs._remove_quietly(self.tmp / "missing")  # nothing to remove
        plain = write(self.tmp / "plain", "x")
        studio_fs._remove_quietly(plain)
        self.assertFalse(plain.exists())
        locked = write(self.tmp / "locked", "x")
        os.chmod(locked, stat.S_IREAD)
        studio_fs._remove_quietly(locked)  # a read-only file (a copied mode) goes: on Windows after losing the bit, on POSIX at once (unlink needs a writable folder, not a writable file)
        self.assertFalse(locked.exists())
        with mock.patch.object(os, "unlink", side_effect=PermissionError(13, "no")), mock.patch.object(os, "chmod", side_effect=PermissionError(13, "no")):
            studio_fs._remove_quietly(plain)  # cannot even change the mode: still no exception
        with mock.patch.object(os, "unlink", side_effect=PermissionError(13, "no")):
            studio_fs._remove_quietly(plain)  # retried once after the chmod, still no exception

    def test_quote_meta_statuses(self):
        self.assertEqual(studio_fmt._quote_meta("  version: 1"), ('  version: "1"', "fixed"))
        self.assertEqual(studio_fmt._quote_meta('  version: "1"'), ('  version: "1"', "ok"))
        self.assertEqual(studio_fmt._quote_meta("  # a comment"), ("  # a comment", "ok"))
        self.assertEqual(studio_fmt._quote_meta("  key:"), ("  key:", "ok"))
        self.assertEqual(studio_fmt._quote_meta("  note: x # c")[1], "stuck")

    def test_fmt_too_many_folders_is_not_checked_and_exit_1(self):
        for name in ("a", "b", "c"):
            write(self.tmp / name / "x.md", "# X\n")
        with mock.patch.object(studio_const, "DOCTOR_MAX_DIRS", 2):
            code, out, _ = run("--check", str(self.tmp))
        self.assertEqual(code, 1, out)
        self.assertIn("skipped (too-many-folders)", out)


if __name__ == "__main__":
    unittest.main()
