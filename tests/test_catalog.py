"""SPR-04 TK9 (FR2, FR7, FR9.1, FR9.2, SC2, SC3): the `catalog` command, its rows, root states, exit codes, CATALOG.md and the opcos keys.

Run: python -X utf8 -m unittest tests.test_catalog -v
"""
from __future__ import annotations

import contextlib
import io
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
import _engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "opcos-tree"
CURATOR_DIR = ROOT / "skills" / "skill-curator" / "scripts"
studio = _engine.engine

SKILL = "---\nname: %s\ndescription: Checks a toy example. Use when testing the catalog.\n---\n\n# Title\n\nShort body.\n"
OPCOS_SKILL = ('---\nname: a\ndescription: Fixture skill with registry keys. Use when testing the opcos keys.\nmetadata:\n  opcos_when: "x"\n'
               '  opcos_rank: 3\n  opcos_tags: [a]\n---\n\n# a\n\nShort body.\n')


def load_catalog_module():
    """`curator_catalog` as `studio.py catalog` loads it (the folder is fixed from the engine file)."""
    module, problem = studio.load_curator_catalog()
    assert module is not None, problem
    return module


def run_catalog(*argv, cwd=None):
    """Run `studio.py catalog ...` in-process (cwd switched when given, OPCOS_ROOT unset); returns (exit code, stdout, stderr). A flag error is exit 2."""
    out, err = io.StringIO(), io.StringIO()
    before = os.getcwd()
    code = 0
    try:
        if cwd is not None:
            os.chdir(cwd)
        with mock.patch.dict(os.environ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            os.environ.pop("OPCOS_ROOT", None)
            try:
                code = studio.main(["catalog", *argv])
            except SystemExit as exc:
                code = exc.code
    finally:
        os.chdir(before)
    return code, out.getvalue(), err.getvalue()


def make_skill(folder: Path, name: str = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_bytes((SKILL % (name or folder.name)).encode("utf-8"))
    return folder


class TmpCase(unittest.TestCase):
    def setUp(self):
        _engine.clear_caches()
        self.addCleanup(_engine.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-catalog-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def tree(self, name="tree") -> Path:
        """A copy of the TK5 fixture tree; its `a` skill carries the three opcos keys."""
        dest = self.tmp / name
        shutil.copytree(FIX, dest)
        (dest / "plugins" / "p-default" / "skills" / "a" / "SKILL.md").write_bytes(OPCOS_SKILL.encode("utf-8"))
        return dest

    def clean_tree(self, name="clean") -> Path:
        """An OpcOS tree whose roots hold two plain skills, a vendor folder (by rule) and nothing else: every root is ok."""
        base = self.tmp / name
        (base / "plugins").mkdir(parents=True)
        (base / "system" / "opcos-plugin" / ".claude-plugin").mkdir(parents=True)
        (base / "system" / "opcos-plugin" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "opcos-core", "version": "1.2.3"}), encoding="utf-8")
        make_skill(base / "system" / "opcos-plugin" / "skills" / "one")
        plugin = base / "plugins" / "p-two"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "p-two"}), encoding="utf-8")
        make_skill(plugin / "skills" / "two")
        vendor = base / "plugins" / "vendor-y"
        (vendor / ".claude-plugin").mkdir(parents=True)
        (vendor / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "vendor-y"}), encoding="utf-8")
        make_skill(vendor / "skills" / "v")
        (base / "paths.json").write_text(json.dumps({"version": 1, "areas": [{"id": "opcos-plugin", "rel_path": "system/opcos-plugin"}, {"id": "plugins", "rel_path": "plugins"}]}), encoding="utf-8")
        return base

    def report(self, tree: Path, *extra) -> dict:
        out = self.tmp / ("report-%d.json" % len(list(self.tmp.glob("report-*.json"))))
        code, so, se = run_catalog("--roots-from", "opcos", "--out", str(out), *extra, cwd=tree)
        self.assertIn(code, (0, 1), so + se)
        return json.loads(out.read_text(encoding="utf-8"))


