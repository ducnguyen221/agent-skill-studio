"""SPR-04 TK16 (review round 1 of the whole branch): RF-S1 links in the chain, RF-A1/U1/U2/U11 CATALOG.md, RF-A2, RF-A3, RF-S2, RF-S3, README.

Run: python -X utf8 -m unittest tests.test_tk16_fix1 -v
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402
import test_catalog as TC  # noqa: E402
import test_roots as TR  # noqa: E402

R = _engine.roots
fs = _engine.fs
C = _engine.const
ROOT = Path(__file__).resolve().parents[1]

LEAK = "9.9.9-leak"


def make_vault(base: Path) -> Path:
    """A fake secret zone (a folder called .secret) holding bait: a plugin.json, an evals catalog and a paths.json."""
    vault = base / "vault" / ".secret" / "s1"
    vault.mkdir(parents=True)
    (vault / "plugin.json").write_text(json.dumps({"name": "LEAKNAME", "version": LEAK}), encoding="utf-8")
    (vault / "catalog.json").write_text(json.dumps({"schema_version": "1", "skills": [{"path": "skills/alpha", "model_evaluated": True}]}), encoding="utf-8")
    (vault / "paths.json").write_text("not json LEAKTEXT", encoding="utf-8")
    return vault


class ReadJsonChainTests(TC.TmpCase):
    def test_read_json_refuses_link_in_the_middle(self):
        """bắt-lỗi: RF-S1 a junction between base and the file is refused before the file is opened; the bait never reaches the caller."""
        vault = make_vault(self.tmp)
        base = self.tmp / "plug"
        base.mkdir()
        TR.make_link(self, base / ".claude-plugin", vault)
        with self.assertRaises(R.RootError) as ctx:
            R._read_json(base / ".claude-plugin" / "plugin.json", C.MANIFEST_MAX, C.CLOUD_MARKERS, base)
        self.assertEqual(ctx.exception.reason, "link")

    def test_read_json_refuses_link_by_patch(self):
        """bắt-lỗi: RF-S1 the same, with the link faked (POSIX and machines that cannot make a junction)."""
        base = self.tmp / "plug"
        (base / "mid").mkdir(parents=True)
        (base / "mid" / "f.json").write_text("{}", encoding="utf-8")
        real = fs.is_link
        with mock.patch.object(fs, "is_link", lambda p: Path(p) == base / "mid" or real(p)), \
                mock.patch.object(fs, "open_nofollow_read", side_effect=AssertionError("opened")):
            with self.assertRaises(R.RootError) as ctx:
                R._read_json(base / "mid" / "f.json", 1000, C.CLOUD_MARKERS, base)
        self.assertEqual(ctx.exception.reason, "link")

    def test_read_json_refuses_real_path_in_zone(self):
        """bắt-lỗi: RF-S1 a plain-looking path whose real path is a secret zone is refused (zone by the real path, not by the spelling)."""
        vault = make_vault(self.tmp)
        with mock.patch.object(Path, "resolve", lambda self, *a, **k: vault / "plugin.json"):
            with self.assertRaises(R.RootError) as ctx:
                R._read_json(self.tmp / "x" / "plugin.json", 1000, C.CLOUD_MARKERS, self.tmp)
        self.assertEqual(ctx.exception.reason, "secret-zone")

    def test_read_json_plain_file_still_read(self):
        base = self.tmp / "plug"
        base.mkdir()
        (base / "f.json").write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(R._read_json(base / "f.json", 1000, C.CLOUD_MARKERS, base), {"a": 1})

    def test_find_paths_json_opcos_root_junction(self):
        """bắt-lỗi: RF-S1 (c) OPCOS_ROOT that is a junction into a zone: RootError, the paths.json behind it is not parsed."""
        vault = make_vault(self.tmp)
        op = self.tmp / "opj"
        TR.make_link(self, op, vault)
        with self.assertRaises(R.RootError) as ctx:
            R.find_paths_json(self.tmp / "cwd-none", {"OPCOS_ROOT": str(op)})
        self.assertIn(ctx.exception.reason, ("link", "secret-zone"))
        self.assertNotIn("LEAKTEXT", str(ctx.exception))


class CatalogLinkTests(TC.TmpCase):
    def _plug(self):
        lib = self.tmp / "lib"
        plug = lib / "myplug"
        TC.make_skill(plug / "skills" / "alpha")
        return lib, plug

    def test_catalog_roots_manifest_and_evals_junction(self):
        """bắt-lỗi: RF-S1 (a) `catalog --roots` with .claude-plugin and evals as junctions into a zone: no bait in the JSON, no version, no model_evaluated."""
        vault = make_vault(self.tmp)
        lib, plug = self._plug()
        TR.make_link(self, plug / ".claude-plugin", vault)
        TR.make_link(self, plug / "evals", vault)
        code, out, err = TC.run_catalog("--roots", str(plug), "--json")
        self.assertIn(code, (0, 1), out + err)
        self.assertNotIn(LEAK, out)
        self.assertNotIn("LEAKNAME", out)
        row = json.loads(out)["skills"][0]
        self.assertIsNone(row["plugin_version"])
        self.assertIsNone(row["model_evaluated"])

    def test_catalog_opcos_evals_junction_is_not_silent(self):
        """bắt-lỗi: RF-S1 (b) a plugin whose evals is a junction into a zone gives model_evaluated null, never the bait."""
        vault = make_vault(self.tmp)
        tree = self.clean_tree()
        plug = tree / "plugins" / "p-two"
        TR.make_link(self, plug / "evals", vault)
        (vault / "catalog.json").write_text(json.dumps({"schema_version": "1", "skills": [{"path": "skills/two", "model_evaluated": True}]}), encoding="utf-8")
        report = self.report(tree)
        row = next(r for r in report["skills"] if r["name"] == "two")
        self.assertIsNone(row["model_evaluated"])


# --- CATALOG.md: summary, "Cần xem trước", provenance line (RF-A1/U1, RF-U2, RF-U11) -----------------------------------------------------------------

def _pair(a, b, label):
    return {"a": a, "b": b, "label": label, "evidence": ["e"], "suggestion": "keep", "needs_review": True}


def _state(state="absent", compare=None):
    return {"state": state, "version": None, "compare": compare}


class MarkdownTk16Tests(TC.TmpCase):
    def report_for(self, pairs, errors=None, differ=None):
        module = TC.load_catalog_module()
        report = module.build(R.opcos_roots(self.clean_tree() / "paths.json"), [], False, "portable")
        report["pairs"] = pairs
        for row, count in zip(report["skills"], errors or []):
            row["doctor"]["errors"] = count
        for row, harness in zip(report["skills"], differ or []):
            row["installed"][harness] = _state("differ")
        report["totals"]["pairs_to_review"] = sum(p["label"] in ("same_name_other_role", "same_function", "version_drift") for p in pairs or [])
        return module, report

    def test_summary_counts_what_needs_a_person_not_copies(self):
        """bắt-lỗi: RF-A1 one copy + one of each real label + one insufficient: the first sentence counts 3 pairs to review, with the split."""
        pairs = [_pair("a", "b", "distribution_copy"), _pair("c", "d", "version_drift"), _pair("e", "f", "same_name_other_role"),
                 _pair("g", "h", "same_function"), _pair("i", "j", "insufficient_evidence")]
        module, report = self.report_for(pairs, errors=[2, 0], differ=["codex"])
        line = module.render_md(report).splitlines()[4]
        self.assertEqual(line, "2 skill nguồn ở 2 repo; 0 gốc không ok. Cần xem: 1 skill có ERROR, 1 bản cài lệch (khác), "
                               "3 cặp nghi trùng (cùng tên khác vai 1, trùng chức năng 1, khác phiên bản 1).")

    def test_summary_without_overlap_has_no_pair_clause(self):
        """bắt-lỗi: RF-A1 `pairs` null (no --overlap): the sentence does not say «0 cặp»."""
        module, report = self.report_for(None)
        line = module.render_md(report).splitlines()[4]
        self.assertEqual(line, "2 skill nguồn ở 2 repo; 0 gốc không ok. Cần xem: 0 skill có ERROR, 0 bản cài lệch (khác).")

    def test_json_totals_pairs_to_review(self):
        """bắt-lỗi: RF-A1 `totals.pairs_to_review` exists and `pairs` still counts every pair."""
        module = TC.load_catalog_module()
        report = module.build(R.opcos_roots(self.clean_tree() / "paths.json"), [], True, "portable")
        self.assertEqual(report["totals"], {"skills": 2, "repos": 2, "roots_not_ok": 0, "pairs": 0, "pairs_to_review": 0})

    def test_need_to_see_section_order_and_size(self):
        """bắt-lỗi: RF-U2 «Cần xem trước» follows the summary, holds at most 25 lines however many items, and «Chỉ có bản cài» is the last section."""
        module, report = self.report_for([_pair("p%d" % i, "q%d" % i, "same_function") for i in range(40)])
        base = report["skills"][0]
        report["skills"] = [dict(base, name="s%d" % i, doctor={"errors": i + 1, "warnings": 0},
                                 installed={"claude": _state("differ"), "codex": _state(), "antigravity": _state()}) for i in range(40)]
        lines = module.render_md(report).splitlines()
        heads = [x for x in lines if x.startswith("## ")]
        self.assertEqual(heads, ["## Cần xem trước", "## Skill theo repo", "## Gốc không ok", "## Cặp trùng", "## Chỉ có bản cài"])
        start, end = lines.index("## Cần xem trước"), lines.index("## Skill theo repo")
        self.assertLessEqual(end - start, 25)
        block = "\n".join(lines[start:end])
        self.assertIn("Cặp trùng", block)  # more pairs than fit: pointed to the section, not listed
        self.assertIn("s39", block)        # the worst skill by ERROR is named

    def test_need_to_see_section_empty(self):
        module, report = self.report_for([])
        self.assertIn("## Cần xem trước\n\nKhông có gì cần xem.", module.render_md(report))

    def test_provenance_line(self):
        """bắt-lỗi: RF-U11 the line after the summary says when (UTC, as generated_at) and with which command; no absolute home path."""
        module, report = self.report_for([])
        text = module.render_md(report, "studio.py catalog --roots ~/x --overlap")
        self.assertEqual(text.splitlines()[5], "Sinh lúc %s (UTC) bằng `studio.py catalog --roots ~/x --overlap`." % report["generated_at"])
        tree = self.tmp / "clean"
        out = self.tmp / "CATALOG.md"
        code, so, se = TC.run_catalog("--roots", str(tree / "plugins" / "p-two" / "skills"), "--md", str(out))
        written = out.read_text(encoding="utf-8").splitlines()[5]
        self.assertTrue(written.startswith("Sinh lúc "), written)
        self.assertIn("studio.py catalog --roots", written)
        self.assertNotIn(os.path.expanduser("~").replace("\\", "/"), written.replace("\\", "/"))


# --- RF-U3 README ------------------------------------------------------------------------------------------------------------------------------

class ReadmeTests(unittest.TestCase):
    def test_readme_does_not_refuse_tmp_on_macos(self):
        """bắt-lỗi: RF-U3 FR13.2 allows /tmp and /var on macOS; the README must not say they are refused."""
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"/tmp.{0,80}bị từ chối", text), "README still says /tmp is refused")
        self.assertIn("link do người dùng tạo vẫn bị từ chối", text)


# --- RF-A3, RF-A2 ------------------------------------------------------------------------------------------------------------------------------

class CloudNameRootsTests(TC.TmpCase):
    def lib(self):
        lib = self.tmp / "lib"
        TC.make_skill(lib / "alpha")
        TC.make_skill(lib / "OneDrive-backup" / "beta")
        return lib

    def test_catalog_roots_cloud_name_is_by_rule(self):
        """bắt-lỗi: RF-A3 `catalog --roots`: a folder named like a cloud zone is cloud-name by rule, the root stays ok, exit 0."""
        code, out, err = TC.run_catalog("--roots", str(self.lib()), "--json")
        self.assertEqual(code, 0, out + err)
        root = json.loads(out)["roots"][0]
        self.assertEqual((root["status"], root["reasons"]), ("ok", []))
        self.assertEqual([x["reason"] for x in root["skipped_by_rule"]], ["cloud-name"])


class UnhashableInstalledTests(TC.TmpCase):
    def test_unhashable_copy_is_not_a_claimed_difference(self):
        """bắt-lỗi: RF-A2 a copy that cannot be hashed (secret-looking file) gives compare «unhashable», the pair is insufficient_evidence, CATALOG.md says «không so được»."""
        import shutil
        module = TC.load_catalog_module()
        tree = self.clean_tree()
        src = tree / "plugins" / "p-two" / "skills" / "two"
        (src / "scripts").mkdir()
        (src / "scripts" / ".env.example").write_text("X=1\n", encoding="utf-8")
        copy = self.tmp / "claude-copy" / "two"
        shutil.copytree(src, copy)
        records = [{"harness": "claude", "plugin": "p-two", "skill": "two", "path": copy.as_posix(), "version": None, "scope": None}]
        report = module.build(R.opcos_roots(tree / "paths.json"), records, True, "portable")
        row = next(r for r in report["skills"] if r["name"] == "two")
        self.assertIsNone(row["tree_sha256"])
        self.assertEqual(row["installed"]["claude"]["state"], "differ")
        self.assertEqual(row["installed"]["claude"]["compare"], "unhashable")
        self.assertEqual([p["label"] for p in report["pairs"]], ["insufficient_evidence"])
        text = module.render_md(report)
        self.assertIn("không so được", text)
        self.assertIn("0 bản cài lệch", text)


# --- RF-S2 -------------------------------------------------------------------------------------------------------------------------------------

class PairCeilingTests(TC.TmpCase):
    def test_overlap_stops_at_the_ceiling(self):
        """bắt-lỗi: RF-S2 more nominated pairs than OVERLAP_MAX_PAIRS: the list stops at the ceiling, one `limit` note is written, the root stays ok."""
        import curator_overlap as O
        self.assertEqual(O.OVERLAP_MAX_PAIRS, 20000)
        module = TC.load_catalog_module()
        plug = self.tmp / "plugs" / "p"
        for i in range(12):
            folder = plug / "skills" / ("s%d" % i)
            folder.mkdir(parents=True)
            desc = ("Reconciles credit card statements against receipts and assigns cost centres." if i % 2 else
                    "Translates legal contracts between several languages carefully for clients.")
            lines = ["---", "name: s%d" % i, "description: " + desc, "---", "", "# T", "", "Body.", ""]
            (folder / "SKILL.md").write_text(chr(10).join(lines), encoding="utf-8")
        (plug / ".claude-plugin").mkdir()
        (plug / ".claude-plugin" / "plugin.json").write_text('{"name": "p"}', encoding="utf-8")
        roots = [R._new_root(plug, "plugin", "roots")]
        notes: list = []
        with mock.patch.object(O, "OVERLAP_MAX_PAIRS", 5):
            report = module.build(roots, [], True, "portable", None, (), notes)
        self.assertLessEqual(len(report["pairs"]), 5)
        self.assertEqual(len([n for n in notes if "limit" in n]), 1, notes)
        self.assertEqual(report["roots"][0]["status"], "ok")


# --- RF-S3 -------------------------------------------------------------------------------------------------------------------------------------

class CheckPathLinkTests(TC.TmpCase):
    def test_link_is_refused_before_is_file(self):
        """bắt-lỗi: RF-S3 `check alias/x.md` with `alias` a link: refused without a stat of the target (Path.is_file is not called)."""
        real = self.tmp / "real"
        real.mkdir()
        (real / "x.md").write_text("# x\n", encoding="utf-8")
        TR.make_link(self, self.tmp / "alias", real)
        seen = []
        original = Path.is_file

        def spy(path):
            seen.append(os.fspath(path))
            return original(path)

        before = os.getcwd()
        os.chdir(self.tmp)
        try:
            with mock.patch.object(Path, "is_file", spy):
                with self.assertRaises(ValueError) as ctx:
                    _engine.validate.resolve_check_path(os.path.join("alias", "x.md"))
        finally:
            os.chdir(before)
        self.assertIn("link", str(ctx.exception))
        self.assertEqual([s for s in seen if s.endswith("x.md")], [])
