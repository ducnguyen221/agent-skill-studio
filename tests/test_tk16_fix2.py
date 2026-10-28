"""SPR-04 TK16 (review round 2): RF-A10 pairs vs installed copies that differ, RF-R1 evals link note, RF-S2 truncation flag, RF-A12 command line, RF-A11 root named like a cloud.

Run: python -X utf8 -m unittest tests.test_tk16_fix2 -v
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402
import test_catalog as TC  # noqa: E402
import test_tk16_fix1 as T1  # noqa: E402

R = _engine.roots
fs = _engine.fs


def _pair(a, b, label):
    return T1._pair(a, b, label)


class DifferVsPairsTests(TC.TmpCase):
    def drift_data(self):
        """9 skills differ in a harness, 31 version_drift pairs among their copies, 8 same-name pairs."""
        pairs = []
        for i in range(9):
            pairs.append(_pair("p:s%d" % i, "antigravity/p:s%d" % i, "version_drift"))
        for i in range(9):
            for other in ("claude", "codex"):
                pairs.append(_pair("antigravity/p:s%d" % i, "%s/p:s%d" % (other, i), "version_drift"))
        pairs += [_pair("claude/q:t%d" % i, "codex/q:t%d" % i, "version_drift") for i in range(4)]
        assert len(pairs) == 31
        pairs += [_pair("x%d:n" % i, "y%d:n" % i, "same_name_other_role") for i in range(8)]
        return pairs

    def test_differ_skills_counted_by_skill(self):
        """bắt-lỗi: RF-A10 9 skills with a differing copy and 31 drift pairs among them (+ 4 install-only skills) count as 13 skills, not 31 or 40."""
        module = TC.load_catalog_module()
        ids = {("p", "s%d" % i) for i in range(9)}
        self.assertEqual(module._differ_skills(ids, self.drift_data()), 13)
        self.assertEqual(module._differ_skills(set(), []), 0)

    def test_summary_and_section_name_the_real_work(self):
        """bắt-lỗi: RF-A10 9 differing skills + 31 drift pairs + 8 same-name pairs: the summary says 9 differ and 8 suspected pairs; the section lists the 8 pairs."""
        module = TC.load_catalog_module()
        report = module.build(R.opcos_roots(self.clean_tree() / "paths.json"), [], False, "portable")
        base = report["skills"][0]
        report["skills"] = [dict(base, name="s%d" % i, installed={"claude": T1._state(), "codex": T1._state(), "antigravity": T1._state("differ")}) for i in range(9)]
        report["pairs"] = self.drift_data()
        report["totals"]["installed_differ_skills"] = 9
        report["totals"]["pairs_to_review"] = 8
        lines = module.render_md(report).splitlines()
        self.assertIn("9 skill có bản cài lệch", lines[4])
        self.assertIn("8 cặp nghi trùng (cùng tên khác vai 8, trùng chức năng 0)", lines[4])
        start, end = lines.index("## Cần xem trước"), lines.index("## Skill theo repo")
        block = "\n".join(lines[start:end])
        self.assertLessEqual(end - start, 25)
        self.assertIn("**Cặp nghi trùng** (8):", block)
        self.assertEqual(block.count("same_name_other_role"), 8)
        self.assertNotIn("version_drift", block)

    def test_more_than_ten_pairs_point_to_the_section(self):
        module = TC.load_catalog_module()
        report = module.build(R.opcos_roots(self.clean_tree() / "paths.json"), [], False, "portable")
        report["pairs"] = [_pair("x%d:n" % i, "y%d:n" % i, "same_function") for i in range(11)]
        block = "\n".join(module._need_to_see(report))
        self.assertIn("11 cặp, xem mục Cặp trùng", block)

    def test_totals_have_the_new_keys(self):
        """bắt-lỗi: RF-A10, RF-S2 `installed_differ_skills` and `pairs_truncated` exist next to `pairs_to_review`."""
        module = TC.load_catalog_module()
        report = module.build(R.opcos_roots(self.clean_tree() / "paths.json"), [], True, "portable")
        self.assertEqual(report["totals"], {"skills": 2, "repos": 2, "roots_not_ok": 0, "pairs": 0, "pairs_to_review": 0,
                                            "installed_differ_skills": 0, "pairs_truncated": False})

    def test_build_counts_drift_once(self):
        """bắt-lỗi: RF-A10 through build: one source skill whose claude copy differs gives a drift pair, installed_differ_skills 1 and pairs_to_review 0."""
        import shutil
        module = TC.load_catalog_module()
        tree = self.clean_tree()
        src = tree / "plugins" / "p-two" / "skills" / "two"
        copy = self.tmp / "claude-copy" / "two"
        shutil.copytree(src, copy)
        (copy / "SKILL.md").write_text((copy / "SKILL.md").read_text(encoding="utf-8") + "\nextra line\n", encoding="utf-8")
        records = [{"harness": "claude", "plugin": "p-two", "skill": "two", "path": copy.as_posix(), "version": None, "scope": None}]
        report = module.build(R.opcos_roots(tree / "paths.json"), records, True, "portable")
        totals = report["totals"]
        self.assertEqual((totals["installed_differ_skills"], totals["pairs_to_review"]), (1, 0), report["pairs"])
        self.assertIn("1 skill có bản cài lệch", module.render_md(report).splitlines()[4])


class TruncationTests(TC.TmpCase):
    def test_truncated_flag_and_sentence(self):
        """bắt-lỗi: RF-S2 note: the ceiling reached gives totals.pairs_truncated true and one sentence in CATALOG.md."""
        import curator_overlap as O
        module = TC.load_catalog_module()
        plug = self.tmp / "plugs" / "p"
        for i in range(12):
            folder = plug / "skills" / ("s%d" % i)
            folder.mkdir(parents=True)
            desc = ("Reconciles credit card statements against receipts and assigns cost centres." if i % 2 else
                    "Translates legal contracts between several languages carefully for clients.")
            (folder / "SKILL.md").write_text(chr(10).join(["---", "name: s%d" % i, "description: " + desc, "---", "", "# T", "", "Body.", ""]), encoding="utf-8")
        (plug / ".claude-plugin").mkdir()
        (plug / ".claude-plugin" / "plugin.json").write_text('{"name": "p"}', encoding="utf-8")
        with mock.patch.object(O, "OVERLAP_MAX_PAIRS", 5):
            report = module.build([R._new_root(plug, "plugin", "roots")], [], True, "portable", None, (), [])
            self.assertTrue(report["totals"]["pairs_truncated"])
            self.assertIn("Danh sách cặp đã cắt ở 5.", module.render_md(report))
        report["totals"]["pairs_truncated"] = False
        self.assertNotIn("đã cắt", module.render_md(report))

    def test_sentence_shows_twenty_thousand(self):
        module = TC.load_catalog_module()
        report = module.build(R.opcos_roots(self.clean_tree() / "paths.json"), [], True, "portable")
        report["totals"]["pairs_truncated"] = True
        self.assertIn("Danh sách cặp đã cắt ở 20 000.", module.render_md(report))


class EvalsLinkNoteTests(TC.TmpCase):
    def test_evals_link_is_noted(self):
        """bắt-lỗi: RF-R1 an evals/catalog.json behind a link is not read and one note says so."""
        module = TC.load_catalog_module()
        plug = self.tmp / "plug"
        (plug / "evals").mkdir(parents=True)
        (plug / "evals" / "catalog.json").write_text('{"schema_version": "1", "skills": []}', encoding="utf-8")
        notes: list = []
        with mock.patch.object(fs, "link_in_chain", return_value=True):
            self.assertEqual(module._evals_entries(plug, {}, notes), {})
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("evals/catalog.json", notes[0])
        self.assertIn("link", notes[0])


class CommandLineTests(TC.TmpCase):
    def args(self, **kw):
        module = TC.load_catalog_module()
        args = module.build_parser().parse_args([])
        for key, value in kw.items():
            setattr(args, key, value)
        return module, args

    def test_command_text_has_json(self):
        """bắt-lỗi: RF-A12 the line says --json when it was given."""
        module, args = self.args(roots_from="opcos", json=True, overlap=True)
        self.assertIn("--overlap --json", module._command_text(args))

    def test_home_path_by_real_path(self):
        """bắt-lỗi: RF-A12 a spelling of the home folder that is not the expanduser one (8.3 name, link) still shows as ~."""
        module = TC.load_catalog_module()
        real = os.path.realpath

        def fake(path, *a, **k):
            return real(str(path).replace("SHORT~1", "LongName"))

        with mock.patch.object(os.path, "expanduser", lambda p: str(self.tmp / "LongName") if p == "~" else p), \
                mock.patch.object(os.path, "realpath", fake):
            self.assertEqual(module.home_path(str(self.tmp / "SHORT~1" / "a" / "b")), "~/a/b")
            self.assertEqual(module.home_path(str(self.tmp / "LongName" / "a")), "~/a")
            self.assertEqual(module.home_path(str(self.tmp / "Other" / "a")), (self.tmp / "Other" / "a").as_posix())

    @unittest.skipUnless(sys.platform == "win32", "8.3 names exist on Windows only")
    def test_home_path_real_8dot3(self):
        module = TC.load_catalog_module()
        home = os.path.expanduser("~")
        buf = ctypes.create_unicode_buffer(1024)
        if not ctypes.windll.kernel32.GetShortPathNameW(home, buf, 1024) or buf.value.lower() == home.lower():
            self.skipTest("no 8.3 name for the home folder")
        self.assertEqual(module.home_path(buf.value + "\\AppData\\x\\y"), "~/AppData/x/y")


class CloudRootTests(TC.TmpCase):
    def test_root_named_like_cloud_is_error_cloud(self):
        """bắt-lỗi: RF-A11 a --roots root whose own name holds a cloud marker is an error with reason `cloud`, not `cloud-name`."""
        root = self.tmp / "OneDrive-backup"
        TC.make_skill(root / "alpha")
        TC.make_skill(self.tmp / "ok" / "beta")
        code, out, err = TC.run_catalog("--roots", "%s;%s" % (root, self.tmp / "ok"), "--json")
        roots = {Path(r["path"]).name: r for r in json.loads(out)["roots"]} if out.strip() else {}
        self.assertEqual(code, 1, out + err)
        self.assertEqual((roots["OneDrive-backup"]["status"], roots["OneDrive-backup"]["reasons"]), ("error", ["cloud"]), roots)


if __name__ == "__main__":
    unittest.main()