class RowsTests(TmpCase):
    def test_rows_one_per_source_skill(self):
        """bắt-lỗi: FR2.1 the fixture gives exactly five rows, one per source skill, each with every key of schema 1."""
        report = self.report(self.tree())
        self.assertEqual(report["schema"], 1)
        self.assertEqual(sorted(r["name"] for r in report["skills"]), ["a", "b", "c", "h", "root"])
        self.assertEqual(set(report), {"schema", "generated_at", "studio_version", "roots", "skills", "installed_only", "pairs", "totals"})
        for row in report["skills"]:
            self.assertEqual(set(row), {"name", "description_short", "repo", "path", "plugin_version", "tree_sha256", "installed", "doctor", "model_evaluated", "opcos"})
            self.assertEqual({h: v["state"] for h, v in row["installed"].items()}, {"claude": "absent", "codex": "absent", "antigravity": "absent"})
            self.assertEqual(set(row["doctor"]), {"errors", "warnings"})
            self.assertEqual(len(row["tree_sha256"]), 64)
            self.assertIsNone(row["model_evaluated"])
            self.assertNotIn("\\", row["path"])
        by = {r["name"]: r for r in report["skills"]}
        self.assertEqual((by["a"]["repo"], by["c"]["repo"]), ("p-default", "k"))
        self.assertEqual(report["totals"], {"skills": 5, "repos": 5, "roots_not_ok": 1, "pairs": 0, "pairs_to_review": 0, "installed_differ_skills": 0, "pairs_truncated": False})
        self.assertIsNone(report["pairs"])
        self.assertEqual(report["installed_only"], [])

    def test_description_is_short_and_one_line(self):
        """bắt-lỗi: FR2.1 description_short is at most 160 characters, on one line, cut at a word."""
        module = load_catalog_module()
        long = "word " * 80
        short = module.short_description(long)
        self.assertLessEqual(len(short), 160)
        self.assertTrue(short.endswith("…"))
        self.assertNotIn("  ", short)
        self.assertEqual(module.short_description("a\n  b   c"), "a b c")
        self.assertEqual(module.short_description("x" * 160), "x" * 160)
        self.assertEqual(len(module.short_description("x" * 400)), 160)

    def test_paths_under_home_are_written_with_a_tilde(self):
        """bắt-lỗi: SPEC ASSUMPTION the path of a skill and of a root below the home folder is written ~/..., never with the user name."""
        module = load_catalog_module()
        tree = self.tree()
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp), "USERPROFILE": str(self.tmp)}):
            code, out, err = run_catalog("--roots-from", "opcos", "--json", cwd=tree)
        self.assertIn(code, (0, 1), err)
        report = json.loads(out)
        self.assertTrue(all(r["path"].startswith("~/tree/") for r in report["skills"]), [r["path"] for r in report["skills"]])
        self.assertTrue(all(r["path"].startswith("~/tree/") for r in report["roots"]))
        self.assertNotIn(self.tmp.as_posix(), out)
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp), "USERPROFILE": str(self.tmp)}):
            self.assertEqual(module.home_path(self.tmp / "x" / "y"), "~/x/y")
            self.assertEqual(module.home_path("/elsewhere/z"), "/elsewhere/z")

    def test_model_evaluated_from_the_repo_catalog(self):
        """bắt-lỗi: FR2.1 model_evaluated is read from the plugin's evals/catalog.json when it has the Studio schema, else null."""
        tree = self.clean_tree()
        plugin = tree / "plugins" / "p-two"
        (plugin / "evals").mkdir()
        entries = {"schema_version": "1.0", "skills": [{"name": "two", "path": "skills/two", "model_evaluated": True}, {"name": "x", "path": "skills/zzz", "model_evaluated": 1}]}
        (plugin / "evals" / "catalog.json").write_text(json.dumps(entries), encoding="utf-8")
        by = {r["name"]: r for r in self.report(tree)["skills"]}
        self.assertIs(by["two"]["model_evaluated"], True)
        self.assertIsNone(by["one"]["model_evaluated"])
        (plugin / "evals" / "catalog.json").write_text(json.dumps({"skills": entries["skills"]}), encoding="utf-8")  # no schema_version: not the Studio schema
        self.assertIsNone({r["name"]: r for r in self.report(tree)["skills"]}["two"]["model_evaluated"])
        (plugin / "evals" / "catalog.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone({r["name"]: r for r in self.report(tree)["skills"]}["two"]["model_evaluated"])

    def test_plugin_version_and_doctor_counts(self):
        """bắt-lỗi: FR2.1 the plugin version comes from its manifest; the doctor counts are those of `doctor` for that skill."""
        by = {r["name"]: r for r in self.report(self.clean_tree())["skills"]}
        self.assertEqual(by["one"]["plugin_version"], "1.2.3")
        self.assertIsNone(by["two"]["plugin_version"])
        broken = self.tree()
        by = {r["name"]: r for r in self.report(broken)["skills"]}
        self.assertGreaterEqual(by["a"]["doctor"]["errors"], 1, "the list value of opcos_tags is an FM1 error in doctor")

    def test_installed_copies_match_differ_and_only(self):
        """bắt-lỗi: FR3.2 an installed copy of the same (plugin, skill) is `match` with the same tree hash and `differ` otherwise; one without a source is listed apart."""
        module = load_catalog_module()
        tree = self.clean_tree()
        roots = _engine.roots.opcos_roots(tree / "paths.json")
        inst = self.tmp / "inst"
        same, other = inst / "claude" / "two", inst / "codex" / "two"
        shutil.copytree(tree / "plugins" / "p-two" / "skills" / "two", same)
        shutil.copytree(same, other)
        (other / "extra.md").write_text("changed\n", encoding="utf-8")
        lone = make_skill(inst / "antigravity" / "lonely")
        records = [{"harness": "claude", "plugin": "p-two", "skill": "two", "path": same.as_posix(), "version": "0.1.0", "scope": None},
                   {"harness": "codex", "plugin": "p-two", "skill": "two", "path": other.as_posix(), "version": "0.2.0", "scope": None},
                   {"harness": "antigravity", "plugin": "elsewhere", "skill": "lonely", "path": lone.as_posix(), "version": None, "scope": None}]
        report = module.build(roots, records, False, "portable")
        row = {r["name"]: r for r in report["skills"]}["two"]
        self.assertEqual(row["installed"]["claude"], {"state": "match", "version": "0.1.0", "compare": "byte"})
        self.assertEqual(row["installed"]["codex"], {"state": "differ", "version": "0.2.0", "compare": None})
        self.assertEqual(row["installed"]["antigravity"]["state"], "absent")
        self.assertEqual([(i["harness"], i["skill"]) for i in report["installed_only"]], [("antigravity", "lonely")])
        text = module.render_md(report)
        self.assertIn("| khớp | khác (0.2.0) | — |", text)
        self.assertRegex(text, r"## Chỉ có bản cài\n\n\| Harness \| Plugin \| Skill")


class RootStatusTests(TmpCase):
    def roots_of(self, report) -> dict:
        return {r["area"]: r for r in report["roots"]}

    def test_root_status_ok_partial_error(self):
        """bắt-lỗi: FR2.2 a clean tree is all ok (the vendor folder is by rule, root stays ok); a manifest that escapes makes plugins partial; a missing area is error."""
        clean = self.roots_of(self.report(self.clean_tree()))
        self.assertEqual({k: v["status"] for k, v in clean.items()}, {"opcos-plugin": "ok", "plugins": "ok"})
        self.assertIn(("vendor-y", "vendor"), [(Path(x["path"]).name, x["reason"]) for x in clean["plugins"]["skipped_by_rule"]])
        fixture = self.roots_of(self.report(self.tree()))
        self.assertEqual(fixture["plugins"]["status"], "partial")
        self.assertIn("manifest-escape", fixture["plugins"]["reasons"])
        gone = self.clean_tree("gone")
        shutil.rmtree(gone / "plugins")
        statuses = self.roots_of(self.report(gone))
        self.assertEqual((statuses["opcos-plugin"]["status"], statuses["plugins"]["status"]), ("ok", "error"))
        self.assertEqual(statuses["plugins"]["reasons"], ["not-found"])

    def test_exit_codes(self):
        """bắt-lỗi: FR2.3 exit 0 every root ok, 1 a root partial or error, 2 nothing scanned or a flag that cannot be used."""
        clean = self.clean_tree()
        self.assertEqual(run_catalog("--roots-from", "opcos", cwd=clean)[0], 0)
        self.assertEqual(run_catalog("--roots-from", "opcos", cwd=self.tree())[0], 1)
        gone = self.clean_tree("gone")
        shutil.rmtree(gone / "plugins")
        self.assertEqual(run_catalog("--roots-from", "opcos", cwd=gone)[0], 1)
        for argv in (("--no-such-flag",), ("--roots-from", "elsewhere"), ("--roots-from", "opcos", "--roots", str(clean)), ("--installed", "bogus"),
                     ("--roots", str(self.tmp / "missing")), ("--skip-marker", " "), ("--roots-from", "opcos", "--out", str(self.tmp / "o.json"), "--md", str(self.tmp / "o.json"))):
            with self.subTest(argv):
                self.assertEqual(run_catalog(*argv, cwd=clean)[0], 2)
        empty = self.tmp / "empty"
        (empty / "plugins").mkdir(parents=True)
        (empty / "paths.json").write_text(json.dumps({"version": 1, "areas": [{"id": "plugins", "rel_path": "plugins"}]}), encoding="utf-8")
        code, out, err = run_catalog("--roots-from", "opcos", cwd=empty)
        self.assertEqual(code, 2, out + err)
        nothing = self.tmp / "nothing"
        nothing.mkdir()
        code, out, err = run_catalog("--roots", str(nothing))
        self.assertEqual(code, 2, out + err)
        self.assertIn("no skill found", err)
        no_paths = self.tmp / "no-paths"
        no_paths.mkdir()
        code, out, err = run_catalog("--roots-from", "opcos", cwd=no_paths)
        self.assertEqual(code, 2, out + err)

    def test_roots_option_scans_plain_skill_folders(self):
        """bắt-lỗi: FR2.1 --roots lists the skills of plain folders; the repo is the root's name (its parent's for a folder called skills); a skipped cloud-named folder is partial."""
        base = self.tmp / "lib" / "skills"
        make_skill(base / "s1")
        make_skill(base / "s2")
        make_skill(self.tmp / "other" / "o1")
        code, out, err = run_catalog("--roots", "%s;%s" % (base, self.tmp / "other"), "--json")
        self.assertEqual(code, 0, out + err)
        report = json.loads(out)
        self.assertEqual(sorted((r["name"], r["repo"]) for r in report["skills"]), [("o1", "other"), ("s1", "lib"), ("s2", "lib")])
        self.assertEqual({r["status"] for r in report["roots"]}, {"ok"})
        link = self.tmp / "other" / "linked"
        try:
            os.symlink(base, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create a symlink here")
        code, out, err = run_catalog("--roots", str(self.tmp / "other"), "--json")
        self.assertEqual(code, 1, out + err)
        self.assertIn("link", json.loads(out)["roots"][0]["reasons"])

    def test_text_output_and_json_to_stdout(self):
        """bắt-lỗi: FR2.3 without a flag a compact table is printed; --json prints the report; --json with --out writes the file only."""
        tree = self.clean_tree()
        code, out, err = run_catalog("--roots-from", "opcos", cwd=tree)
        self.assertEqual(code, 0, err)
        self.assertIn("catalog: 2 skills in 2 repos; 0 roots not ok", out)
        self.assertIn("one", out)
        code, out, err = run_catalog("--roots-from", "opcos", "--json", cwd=tree)
        self.assertEqual(json.loads(out)["totals"]["skills"], 2)
        target = self.tmp / "only.json"
        code, out, err = run_catalog("--roots-from", "opcos", "--json", "--out", str(target), cwd=tree)
        self.assertNotIn('"schema"', out)
        self.assertIn("written to", out)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["schema"], 1)
        fixture_text = run_catalog("--roots-from", "opcos", cwd=self.tree())[1]
        self.assertIn("/plugins: partial (manifest-escape)", fixture_text)

    def test_installed_and_overlap_flags_are_declared(self):
        """bắt-lỗi: --installed reads the harnesses (an empty home: every locator fails, so each harness root is `error`, exit 1, every copy absent);
        --overlap is accepted (TK11: the pairs are found, so `pairs` is a list, empty over an empty home)."""
        home = self.tmp / "empty-home"
        home.mkdir()
        code, out, err = run_catalog("--roots-from", "opcos", "--installed", "claude,codex", "--home", str(home), "--overlap", "--json", cwd=self.clean_tree())
        self.assertEqual(code, 1, err)
        self.assertNotIn("not read yet", err)
        self.assertNotIn("not available", err)
        report = json.loads(out)
        self.assertEqual(report["pairs"], [])
        self.assertEqual(report["totals"]["pairs"], 0)
        self.assertEqual([(r["area"], r["status"]) for r in report["roots"] if r["kind"] == "harness"], [("claude", "error"), ("codex", "error")])
        self.assertTrue(all(v["state"] == "absent" for r in report["skills"] for v in r["installed"].values()))


class MarkdownTests(TmpCase):
    def test_md_sections(self):
        """bắt-lỗi: FR2.4 CATALOG.md starts with the marker, then the title, the one-sentence summary, a table per repo and the four sections in order."""
        md = self.tmp / "CATALOG.md"
        code, out, err = run_catalog("--roots-from", "opcos", "--md", str(md), cwd=self.tree())
        self.assertEqual(code, 1, out + err)
        text = md.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertEqual(lines[0], "<!-- studio catalog -->")
        self.assertEqual(lines[2], "# Danh mục skill")
        self.assertEqual(lines[4], "5 skill nguồn ở 5 repo; 1 gốc không ok. Cần xem: 2 skill có ERROR, 0 skill có bản cài lệch.")  # TK16 RF-A1: no pair clause without --overlap
        self.assertTrue(lines[5].startswith("Sinh lúc ") and "studio.py catalog --roots-from opcos" in lines[5])  # TK16 RF-U11
        self.assertEqual([x for x in lines if x.startswith("## ")], ["## Cần xem trước", "## Skill theo repo", "## Gốc không ok", "## Cặp trùng", "## Chỉ có bản cài"])  # TK16 RF-U2
        self.assertEqual([x for x in lines if x.startswith("### ")], ["### k", "### p-agents", "### p-default", "### p-nested", "### p-root"])
        self.assertIn("| Skill | Việc | Bản | Claude | Codex | Antigravity | Lỗi | Đã đo |", lines)
        self.assertRegex(text, r"## Gốc không ok\n\n\| Gốc \| Trạng thái \| Lý do \|\n\|---\|---\|---\|\n\| ~?[^|]*plugins \| partial \| manifest-escape \|")
        self.assertIn("Không có.", text)
        self.assertTrue(text.endswith("\n") and "\r" not in text)

    def test_md_pairs_section_when_pairs_are_known(self):
        """bắt-lỗi: FR2.4 a distribution copy is only counted; the other pairs are a table that says they need a person."""
        module = load_catalog_module()
        tree = self.clean_tree()
        report = module.build(_engine.roots.opcos_roots(tree / "paths.json"), [], False, "portable")
        report["pairs"] = [{"a": "p:one", "b": "claude/p:one", "label": "distribution_copy", "evidence": ["same hash"], "suggestion": "keep", "needs_review": True},
                           {"a": "p:two", "b": "q:two", "label": "same_function", "evidence": ["a | b"], "suggestion": "merge", "needs_review": True}]
        text = module.render_md(report)
        self.assertIn("1 cặp là bản sao phân phối", text)
        self.assertIn("| Cặp | Loại | Bằng chứng | Đề xuất |", text)
        self.assertIn("| p:two ↔ q:two | same_function | a \\| b | merge (cần người duyệt) |", text)
        self.assertNotIn("claude/p:one", text.split("## Cặp trùng")[1])


class OpcosKeysTests(TmpCase):
    def test_opcos_keys(self):
        """bắt-lỗi: FR7.1 metadata.opcos_when "x" gives {"when": "x"}, a number is kept as text, a list value is left out and said as a NOTE; a skill with none gets {}."""
        tree = self.tree()
        code, out, err = run_catalog("--roots-from", "opcos", "--json", cwd=tree)
        self.assertEqual(code, 1, err)
        by = {r["name"]: r for r in json.loads(out)["skills"]}
        self.assertEqual(by["a"]["opcos"], {"when": "x", "rank": "3"})
        self.assertEqual(by["b"]["opcos"], {})
        self.assertIn("metadata.opcos_tags is a list or a mapping; not recorded", err)
        self.assertIn("NOTE:", err)

    def test_long_value_is_cut_and_other_keys_are_ignored(self):
        """bắt-lỗi: FR7.1 a value is cut to 160 characters; a key that is not opcos_* is not copied."""
        tree = self.clean_tree()
        skill = tree / "plugins" / "p-two" / "skills" / "two" / "SKILL.md"
        skill.write_bytes(("---\nname: two\ndescription: Fixture. Use when testing.\nmetadata:\n  opcos_note: \"%s\"\n  version: \"1\"\n---\n\n# two\n" % ("w " * 200)).encode("utf-8"))
        by = {r["name"]: r for r in self.report(tree)["skills"]}
        self.assertEqual(list(by["two"]["opcos"]), ["note"])
        self.assertLessEqual(len(by["two"]["opcos"]["note"]), 160)


class CuratorSkillTests(TmpCase):
    def test_catalog_without_curator_exit_2(self):
        """bắt-lỗi: FR9.2 an engine with no skill-curator next to it answers `catalog` with the one-line complaint and exit 2; the other commands still run."""
        lone = self.tmp / "lone" / "skills"
        shutil.copytree(ROOT / "skills" / "skill-creator-studio", lone / "skill-creator-studio", ignore=shutil.ignore_patterns("__pycache__"))
        engine = lone / "skill-creator-studio" / "scripts" / "studio.py"
        done = subprocess.run([sys.executable, str(engine), "catalog", "--roots", str(self.tmp)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stderr.strip(), "ERROR: catalog needs the skill-curator skill next to skill-creator-studio")
        done = subprocess.run([sys.executable, str(engine), "--version"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_foreign_curator_module_is_refused(self):
        """bắt-lỗi: FR11.1 a `curator_*` module already loaded from another folder makes `catalog` exit 2 and name both folders."""
        foreign = self.tmp / "foreign"
        foreign.mkdir()
        (foreign / "curator_catalog.py").write_text("X = 1\n", encoding="utf-8")
        spec = __import__("importlib.util").util.spec_from_file_location("curator_other", foreign / "curator_catalog.py")
        module = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.dict(sys.modules, {"curator_other": module}):
            code, out, err = run_catalog("--roots", str(self.tmp))
        self.assertEqual(code, 2, out + err)
        self.assertIn("curator module curator_other loaded from", err)

    def test_curator_entry_point_runs_catalog_and_doctor(self):
        """bắt-lỗi: FR9.1 `curator.py catalog` gives the same report as `studio.py catalog`; `curator.py doctor` is the engine's doctor; an unknown command is exit 2."""
        tree = self.clean_tree()
        entry = CURATOR_DIR / "curator.py"
        env = dict(os.environ, PYTHONUTF8="1")
        env.pop("OPCOS_ROOT", None)
        base = [sys.executable, str(entry)]
        done = subprocess.run(base + ["catalog", "--roots-from", "opcos", "--json"], capture_output=True, text=True, encoding="utf-8", cwd=tree, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["totals"]["skills"], 2)
        done = subprocess.run(base + ["doctor", "--roots-from", "opcos", "--json"], capture_output=True, text=True, encoding="utf-8", cwd=tree, env=env)
        self.assertIn(done.returncode, (0, 1), done.stderr)
        self.assertEqual(json.loads(done.stdout)["totals"]["skills"], 2)
        for argv, code in ((["--help"], 0), ([], 0), (["nonsense"], 2), (["catalog", "--bogus"], 2)):
            done = subprocess.run(base + argv, capture_output=True, text=True, encoding="utf-8", cwd=tree, env=env)
            self.assertEqual(done.returncode, code, (argv, done.stdout, done.stderr))

    def test_curator_refuses_an_engine_folder_that_lacks_a_module(self):
        """bắt-lỗi: FR9.2 a curator whose sibling engine folder misses one shared module says so and exits 2, loading nothing from the path."""
        lone = self.tmp / "skills"
        shutil.copytree(ROOT / "skills" / "skill-curator", lone / "skill-curator", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "skills" / "skill-creator-studio", lone / "skill-creator-studio", ignore=shutil.ignore_patterns("__pycache__"))
        (lone / "skill-creator-studio" / "scripts" / "studio_roots.py").unlink()
        done = subprocess.run([sys.executable, str(lone / "skill-curator" / "scripts" / "curator.py"), "catalog", "--help"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("curator needs the shared engine modules", done.stderr)

    def test_the_skill_ships_next_to_the_other(self):
        """bắt-lỗi: FR9.1 skill-curator is a second skill of the plugin with a SKILL.md and a reference guide; `check` and `fmt` find nothing."""
        folder = ROOT / "skills" / "skill-curator"
        self.assertTrue((folder / "SKILL.md").is_file())
        self.assertTrue((folder / "references" / "CATALOG_GUIDE.md").is_file())
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
        for script in sorted(p.name for p in (folder / "scripts").glob("*.py")):
            self.assertIn("scripts/" + script, text, "the body names every script (SC3)")


class JsonEncodingTests(TmpCase):
    """cp1252 console or pipe (Windows without PYTHONUTF8): a report with a Vietnamese letter must not crash `check --json` or `catalog --json` (TK14, RQ-192)."""

    def run_cp1252(self, *argv, cwd=None):
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        env.pop("OPCOS_ROOT", None)
        return subprocess.run([sys.executable, str(ROOT / "studio.py"), *argv], capture_output=True, cwd=cwd, env=env)

    def test_check_json_with_vietnamese_text_under_cp1252(self):
        """bắt-lỗi: TK14 `check <skill> --json` with a finding that holds a character outside cp1252 exits by the findings, not by UnicodeEncodeError."""
        skill = self.tmp / "viet-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_bytes("---\nname: viet-skill\ndescription: Kiểm thử. Use when testing the encoding.\nbạn: x\n---\n\n# Title\n\nBody.\n".encode("utf-8"))
        done = self.run_cp1252("check", str(skill), "--json")
        self.assertEqual(done.returncode, 1, done.stderr.decode("ascii", "replace"))
        self.assertNotIn(b"UnicodeEncodeError", done.stderr)
        report = json.loads(done.stdout.decode("ascii"))
        self.assertTrue(any("bạn" in f["message"] for f in report["reports"][0]["findings"]))

    def test_catalog_json_with_vietnamese_text_under_cp1252(self):
        """bắt-lỗi: TK14 `catalog --json` prints the report with ASCII escapes when the console cannot show the description."""
        base = self.tmp / "lib" / "skills"
        folder = base / "viet"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_bytes("---\nname: viet\ndescription: Kiểm thử bản mô tả tiếng Việt. Use when testing.\n---\n\n# Title\n\nBody.\n".encode("utf-8"))
        done = self.run_cp1252("catalog", "--roots", str(base), "--json")
        self.assertEqual(done.returncode, 0, done.stderr.decode("ascii", "replace"))
        self.assertNotIn(b"UnicodeEncodeError", done.stderr)
        report = json.loads(done.stdout.decode("ascii"))
        self.assertIn("Kiểm", report["skills"][0]["description_short"])

    def test_catalog_text_run_never_dies_on_the_console(self):
        """bắt-lỗi: TK14 the compact table and the notes use a safe print: a name outside cp1252 is shown escaped, exit stays 0."""
        base = self.tmp / "lib" / "skills"
        folder = base / "viet"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_bytes("---\nname: bạn\ndescription: Mô tả. Use when testing.\n---\n\n# Title\n\nBody.\n".encode("utf-8"))
        done = self.run_cp1252("catalog", "--roots", str(base))
        self.assertEqual(done.returncode, 0, done.stderr.decode("ascii", "replace"))
        self.assertIn(b"b\\u1ea1n", done.stdout)


if __name__ == "__main__":
    unittest.main()
