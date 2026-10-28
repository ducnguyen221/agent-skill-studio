"""SPR-04 TK11 (FR4.1-FR4.4, SC5): `catalog --overlap` nominates pairs and gives each exactly one of five labels with fixed evidence and suggestion.

Run: python -X utf8 -m unittest tests.test_overlap -v
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402
import test_catalog as TC  # noqa: E402
import test_installed as TI  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "overlap" / "plugins"
studio = _engine.engine
LABELS = {"distribution_copy", "version_drift", "same_function", "same_name_other_role", "insufficient_evidence"}
SUGGEST = {"distribution_copy": "keep", "version_drift": "sync", "same_function": "merge", "same_name_other_role": "keep", "insufficient_evidence": "keep"}
FILLERS = ["Plans gardening schedules for seasonal vegetables and flowers.",
           "Translates legal contracts between several languages carefully.",
           "Renders animated charts from spreadsheets for presentations.",
           "Coaches runners through marathon training weeks.",
           "Summarises weather forecasts for sailing trips.",
           "Catalogues vintage records and listening notes."]
CARD = "Reconciles credit card statements against receipts and assigns cost centres. Use when closing the month."


def modules():
    catalog = TC.load_catalog_module()
    import curator_overlap
    return catalog, curator_overlap


O = modules()[1]
CAT = modules()[0]


def write_skill(base: Path, plugin: str, skill: str, name: str = None, desc: str = CARD, refs=(), scripts=(), body: str = "# T\n\nBody.\n", eol: str = "\n") -> dict:
    """A skill folder under base/<plugin>/skills/<skill> and the item record `curator_overlap` takes (a source skill)."""
    folder = base / plugin / "skills" / skill
    (folder / "references").mkdir(parents=True, exist_ok=True)
    (folder / "scripts").mkdir(parents=True, exist_ok=True)
    text = "---\nname: %s\ndescription: %s\n---\n\n%s" % (name or skill, json.dumps(desc), body)
    (folder / "SKILL.md").write_bytes(text.replace("\n", eol).encode("utf-8"))
    for ref in refs:
        (folder / "references" / ref).write_text("ref %s\n" % ref, encoding="utf-8")
    for script in scripts:
        (folder / "scripts" / script).write_text("# %s\n" % script, encoding="utf-8")
    return item(folder, plugin, skill, name or skill, desc)


def item(folder: Path, plugin: str, skill: str, name: str, desc: str, harness: str = None) -> dict:
    key = "%s:%s" % (plugin, skill) if harness is None else "%s/%s:%s" % (harness, plugin, skill)
    return {"key": key, "plugin": plugin, "skill": skill, "name": name, "desc": desc, "path": str(folder), "harness": harness}


def installed_copy(base: Path, source: dict, harness: str = "claude", edit=None) -> dict:
    """A copy of `source` as an installed skill; `edit(folder)` may change it afterwards."""
    folder = base / harness / source["plugin"] / source["skill"]
    shutil.copytree(source["path"], folder)
    if edit:
        edit(folder)
    return item(folder, source["plugin"], source["skill"], source["name"], source["desc"], harness)


def corpus(*items):
    return O.doc_freq([i["desc"] for i in items] + FILLERS)


class TmpCase(unittest.TestCase):
    def setUp(self):
        _engine.clear_caches()
        self.tmp = Path(tempfile.mkdtemp(prefix="overlap-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(_engine.clear_caches)

    def classify(self, a, b):
        df, n = corpus(a, b)
        return O.classify(a, b, df, n)


class SimilarityTests(unittest.TestCase):
    def test_identical_descriptions_score_one_and_disjoint_zero(self):
        df, n = O.doc_freq([CARD] + FILLERS)
        self.assertAlmostEqual(O.similarity(CARD, CARD, df, n), 1.0)
        self.assertEqual(O.similarity(CARD, FILLERS[0], df, n), 0.0)

    def test_short_words_and_stopwords_do_not_count(self):
        self.assertEqual(O.words("The cat and the dog"), set())
        base = "Reconciles statements against receipts"
        df, n = O.doc_freq([base, base + " when with this from"] + FILLERS)
        self.assertAlmostEqual(O.similarity(base, base + " when with this from", df, n), 1.0)
        for word in ("when", "with", "this", "from", "không", "những"):
            self.assertIn(word, O.STOPWORDS)

    def test_weight_is_log_n_over_df(self):
        """A word every skill has weighs nothing; a rare word dominates the score."""
        descs = ["common alpha rarity", "common beta rarity", "common gamma other"]
        df, n = O.doc_freq(descs)
        self.assertEqual((df["common"], n), (3, 3))
        one = O.similarity(descs[0], descs[1], df, n)   # share `common` (weight 0) and `rarity` (log(3/2))
        two = O.similarity(descs[0], descs[2], df, n)   # share only `common`
        self.assertGreater(one, 0.0)
        self.assertEqual(two, 0.0)

    def test_vietnamese_words_are_kept(self):
        self.assertEqual(O.words("Đối chiếu hoá đơn"), {"chiếu"})  # the other three words have fewer than four characters
        self.assertEqual(O.words("ABC-123 abc123"), {"abc123"})


class CandidateTests(TmpCase):
    def test_nominates_the_four_kinds_and_only_them(self):
        src = self.tmp / "src"
        a1 = write_skill(src, "pa", "audit", desc="Audits documentation sites for broken links and stale pages.")
        a2 = write_skill(src, "pb", "audit", desc="Checks ledgers for sampling gaps before month end.")
        b1 = write_skill(src, "pa", "grader", desc=CARD)
        b2 = write_skill(src, "pc", "cardio", desc=CARD)
        c1 = write_skill(src, "pa", "lonely", desc="Plans gardening schedules for seasonal vegetables only.")
        inst = installed_copy(self.tmp, a1)
        inst2 = installed_copy(self.tmp, a1, harness="codex")
        rows = [a1, a2, b1, b2, c1]
        pairs = {(x["key"], y["key"]) for x, y in O.candidates(rows, [inst, inst2])}
        keys = lambda *z: tuple(i["key"] for i in z)  # noqa: E731
        self.assertIn(keys(a1, inst), pairs)                                   # source <-> installed copy
        self.assertIn(keys(a1, inst2), pairs)
        self.assertIn(keys(inst, inst2), pairs)                                # two installed copies
        self.assertIn(keys(a1, a2), pairs)                                     # same name, other plugin
        self.assertIn(keys(b1, b2), pairs)                                     # other names, similar description
        self.assertFalse([p for p in pairs if "pa:lonely" in p], "a skill with nothing alike is nominated against nobody")
        self.assertEqual(len(pairs), len({frozenset(p) for p in pairs}), "a pair is listed once")

    def test_threshold_nominate_is_020(self):
        self.assertEqual(O.NOMINATE, 0.20)
        self.assertEqual(O.SAME_FUNCTION, 0.30)


class RepresentativeCandidateTests(TmpCase):
    """RF-11.1: `same name: in two plugins` covers every (plugin, skill), also a skill that is only installed, one representative each."""

    def pairs(self, rows, installed):
        return sorted(tuple(i["key"] for i in p) for p in O.candidates(rows, installed))

    def test_source_and_installed_only_plugin_with_same_name(self):
        src = self.tmp / "src"
        notes = write_skill(src, "pa", "notes", desc="Keeps meeting notes tidy and filed.")
        other = write_skill(self.tmp / "other", "pz", "notes", desc="Draws sketches of ocean currents.")
        inst_other = installed_copy(self.tmp, other)  # pz has no source here, only its installed copy
        own = installed_copy(self.tmp, notes)         # the installed copy of pa itself
        got = self.pairs([notes], [inst_other, own])
        self.assertIn(("pa:notes", "claude/pz:notes"), got)
        self.assertEqual(len([p for p in got if "claude/pz:notes" in p]), 1, "one pair for the relation, not one per copy")
        self.assertNotIn(("claude/pa:notes", "claude/pz:notes"), got)
        pair = O.classify(notes, inst_other, *corpus(notes, inst_other))
        self.assertEqual(pair["label"], "same_name_other_role")

    def test_two_installed_only_plugins_with_same_name(self):
        px = write_skill(self.tmp / "x", "px", "pdf", desc="Reads portable documents and extracts the text.")
        py = write_skill(self.tmp / "y", "py", "pdf", desc="Fills forms in scanned paperwork for clerks.")
        got = self.pairs([], [installed_copy(self.tmp, px, "codex"), installed_copy(self.tmp, py, "codex"), installed_copy(self.tmp, px, "claude"),
                              installed_copy(self.tmp, py, "claude")])
        self.assertEqual([p for p in got if p[0].split("/")[1] != p[1].split("/")[1]], [("claude/px:pdf", "claude/py:pdf")])

    def test_representative_is_stable_and_prefers_the_source(self):
        px = write_skill(self.tmp / "x", "px", "pdf", desc="Reads portable documents and extracts the text.")
        py = write_skill(self.tmp / "y", "py", "pdf", desc="Fills forms in scanned paperwork for clerks.")
        a, b = installed_copy(self.tmp, px, "codex"), installed_copy(self.tmp, px, "antigravity")
        c = installed_copy(self.tmp, py, "antigravity")
        self.assertEqual(self.pairs([], [b, a, c]), self.pairs([], [a, c, b]))
        self.assertIn(("antigravity/py:pdf", "codex/px:pdf"), self.pairs([], [b, a, c]))  # codex comes before antigravity: it represents px
        self.assertIn(("px:pdf", "antigravity/py:pdf"), self.pairs([px], [b, a, c]))     # a source copy beats every installed one


class TreeCacheTests(TmpCase):
    """RF-11.2: one run hashes a tree once (bytes) and folds it once (semantic); equal bytes never reach the semantic digest."""

    def test_find_pairs_hashes_each_tree_once(self):
        src = write_skill(self.tmp / "s", "pa", "audit")
        one = installed_copy(self.tmp, src, "claude", edit=lambda f: (f / "x.md").write_text("x"))
        two = installed_copy(self.tmp, src, "codex", edit=lambda f: (f / "x.md").write_text("x"))
        three = installed_copy(self.tmp, src, "antigravity")
        rows = [dict(src, sha=CAT.roots_mod.tree_sha256(Path(src["path"])))]
        calls = {"sha": [], "sem": []}
        real_sha, real_sem = CAT.roots_mod.tree_sha256, CAT.roots_mod.tree_digest_semantic

        def count(kind, real):
            def inner(path, *rest):
                calls[kind].append(os.path.normcase(os.fspath(path)))
                return real(path, *rest)
            return inner

        with mock.patch.object(CAT.roots_mod, "tree_sha256", side_effect=count("sha", real_sha)), mock.patch.object(CAT.roots_mod, "tree_digest_semantic", side_effect=count("sem", real_sem)):
            cache = CAT.TreeCache(C_MARKERS)
            items = CAT._installed_items([{"harness": i["harness"], "plugin": i["plugin"], "skill": i["skill"], "path": i["path"]} for i in (one, two, three)],
                                         C_MARKERS, cache)
            O.find_pairs(rows, items, C_MARKERS, cache)
        for kind in ("sha", "sem"):
            counts = {x: calls[kind].count(x) for x in calls[kind]}
            self.assertLessEqual(max(counts.values()), 1, (kind, counts))

    def test_same_content_byte_equal_skips_semantic(self):
        src = write_skill(self.tmp / "s", "pa", "audit")
        inst = installed_copy(self.tmp, src)
        with mock.patch.object(CAT.roots_mod, "tree_digest_semantic", side_effect=AssertionError("semantic digest asked")):
            self.assertEqual(CAT.same_content(src, inst), (True, "byte"))
            same = CAT.same_content(dict(src, sha="s"), dict(inst, sha="s"))
        self.assertEqual(same, (True, "byte"))

    def test_cache_key_ignores_case_of_the_path(self):
        src = write_skill(self.tmp / "s", "pa", "audit")
        cache = CAT.TreeCache()
        with mock.patch.object(CAT.roots_mod, "tree_sha256", wraps=CAT.roots_mod.tree_sha256) as probe:
            first = cache.sha(Path(src["path"]))
            second = cache.sha(Path(src["path"].swapcase() if os.name == "nt" else src["path"]))
        self.assertEqual(first, second)
        self.assertEqual(probe.call_count, 1)


C_MARKERS = CAT.C.CLOUD_MARKERS


class DecisionTableTests(TmpCase):
    """One test per row of the decision table, in the order the table is applied."""

    def test_row1_same_key_same_hash_is_distribution_copy(self):
        src = write_skill(self.tmp / "s", "pa", "audit", refs=("r.md",))
        inst = installed_copy(self.tmp, src)
        pair = self.classify(src, inst)
        self.assertEqual((pair["label"], pair["suggestion"], pair["needs_review"]), ("distribution_copy", "keep", True))
        self.assertEqual((pair["a"], pair["b"]), ("pa:audit", "claude/pa:audit"))
        self.assertIn("compare: byte", pair["evidence"])

    def test_row1_semantic_copy_records_compare_semantic(self):
        src = write_skill(self.tmp / "s", "pa", "audit")

        def crlf(folder):
            (folder / "SKILL.md").write_bytes((folder / "SKILL.md").read_bytes().replace(b"\n", b"\r\n"))
        inst = installed_copy(self.tmp, src, edit=crlf)
        pair = self.classify(src, inst)
        self.assertEqual(pair["label"], "distribution_copy")
        self.assertIn("compare: semantic", pair["evidence"])

    def test_row1_uses_same_content_of_the_catalog(self):
        """The one comparison of FR3.2: patching it changes the answer, so the pairs cannot have a comparison of their own."""
        src = write_skill(self.tmp / "s", "pa", "audit")
        inst = installed_copy(self.tmp, src, edit=lambda f: (f / "extra.md").write_text("x"))
        with mock.patch.object(CAT, "same_content", return_value=(True, "semantic")) as probe:
            pair = self.classify(src, inst)
        probe.assert_called_once()
        self.assertEqual(pair["label"], "distribution_copy")
        self.assertIn("compare: semantic", pair["evidence"])

    def test_row2_same_key_other_hash_is_version_drift(self):
        src = write_skill(self.tmp / "s", "pa", "audit")
        inst = installed_copy(self.tmp, src, edit=lambda f: (f / "SKILL.md").write_text((f / "SKILL.md").read_text(encoding="utf-8") + "\nNew line.\n", encoding="utf-8"))
        pair = self.classify(src, inst)
        self.assertEqual((pair["label"], pair["suggestion"], pair["needs_review"]), ("version_drift", "sync", True))
        self.assertIn("compare: none", pair["evidence"])

    def test_row1_2_two_installed_copies(self):
        src = write_skill(self.tmp / "s", "pa", "audit")
        one, two = installed_copy(self.tmp, src, "claude"), installed_copy(self.tmp, src, "codex")
        self.assertEqual(self.classify(one, two)["label"], "distribution_copy")
        (Path(two["path"]) / "references" / "late.md").write_text("late")
        self.assertEqual(self.classify(one, two)["label"], "version_drift")

    def test_row1_2_an_unhashable_tree_proves_nothing(self):
        """A tree that cannot be hashed whole is neither equal nor different: not a copy, not a drift."""
        src = write_skill(self.tmp / "s", "pa", "audit")
        inst = dict(installed_copy(self.tmp, src), sha=None)
        pair = self.classify(src, inst)
        self.assertEqual((pair["label"], pair["suggestion"]), ("insufficient_evidence", "keep"))

    def test_copy_needs_hash(self):
        """FR4.3: when the comparison says the trees differ, the pair is never `distribution_copy`, however alike the texts are."""
        src = write_skill(self.tmp / "s", "pa", "audit")
        inst = installed_copy(self.tmp, src)
        with mock.patch.object(CAT, "same_content", return_value=(False, None)):
            pair = self.classify(src, inst)
        self.assertNotEqual(pair["label"], "distribution_copy")
        self.assertEqual(pair["label"], "version_drift")

    def test_same_name_diff_hash_never_copy(self):
        """Trọng tâm review 3: two skills with one name, near-identical descriptions and different trees are never a copy, whatever the plugin."""
        a = write_skill(self.tmp / "s", "pa", "review", refs=("one.md", "two.md"), scripts=("tool.py",))
        for plugin in ("pa", "pb"):
            other = write_skill(self.tmp / "t", plugin, "review", desc=a["desc"] + " Extra.", refs=("one.md", "two.md", "three.md"), scripts=("tool.py",), body="# Other\n\nDifferent.\n")
            pair = self.classify(a, other)
            self.assertNotEqual(pair["label"], "distribution_copy", plugin)
            self.assertIn(pair["label"], ("version_drift", "same_function"))

    def test_row3_not_clause_is_role_split(self):
        """A «Not …» that names the other skill, in either direction, by folder or by `name:`, any case: same name -> same_name_other_role, other name -> insufficient_evidence."""
        a = write_skill(self.tmp / "s", "pa", "cards", name="card-grader", desc=CARD + " Not for statement-tidy, which cleans csv files.")
        b = write_skill(self.tmp / "s", "pb", "tidy", name="statement-tidy", desc=CARD)
        pair = self.classify(a, b)
        self.assertEqual((pair["label"], pair["suggestion"], pair["needs_review"]), ("insufficient_evidence", "keep", True))
        self.assertEqual(self.classify(b, a)["label"], "insufficient_evidence", "both directions")
        c = write_skill(self.tmp / "s", "pc", "x", name="other", desc=CARD + " Không dùng cho TIDY-FOLDER.")
        d = write_skill(self.tmp / "s", "pd", "tidy-folder", name="something", desc=CARD)
        self.assertEqual(self.classify(c, d)["label"], "insufficient_evidence", "Vietnamese «Không», folder name, any case")
        files = ("a.md", "b.md")
        e = write_skill(self.tmp / "s", "pe", "review", desc=CARD + " Not for review of prose.", refs=files)
        f = write_skill(self.tmp / "s", "pf", "review", desc=CARD, refs=files)
        self.assertEqual(self.classify(e, f)["label"], "same_name_other_role", "the clause outranks the files that would make it same_function")

    def test_row3_name_before_the_clause_does_not_count(self):
        a = write_skill(self.tmp / "s", "pa", "cards", desc="Works with beta-tool exports. Not for csv files.")
        b = write_skill(self.tmp / "s", "pb", "beta-tool", desc=CARD)
        self.assertNotIn("loại trừ", " ".join(self.classify(a, b)["evidence"]))
        self.assertEqual(self.classify(a, b)["label"], "insufficient_evidence")  # row 6 here, not row 3: the evidence says why

    def test_row3_beats_same_function(self):
        files = ("a.md", "b.md", "c.md")
        a = write_skill(self.tmp / "s", "pa", "one", desc=CARD + " Not for two-skill.", refs=files)
        b = write_skill(self.tmp / "s", "pb", "two-skill", desc=CARD, refs=files)
        self.assertEqual(self.classify(a, b)["label"], "insufficient_evidence")

    def test_row4_same_function_needs_text_and_two_files(self):
        a = write_skill(self.tmp / "s", "pa", "grading", desc=CARD, refs=("rules.md", "codes.md"), scripts=("run.py",))
        b = write_skill(self.tmp / "s", "pb", "feedback", desc=CARD, refs=("rules.md", "extra.md"), scripts=("run.py",))
        pair = self.classify(a, b)
        self.assertEqual((pair["label"], pair["suggestion"], pair["needs_review"]), ("same_function", "merge", True))
        self.assertTrue(any("rules.md" in line and "run.py" in line for line in pair["evidence"]), pair["evidence"])
        one_file = write_skill(self.tmp / "s", "pc", "feedback", desc=CARD, refs=("rules.md",))
        self.assertEqual(self.classify(a, one_file)["label"], "insufficient_evidence", "one shared file is not enough")
        far = write_skill(self.tmp / "s", "pd", "feedback", desc=FILLERS[0], refs=("rules.md", "codes.md"), scripts=("run.py",))
        self.assertEqual(self.classify(a, far)["label"], "insufficient_evidence", "files without a like description are not enough")

    def test_row4_readme_and_init_do_not_count(self):
        a = write_skill(self.tmp / "s", "pa", "grading", desc=CARD, refs=("README.md", "rules.md"), scripts=("__init__.py",))
        b = write_skill(self.tmp / "s", "pb", "feedback", desc=CARD, refs=("readme.md", "rules.md"), scripts=("__init__.py",))
        self.assertEqual(self.classify(a, b)["label"], "insufficient_evidence")

    def test_row4_file_names_only_not_paths(self):
        """A file called the same in references/ of one and scripts/ of the other counts: the name is what is compared."""
        a = write_skill(self.tmp / "s", "pa", "grading", desc=CARD, refs=("rules.md", "codes.md"))
        b = write_skill(self.tmp / "s", "pb", "feedback", desc=CARD, refs=("rules.md",), scripts=("codes.md",))
        self.assertEqual(self.classify(a, b)["label"], "same_function")

    def test_text_only_is_insufficient(self):
        """FR4.2: identical descriptions and identical `##` headings, no shared files: never same_function or distribution_copy."""
        body = "# T\n\n## Crawl\n\ntext\n\n## Report\n\ntext\n"
        a = write_skill(self.tmp / "s", "pa", "grading", desc=CARD, body=body)
        b = write_skill(self.tmp / "s", "pb", "feedback", desc=CARD, body=body)
        pair = self.classify(a, b)
        self.assertEqual((pair["label"], pair["suggestion"]), ("insufficient_evidence", "keep"))
        self.assertAlmostEqual(O.similarity(a["desc"], b["desc"], *corpus(a, b)), 1.0)

    def test_row5_same_name_other_plugin(self):
        a = write_skill(self.tmp / "s", "pa", "notes", desc="Keeps accounting policy lists tidy.")
        b = write_skill(self.tmp / "s", "pb", "notes", desc="Drafts release notes from merged pull requests.")
        pair = self.classify(a, b)
        self.assertEqual((pair["label"], pair["suggestion"], pair["needs_review"]), ("same_name_other_role", "keep", True))
        self.assertTrue(any("notes" in line for line in pair["evidence"]))

    def test_row5_name_is_the_name_field_not_the_folder(self):
        a = write_skill(self.tmp / "s", "pa", "one", name="shared", desc="Keeps accounting policy lists tidy.")
        b = write_skill(self.tmp / "s", "pb", "two", name="Shared", desc="Drafts release notes from merged pull requests.")
        self.assertEqual(self.classify(a, b)["label"], "same_name_other_role")

    def test_row5_needs_another_plugin(self):
        """One plugin with two folders that carry one `name:` is a naming slip inside a plugin, not a role split between plugins: not nominated, and row 6 if asked."""
        a = write_skill(self.tmp / "s", "pa", "one", name="shared", desc="Keeps accounting policy lists tidy.")
        b = write_skill(self.tmp / "s", "pa", "two", name="shared", desc="Drafts release notes from merged pull requests.")
        self.assertEqual(O.candidates([a, b], []), [])
        self.assertEqual(self.classify(a, b)["label"], "insufficient_evidence")

    def test_row6_everything_else(self):
        a = write_skill(self.tmp / "s", "pa", "grading", desc=CARD, refs=("one.md",))
        b = write_skill(self.tmp / "s", "pb", "feedback", desc=CARD + " Also scores essays.", refs=("two.md",))
        pair = self.classify(a, b)
        self.assertEqual((pair["label"], pair["suggestion"], pair["needs_review"]), ("insufficient_evidence", "keep", True))
        self.assertTrue(pair["evidence"])

    def test_pair_shape_and_no_drop(self):
        a = write_skill(self.tmp / "s", "pa", "x", desc=CARD)
        b = write_skill(self.tmp / "s", "pb", "y", desc=CARD)
        pair = self.classify(a, b)
        self.assertEqual(set(pair), {"a", "b", "label", "evidence", "suggestion", "needs_review"})
        self.assertIn(pair["label"], LABELS)
        self.assertIn(pair["suggestion"], ("merge", "sync", "keep"))
        self.assertTrue(all(isinstance(line, str) for line in pair["evidence"]))


class FileNameTests(TmpCase):
    def test_names_come_from_references_and_scripts_only(self):
        s = write_skill(self.tmp, "pa", "x", refs=("A.md", "README.md"), scripts=("run.py", "__init__.py", "x.pyc"))
        (Path(s["path"]) / "assets").mkdir()
        (Path(s["path"]) / "assets" / "logo.png").write_bytes(b"x")
        self.assertEqual(O.file_names(Path(s["path"]), _engine.const.CLOUD_MARKERS), {"a.md", "run.py"})

    def test_secret_zone_and_cloud_names_are_never_listed(self):
        s = write_skill(self.tmp / ".secret", "pa", "x", refs=("a.md",))
        with mock.patch("os.scandir", side_effect=AssertionError("listed a forbidden folder")):
            self.assertEqual(O.file_names(Path(s["path"]), _engine.const.CLOUD_MARKERS), set())
        t = write_skill(self.tmp / "OneDrive - X", "pa", "x", refs=("a.md",))
        self.assertEqual(O.file_names(Path(t["path"]), _engine.const.CLOUD_MARKERS), set())

    def test_a_linked_references_folder_is_not_entered(self):
        s = write_skill(self.tmp / "s", "pa", "x", refs=("real.md",))
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "leak.md").write_text("x")
        shutil.rmtree(Path(s["path"]) / "references")
        link = Path(s["path"]) / "references"
        if not TI.make_junction(link, outside):
            self.skipTest("this machine cannot make a directory link; CI runs it")
        self.addCleanup(TI.drop_link, link)
        self.assertEqual(O.file_names(Path(s["path"]), _engine.const.CLOUD_MARKERS), set())


class CatalogIntegrationTests(TmpCase):
    def run_json(self, *argv, cwd=None):
        code, out, err = TC.run_catalog(*argv, "--json", cwd=cwd)
        return code, (json.loads(out) if out.strip().startswith("{") else None), err

    def test_without_the_flag_pairs_stay_null(self):
        code, report, err = self.run_json("--roots", str(FIXTURE))
        self.assertEqual(code, 0, err)
        self.assertIsNone(report["pairs"])

    def test_fixture_gets_pairs_with_every_label_rule(self):
        code, report, err = self.run_json("--roots", str(FIXTURE), "--overlap")
        self.assertEqual(code, 0, err)
        self.assertNotIn("not available", err)
        pairs = report["pairs"]
        self.assertEqual(report["totals"]["pairs"], len(pairs))
        self.assertTrue(pairs)
        self.assertTrue(all(p["needs_review"] is True and p["label"] in LABELS and p["suggestion"] in ("merge", "sync", "keep") and p["evidence"] for p in pairs))
        self.assertEqual(len({(p["a"], p["b"]) for p in pairs}), len(pairs), "one pair once")
        self.assertTrue(all(p["suggestion"] == SUGGEST[p["label"]] for p in pairs))
        by = {frozenset((p["a"], p["b"])): p["label"] for p in pairs}
        self.assertEqual(by[frozenset(("syn-finance:invoice-check", "syn-accounts:payable-invoice-audit"))], "same_function", "keys use the plugin name, not the root")
        self.assertEqual(by[frozenset(("syn-docs:review", "syn-devops:review"))], "same_name_other_role")
        self.assertEqual(by[frozenset(("syn-docs:sheet-tidy", "syn-finance:csv-cleaner"))], "insufficient_evidence", "alike in words only")
        labels = {p["label"] for p in pairs}
        self.assertIn("same_function", labels)
        self.assertIn("same_name_other_role", labels)
        self.assertNotIn("distribution_copy", labels, "no installed copy was asked for")

    def test_two_runs_give_the_same_pairs(self):
        first = self.run_json("--roots", str(FIXTURE), "--overlap")[1]["pairs"]
        second = self.run_json("--roots", str(FIXTURE), "--overlap")[1]["pairs"]
        self.assertEqual(first, second)

    def test_installed_copies_make_copy_and_drift_pairs(self):
        sources = self.tmp / "src"
        shutil.copytree(FIXTURE / "syn-docs", sources / "syn-docs")
        scanned_roots, skills, skipped = CAT._plain_roots([sources / "syn-docs"], ())
        by_name = {Path(s["path"]).name: s for s in skills}
        installed = []
        for skill_name, how in (("audit", "same"), ("planner", "drift"), ("review", "semantic")):
            src = by_name[skill_name]
            copy = self.tmp / "home" / skill_name
            shutil.copytree(src["path"], copy)
            if how == "drift":
                (copy / "references" / "calendar-template.md").write_text("changed\n")
            if how == "semantic":
                (copy / "SKILL.md").write_bytes((copy / "SKILL.md").read_bytes().replace(b"\n", b"\r\n"))
            installed.append({"harness": "claude", "plugin": src["plugin"], "skill": skill_name, "path": str(copy), "version": "0.1.0", "scope": None})
        report = CAT.build(scanned_roots, installed, True, "portable", (skills, skipped))
        labels = {(p["a"], p["label"], p["suggestion"]) for p in report["pairs"] if p["b"].startswith("claude/")}
        self.assertEqual(labels, {("syn-docs:audit", "distribution_copy", "keep"), ("syn-docs:planner", "version_drift", "sync"), ("syn-docs:review", "distribution_copy", "keep")})
        semantic = [p for p in report["pairs"] if p["a"] == "syn-docs:review" and p["b"].startswith("claude/")][0]
        self.assertIn("compare: semantic", semantic["evidence"])
        self.assertTrue(all(p["needs_review"] for p in report["pairs"]))

    def test_md_counts_copies_and_lists_the_rest(self):
        md = self.tmp / "CATALOG.md"
        code, out, err = TC.run_catalog("--roots", str(FIXTURE), "--overlap", "--md", str(md))
        self.assertEqual(code, 0, err)
        text = md.read_text(encoding="utf-8")
        section = text.split("## Cặp trùng", 1)[1]
        self.assertNotIn("Chưa tìm", section)
        self.assertIn("cần người duyệt", section)

    def test_the_run_changes_nothing_in_the_scanned_tree(self):
        def snapshot(base):
            return sorted((str(p.relative_to(base)), p.read_bytes()) for p in base.rglob("*") if p.is_file())
        before = snapshot(FIXTURE)
        self.run_json("--roots", str(FIXTURE), "--overlap")
        self.assertEqual(snapshot(FIXTURE), before)


if __name__ == "__main__":
    unittest.main()
