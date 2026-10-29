"""SPR-04 TK5 (FR1, FR2.2, SC2, SC3): scan roots from paths.json and plugin manifests, the tree hash, and `doctor --roots-from opcos`.

Run: python -X utf8 -m unittest tests.test_roots -v
"""
from __future__ import annotations

import contextlib
import hashlib
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
import _engine  # noqa: E402
import importlib  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "opcos-tree"
R = importlib.import_module("studio_roots")  # the engine put its folder on sys.path when _engine loaded it
C = _engine.const
studio = _engine.engine
doctor = _engine.doctor

SKILL = "---\nname: %s\ndescription: Checks a toy example. Use when testing the roots.\n---\n\n# Title\n\nShort body.\n"


def make_skill(folder: Path, name: str = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_bytes((SKILL % (name or folder.name)).encode("utf-8"))
    return folder


def make_plugin(parent: Path, name: str, manifest=None) -> Path:
    """A plugin folder with .claude-plugin/plugin.json: `manifest` is a dict (written as JSON), a str or bytes (written as given) or None (no key `skills`)."""
    folder = parent / name
    (folder / ".claude-plugin").mkdir(parents=True)
    if manifest is None:
        manifest = {"name": name}
    data = manifest if isinstance(manifest, (str, bytes)) else json.dumps(manifest)
    (folder / ".claude-plugin" / "plugin.json").write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return folder


def make_link(test, link: Path, target: Path) -> None:
    """A directory symlink, or a junction on Windows without the symlink privilege; skips the test when neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        import subprocess
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if link.exists():
            return
    test.skipTest("cannot create a symlink or junction here")


def run_doctor(*argv, cwd=None):
    """Run `studio.py doctor ...` in-process (cwd switched when given); returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    before = os.getcwd()
    try:
        if cwd is not None:
            os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = studio.main(["doctor", *argv])
    finally:
        os.chdir(before)
    return code, out.getvalue(), err.getvalue()


class TmpCase(unittest.TestCase):
    def setUp(self):
        _engine.clear_caches()
        self.addCleanup(_engine.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-roots-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)


class FindPathsJsonTests(TmpCase):
    def test_paths_json_lookup_env_then_up(self):
        """bắt-lỗi (red: no studio_roots module): FR1.1 OPCOS_ROOT/paths.json first, then up to 6 levels from the start folder, never further."""
        data = self.tmp / "data"
        data.mkdir()
        (data / "paths.json").write_text('{"areas": []}', encoding="utf-8")
        elsewhere = self.tmp / "other"
        elsewhere.mkdir()
        self.assertEqual(R.find_paths_json(elsewhere, {"OPCOS_ROOT": str(data)}), data / "paths.json")
        deep = elsewhere
        for name in "abcdef":  # six levels below `other`
            deep = deep / name
        deep.mkdir(parents=True)
        (elsewhere / "paths.json").write_text('{"areas": []}', encoding="utf-8")
        self.assertEqual(R.find_paths_json(deep, {}), elsewhere / "paths.json", "six levels up is still searched")
        deeper = deep / "g"
        deeper.mkdir()
        self.assertIsNone(R.find_paths_json(deeper, {}), "the seventh level up is not searched")
        self.assertEqual(R.find_paths_json(deeper, {"OPCOS_ROOT": str(data)}), data / "paths.json")
        self.assertEqual(R.find_paths_json(deep, {"OPCOS_ROOT": str(self.tmp / "nowhere")}), elsewhere / "paths.json",
                         "an OPCOS_ROOT without paths.json falls back to the walk up")
        self.assertEqual(R.find_paths_json(FIX / "plugins" / "p-default" / "skills" / "a", {}), FIX / "paths.json")

    def test_paths_json_other_env_names_are_not_read(self):
        """bắt-lỗi: FR1.1 only OPCOS_ROOT is read; OPCOS_REPO_ROOT and the other area variables are ignored."""
        other = self.tmp / "other"
        other.mkdir()
        (other / "paths.json").write_text('{"areas": []}', encoding="utf-8")
        start = self.tmp / "start"
        start.mkdir()
        env = {"OPCOS_REPO_ROOT": str(other), "OPCOS_BRAIN_PATH": str(other), "OPCOS_WORKSPACES": str(other)}
        self.assertIsNone(R.find_paths_json(start, env))

    def test_paths_json_too_big_is_refused_with_a_reason(self):
        """bắt-lỗi: FR1.1 a paths.json above 256 KB is refused unread, with reason limit."""
        (self.tmp / "paths.json").write_bytes(b" " * (C.PATHS_JSON_MAX + 1))
        with self.assertRaises(R.RootError) as caught:
            R.find_paths_json(self.tmp, {})
        self.assertEqual(caught.exception.reason, "limit")

    def test_paths_json_that_is_a_folder_is_refused(self):
        """bắt-lỗi: FR1.1 a paths.json that is not a regular file is refused (unreadable), not opened."""
        (self.tmp / "paths.json").mkdir()
        with self.assertRaises(R.RootError) as caught:
            R.find_paths_json(self.tmp, {})
        self.assertEqual(caught.exception.reason, "unreadable")

    def test_paths_json_link_is_refused_before_opening(self):
        """bắt-lỗi: FR1.1 a paths.json that is a link is refused with reason link, and is never opened."""
        (self.tmp / "real.json").write_text('{"areas": []}', encoding="utf-8")
        link = self.tmp / "paths.json"
        with mock.patch.object(_engine.fs, "is_link", side_effect=lambda p: Path(p) == link):
            (self.tmp / "paths.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(_engine.fs, "open_nofollow_read", side_effect=AssertionError("opened")):
                with self.assertRaises(R.RootError) as caught:
                    R.find_paths_json(self.tmp, {})
        self.assertEqual(caught.exception.reason, "link")

    def test_paths_json_in_cloud_or_secret_zone_is_refused_unread(self):
        """bắt-lỗi: FR1.1 OPCOS_ROOT inside a cloud-named or .secret folder is refused by name (cloud / secret-zone), nothing is opened."""
        for name, reason in (("OneDrive - X", "cloud"), (".secret", "secret-zone")):
            with self.subTest(name):
                folder = self.tmp / name
                folder.mkdir()
                (folder / "paths.json").write_text('{"areas": []}', encoding="utf-8")
                with mock.patch.object(_engine.fs, "open_nofollow_read", side_effect=AssertionError("opened")):
                    with self.assertRaises(R.RootError) as caught:
                        R.find_paths_json(self.tmp, {"OPCOS_ROOT": str(folder)})
                self.assertEqual(caught.exception.reason, reason)

    def test_walk_up_skips_a_start_folder_in_a_cloud_zone(self):
        """bắt-lỗi: FR1.1 a start folder whose path names a cloud marker is not searched (nothing under it is touched)."""
        folder = self.tmp / "SharePoint share" / "work"
        folder.mkdir(parents=True)
        (self.tmp / "SharePoint share" / "paths.json").write_text('{"areas": []}', encoding="utf-8")
        self.assertIsNone(R.find_paths_json(folder, {}))


class OpcosRootsTests(TmpCase):
    def write_paths(self, areas, name="paths.json") -> Path:
        path = self.tmp / name
        path.write_text(json.dumps({"version": 1, "areas": areas}), encoding="utf-8")
        return path

    def test_fixture_roots(self):
        """bắt-lỗi: FR1.1 opcos-plugin -> one plugin root, plugins -> plugin-parent, system/plugins -> plugin-parent with area system-plugins."""
        roots = R.opcos_roots(FIX / "paths.json")
        self.assertEqual([(r["kind"], r["area"], r["status"]) for r in roots],
                         [("plugin", "opcos-plugin", "ok"), ("plugin-parent", "plugins", "ok"), ("plugin-parent", "system-plugins", "ok")])
        self.assertEqual([Path(r["path"]) for r in roots], [FIX / "system" / "opcos-plugin", FIX / "plugins", FIX / "system" / "plugins"])
        for root in roots:
            self.assertEqual(set(root), {"path", "kind", "area", "status", "reasons", "skipped_by_rule"})
            self.assertEqual((root["reasons"], root["skipped_by_rule"]), ([], []))
        self.assertNotIn("\\", roots[0]["path"], "paths are written with /")

    def test_system_plugins_optional(self):
        """bắt-lỗi: FR1.1 system/plugins is a root only when include_system_plugins and the folder exists (CQ2)."""
        self.assertEqual([r["area"] for r in R.opcos_roots(FIX / "paths.json", include_system_plugins=False)], ["opcos-plugin", "plugins"])
        (self.tmp / "p").mkdir()
        (self.tmp / "o").mkdir()
        path = self.write_paths([{"id": "system", "rel_path": "."}, {"id": "opcos-plugin", "rel_path": "o"}, {"id": "plugins", "rel_path": "p"}])
        self.assertEqual([r["area"] for r in R.opcos_roots(path)], ["opcos-plugin", "plugins"], "no system/plugins folder: no root, no error")
        (self.tmp / "plugins").mkdir()
        self.assertEqual([r["area"] for r in R.opcos_roots(path)], ["opcos-plugin", "plugins", "system-plugins"])
        path = self.write_paths([{"id": "opcos-plugin", "rel_path": "o"}, {"id": "plugins", "rel_path": "p"}])
        self.assertEqual([r["area"] for r in R.opcos_roots(path)], ["opcos-plugin", "plugins"], "no system area: no system root")

    def test_rel_path_refused(self):
        """bắt-lỗi: FR1.1 an absolute rel_path, one starting with ~, one with .. or with a drive/stream colon is refused: the root is an error."""
        for bad in (str(self.tmp), "~/x", "/etc", "../up", "a/../../up", "C:evil", "a:stream", "", None, 5):
            with self.subTest(repr(bad)):
                path = self.write_paths([{"id": "opcos-plugin", "rel_path": bad}, {"id": "plugins", "rel_path": "plugins"}])
                root = R.opcos_roots(path, include_system_plugins=False)[0]
                self.assertEqual((root["status"], root["reasons"]), ("error", ["rel-path-refused"]))

    def test_missing_area_and_missing_folder_are_errors(self):
        """bắt-lỗi: FR1.3 a missing area and an area whose folder does not exist are `error` roots with a reason; the others stay usable."""
        (self.tmp / "plugins").mkdir()
        path = self.write_paths([{"id": "plugins", "rel_path": "plugins"}, {"id": "opcos-plugin", "rel_path": "gone"}])
        roots = R.opcos_roots(path, include_system_plugins=False)
        self.assertEqual((roots[0]["area"], roots[0]["status"], roots[0]["reasons"]), ("opcos-plugin", "error", ["not-found"]))
        self.assertEqual((roots[1]["area"], roots[1]["status"]), ("plugins", "ok"))
        roots = R.opcos_roots(self.write_paths([{"id": "plugins", "rel_path": "plugins"}]), include_system_plugins=False)
        self.assertEqual((roots[0]["area"], roots[0]["status"], roots[0]["reasons"]), ("opcos-plugin", "error", ["area-missing"]))

    def test_area_variables_are_not_used(self):
        """bắt-lỗi: FR1.1 the `env` of an area (OPCOS_REPO_ROOT...) is never read: the root comes from rel_path only."""
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        with mock.patch.dict(os.environ, {"OPCOS_REPO_ROOT": str(elsewhere), "OPCOS_ROOT": str(elsewhere)}):
            roots = R.opcos_roots(FIX / "paths.json")
        self.assertEqual(Path(roots[1]["path"]), FIX / "plugins")

    def test_root_that_is_too_broad_or_in_a_zone_is_an_error(self):
        """bắt-lỗi: FR1.1 every root goes through root_too_broad and the zone check: the home folder, a cloud-named or a .secret folder are not roots."""
        path = self.write_paths([{"id": "opcos-plugin", "rel_path": "OneDrive x"}, {"id": "plugins", "rel_path": ".secret"}])
        roots = R.opcos_roots(path, include_system_plugins=False)
        self.assertEqual([(r["status"], r["reasons"]) for r in roots], [("error", ["cloud"]), ("error", ["secret-zone"])])
        with mock.patch.object(_engine.fs, "root_too_broad", return_value=True):
            (self.tmp / "p").mkdir()
            root = R.opcos_roots(self.write_paths([{"id": "plugins", "rel_path": "p"}]), include_system_plugins=False)[1]
        self.assertEqual((root["status"], root["reasons"]), ("error", ["too-broad"]))

    def test_paths_json_bad_content_raises(self):
        """bắt-lỗi: FR1.1 a paths.json that is not JSON, not an object or without an areas list raises RootError (unreadable)."""
        for text in ("{", "[]", '{"areas": 3}', "\xef\xbf\xbd"):
            with self.subTest(text):
                path = self.tmp / "paths.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(R.RootError) as caught:
                    R.opcos_roots(path)
                self.assertEqual(caught.exception.reason, "unreadable")
        path.write_text("[" * 20000, encoding="utf-8")
        with self.assertRaises(R.RootError):
            R.opcos_roots(path)

    def test_root_that_is_a_link_is_an_error(self):
        """bắt-lỗi: FR1.1 a root that is a symlink or junction is not followed: error, reason link."""
        target = self.tmp / "target"
        target.mkdir()
        link = self.tmp / "plugins"
        make_link(self, link, target)
        root = R.opcos_roots(self.write_paths([{"id": "plugins", "rel_path": "plugins"}]), include_system_plugins=False)[1]
        self.assertEqual((root["status"], root["reasons"]), ("error", ["link"]))

    def test_link_in_the_middle_of_rel_path_is_an_error(self):
        """bắt-lỗi: RF-5.1 a junction/symlink between paths.json and the root (sysj/opcos-plugin, sysj a link out of the tree) makes the root an error; nothing is read through it."""
        base = self.tmp / "tree"
        outside = self.tmp / "outside"
        outside.mkdir()
        make_skill(make_plugin(outside, "opcos-plugin") / "skills" / "x")  # a plugin out of the tree
        base.mkdir()
        make_link(self, base / "sysj", outside)
        path = self.write_paths([{"id": "opcos-plugin", "rel_path": "sysj/opcos-plugin"}, {"id": "plugins", "rel_path": "sysj"}], name="tree/paths.json")
        seen = []
        real = os.scandir
        with mock.patch("os.scandir", side_effect=lambda p, *a, **k: (seen.append(os.fspath(p)), real(p, *a, **k))[1]):
            roots = R.opcos_roots(path, include_system_plugins=False)
            R.collect_skills(roots)
        self.assertEqual([(r["status"], r["reasons"]) for r in roots], [("error", ["link"]), ("error", ["link"])])
        self.assertFalse([p for p in seen if "outside" in p], seen)

    def test_link_in_the_middle_of_rel_path_with_patched_is_link(self):
        """bắt-lỗi: RF-5.1 the same on a machine that cannot create links: is_link says the middle folder is a link."""
        (self.tmp / "sysj" / "opcos-plugin").mkdir(parents=True)
        path = self.write_paths([{"id": "opcos-plugin", "rel_path": "sysj/opcos-plugin"}])
        real = _engine.fs.is_link
        with mock.patch.object(_engine.fs, "is_link", side_effect=lambda p: Path(p).name == "sysj" or real(p)):
            root = R.opcos_roots(path, include_system_plugins=False)[0]
        self.assertEqual((root["status"], root["reasons"]), ("error", ["link"]))


class CollectSkillsTests(TmpCase):
    def collect(self, **kw):
        roots = R.opcos_roots(FIX / "paths.json", **kw)
        skills, skipped = R.collect_skills(roots)
        return roots, skills, skipped

    def names(self, skills):
        return sorted(s["path"].name if s["path"].name != "p-root" else "root" for s in skills)

    def test_fixture_has_exactly_five_skills(self):
        """bắt-lỗi: FR1.2 the fixture gives a, b, root, h, c and nothing from tests/, examples/, .claude/skills, vendor, escape."""
        _, skills, _ = self.collect()
        self.assertEqual(self.names(skills), ["a", "b", "c", "h", "root"])
        posix = ["/" + s["path"].relative_to(FIX).as_posix() + "/" for s in skills]
        for part in ("/tests/", "/examples/", "/.claude/", "vendor-x", "p-escape"):
            self.assertFalse([p for p in posix if part in p], part)
        by = {s["path"].name: s for s in skills}
        self.assertEqual((by["a"]["plugin"], by["a"]["repo"]), ("p-default", "p-default"))
        self.assertEqual((by["c"]["plugin"], by["c"]["repo"]), ("k", "k"))
        self.assertEqual(by["p-root"]["path"], FIX / "plugins" / "p-root")

    def test_manifest_default_skills(self):
        """bắt-lỗi: FR1.2 no `skills` key means skills/."""
        plugin = make_plugin(self.tmp, "p")
        make_skill(plugin / "skills" / "one")
        make_skill(plugin / "other" / "two")
        dirs, skipped = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
        self.assertEqual([d.name for d in dirs], ["one"])
        self.assertEqual(skipped, [])

    def test_manifest_default_missing_folder_is_quiet(self):
        """bắt-lỗi: FR1.2 a plugin without skills/ and without a `skills` key has no skills and no complaint; a declared folder that is missing is reported."""
        plugin = make_plugin(self.tmp, "p")
        self.assertEqual(R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS), ([], []))
        declared = make_plugin(self.tmp, "q", {"name": "q", "skills": "./nope/"})
        dirs, skipped = R.plugin_skill_dirs(declared, C.CLOUD_MARKERS)
        self.assertEqual((dirs, [s["reason"] for s in skipped]), ([], ["unreadable"]))

    def test_manifest_agents_dir(self):
        """bắt-lỗi: FR1.2 a declared ./.agents/skills/ is scanned although .agents/skills is otherwise excluded; .claude/skills stays out."""
        _, skills, _ = self.collect()
        b = [s for s in skills if s["path"].name == "b"]
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["path"], FIX / "plugins" / "p-agents" / ".agents" / "skills" / "b")

    def test_manifest_root_dot(self):
        """bắt-lỗi: FR1.2 `./` means the plugin folder itself: only its SKILL.md counts, nothing under examples/ or tests/."""
        plugin = make_plugin(self.tmp, "p", {"name": "p", "skills": "./"})
        make_skill(plugin / "examples" / "e")
        make_skill(plugin / "skills" / "s")
        self.assertEqual(R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS), ([], []), "no SKILL.md at the plugin root: no skill")
        (plugin / "SKILL.md").write_bytes((SKILL % "p").encode("utf-8"))
        dirs, _ = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
        self.assertEqual(dirs, [plugin])
        for n, spelling in enumerate((".", "./", ".\\")):
            plugin2 = make_plugin(self.tmp, "q%d" % n, {"name": "x", "skills": spelling})
            (plugin2 / "SKILL.md").write_bytes((SKILL % "x").encode("utf-8"))
            self.assertEqual(R.plugin_skill_dirs(plugin2, C.CLOUD_MARKERS)[0], [plugin2], spelling)

    def test_manifest_skills_as_list_and_nested_dirs(self):
        """bắt-lỗi: FR1.2 `skills` may be a list of folders; every folder is scanned and a skill is listed once."""
        plugin = make_plugin(self.tmp, "p", {"name": "p", "skills": ["./a/", "b", "./a"]})
        make_skill(plugin / "a" / "one")
        make_skill(plugin / "b" / "two")
        dirs, skipped = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
        self.assertEqual(sorted(d.name for d in dirs), ["one", "two"])
        self.assertEqual(skipped, [])

    def test_nested_skills(self):
        """bắt-lỗi: FR1.2 a skill that sits two folders down (skills/g/h) counts, and so do skills inside a skill (05-forensics/05a-reading)."""
        _, skills, _ = self.collect()
        self.assertIn("h", self.names(skills))
        plugin = make_plugin(self.tmp, "p")
        make_skill(plugin / "skills" / "outer")
        make_skill(plugin / "skills" / "outer" / "inner-a")
        make_skill(plugin / "skills" / "outer" / "inner-a" / "deep")
        make_skill(plugin / "skills" / "outer" / "assets" / "template")
        make_skill(plugin / "skills" / "outer" / "tests" / "fixtures" / "bad")
        make_skill(plugin / "skills" / "outer" / "references" / "example")
        make_skill(plugin / "skills" / "outer" / ".hidden" / "h")
        make_skill(plugin / "skills" / "outer" / "superseded-v1" / "old")
        (plugin / "skills" / "outer" / "notes").mkdir()
        dirs, _ = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
        self.assertEqual(sorted(d.relative_to(plugin / "skills").as_posix() for d in dirs),
                         ["outer", "outer/inner-a", "outer/inner-a/deep"])

    def test_vendor_skipped(self):
        """bắt-lỗi: FR1.1/FR2.2 plugins/vendor-* is skipped by rule (listed, root still ok)."""
        roots, skills, skipped = self.collect()
        plugins = roots[1]
        self.assertIn({"path": (FIX / "plugins" / "vendor-x").as_posix(), "reason": "vendor"}, plugins["skipped_by_rule"])
        self.assertIn({"path": (FIX / "plugins" / "vendor-x").as_posix(), "reason": "vendor"}, skipped)
        self.assertFalse([s for s in skills if "vendor-x" in s["path"].as_posix()])

    def test_manifest_escape_in_the_fixture(self):
        """bắt-lỗi: FR1.2/FR2.2 p-escape (skills: ../../) lists nothing, is reported as manifest-escape and makes the root partial."""
        roots, skills, skipped = self.collect()
        plugins = roots[1]
        self.assertEqual((plugins["status"], plugins["reasons"]), ("partial", ["manifest-escape"]))
        self.assertEqual([s for s in skipped if s["reason"] == "manifest-escape"][0]["path"],
                         (FIX / "plugins" / "p-escape" / ".claude-plugin" / "plugin.json").as_posix())
        self.assertFalse([s for s in skills if "p-escape" in s["path"].as_posix()])
        self.assertEqual((roots[0]["status"], roots[2]["status"]), ("ok", "ok"))
        self.assertEqual(plugins["skipped_by_rule"], [{"path": (FIX / "plugins" / "vendor-x").as_posix(), "reason": "vendor"}])

    def scan_log(self):
        """Record every folder the scan lists, so a test can say what was NOT read."""
        seen = []
        real = os.scandir

        def scandir(path="."):
            seen.append(os.path.normcase(os.path.abspath(os.fspath(path))))
            return real(path)

        return seen, mock.patch("os.scandir", scandir)

    def test_manifest_escape_absolute_and_dotdot(self):
        """bắt-lỗi: Trọng tâm 1: an absolute path, a ~ path, a .. path and "../../.secret" in `skills` are manifest-escape; nothing outside the plugin is listed."""
        outside = self.tmp / "outside-secret"
        make_skill(outside / "loot")
        bads = (str(outside), str(outside).replace("\\", "/"), "~/x", "../outside-secret", "a/../../outside-secret", "../../.secret",
                "skills/../../outside-secret", "C:\\x", "x:stream", "\\\\host\\share", "", "a\x00b", "CON", "name.", "SKILL~1")
        for index, bad in enumerate(bads):  # one folder per case: the first two values are equal on POSIX
            with self.subTest(bad):
                plugin = make_plugin(self.tmp, "p%d" % index, {"name": "p", "skills": bad})
                seen, patch = self.scan_log()
                with patch:
                    dirs, skipped = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
                self.assertEqual(dirs, [])
                self.assertEqual([s["reason"] for s in skipped], ["manifest-escape"], skipped)
                self.assertFalse([p for p in seen if "outside-secret" in p or ".secret" in p], seen)

    def test_manifest_escape_in_a_list_keeps_the_good_entries(self):
        """bắt-lỗi: Trọng tâm 1: a bad entry among good ones is dropped alone."""
        outside = self.tmp / "outside-secret"
        make_skill(outside / "loot")
        plugin = make_plugin(self.tmp, "p", {"name": "p", "skills": ["./skills/", str(outside), 7, None, {"a": 1}, ["x"]]})
        make_skill(plugin / "skills" / "ok")
        dirs, skipped = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
        self.assertEqual([d.name for d in dirs], ["ok"])
        self.assertEqual([s["reason"] for s in skipped], ["manifest-escape"] * 5)

    def test_manifest_escape_through_a_link(self):
        """bắt-lỗi: Trọng tâm 1: a declared folder that is, or passes through, a link is manifest-escape and is not listed."""
        outside = self.tmp / "outside-secret"
        make_skill(outside / "loot")
        plugin = make_plugin(self.tmp, "p", {"name": "p", "skills": ["./door/", "./real/door/"]})
        (plugin / "real").mkdir()
        make_link(self, plugin / "door", outside)
        make_link(self, plugin / "real" / "door", outside)
        seen, patch = self.scan_log()
        with patch:
            dirs, skipped = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
        self.assertEqual((dirs, [s["reason"] for s in skipped]), ([], ["manifest-escape", "manifest-escape"]))
        self.assertFalse([p for p in seen if "outside-secret" in p], seen)

    def test_manifest_escape_link_without_a_real_link(self):
        """bắt-lỗi: Trọng tâm 1 (runs where no symlink can be made): is_link True for a declared folder gives manifest-escape and the folder is not scanned."""
        plugin = make_plugin(self.tmp, "p", {"name": "p", "skills": "./door/"})
        make_skill(plugin / "door" / "loot")
        door = plugin / "door"
        with mock.patch.object(_engine.fs, "is_link", side_effect=lambda p: Path(p) == door):
            with mock.patch.object(doctor, "iter_skill_dirs", side_effect=AssertionError("scanned")):
                dirs, skipped = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
        self.assertEqual((dirs, [s["reason"] for s in skipped]), ([], ["manifest-escape"]))

    def test_manifest_over_the_limits(self):
        """bắt-lỗi: Trọng tâm 1: a manifest above 64 KB is not read (limit); a list above 64 entries is cut at 64 with one limit line; 10 000 entries cost nothing."""
        big = make_plugin(self.tmp, "big", b" " * (C.MANIFEST_MAX + 1))
        make_skill(big / "skills" / "s")
        with mock.patch.object(_engine.fs, "open_nofollow_read", side_effect=AssertionError("opened")):
            self.assertEqual([s["reason"] for s in R.plugin_skill_dirs(big, C.CLOUD_MARKERS)[1]], ["limit"])
            self.assertEqual(R.plugin_skill_dirs(big, C.CLOUD_MARKERS)[0], [])
        many = make_plugin(self.tmp, "many", {"name": "m", "skills": ["./s%d/" % n for n in range(65)]})
        make_skill(many / "s0" / "first")
        make_skill(many / "s64" / "last")
        dirs, skipped = R.plugin_skill_dirs(many, C.CLOUD_MARKERS)
        self.assertEqual([d.name for d in dirs], ["first"], "entry 65 is not looked at")
        self.assertEqual([s["reason"] for s in skipped].count("limit"), 1)
        huge = make_plugin(self.tmp, "huge", {"name": "h", "skills": ["../x"] * 10000})
        dirs, skipped = R.plugin_skill_dirs(huge, C.CLOUD_MARKERS)
        self.assertEqual(dirs, [])
        self.assertLessEqual(len(skipped), C.MANIFEST_SKILLS_MAX + 1)

    def test_manifest_bad_json(self):
        """bắt-lỗi: FR1.2/FR2.2 a manifest that is not JSON, not an object, or has `skills` of another type is `unreadable`, not an exception."""
        for n, text in enumerate(("{", "[]", "null", '{"skills": 3}', '{"skills": true}', b"\xff\xfe", "[" * 30000)):
            with self.subTest(n):
                plugin = make_plugin(self.tmp, "p%d" % n, text)
                make_skill(plugin / "skills" / "s")
                dirs, skipped = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
                self.assertEqual((dirs, [s["reason"] for s in skipped]), ([], ["unreadable"]))

    def test_manifest_zone_names(self):
        """bắt-lỗi: FR1.2 a declared folder named like a cloud or secret zone is not entered: cloud-name (by rule) and secret-zone."""
        plugin = make_plugin(self.tmp, "p", {"name": "p", "skills": ["./OneDrive x/", "./.secret/"]})
        make_skill(plugin / "OneDrive x" / "s")
        make_skill(plugin / ".secret" / "s")
        with mock.patch.object(doctor, "iter_skill_dirs", side_effect=AssertionError("scanned")):
            dirs, skipped = R.plugin_skill_dirs(plugin, C.CLOUD_MARKERS)
        self.assertEqual((dirs, [s["reason"] for s in skipped]), ([], ["cloud-name", "secret-zone"]))

    def test_plugin_parent_rules(self):
        """bắt-lỗi: FR2.2 plugin-parent children: a README file and a folder without a manifest are ignored; a cloud-named child is cloud-name by rule; a link child is link -> partial."""
        parent = self.tmp / "plugins"
        parent.mkdir()
        (parent / "README.md").write_text("x", encoding="utf-8")
        (parent / "not-a-plugin").mkdir()
        (parent / ".git").mkdir()
        (parent / ".worktrees").mkdir()
        good = make_plugin(parent, "good")
        make_skill(good / "skills" / "s")
        cloud = make_plugin(parent, "My OneDrive plugin")
        make_skill(cloud / "skills" / "c")
        root = {"path": parent.as_posix(), "kind": "plugin-parent", "area": "plugins", "status": "ok", "reasons": [], "skipped_by_rule": []}
        with mock.patch.object(_engine.fs, "open_nofollow_read", wraps=_engine.fs.open_nofollow_read) as opener:
            skills, skipped = R.collect_skills([root])
        self.assertEqual([s["path"].name for s in skills], ["s"])
        self.assertEqual(root["status"], "ok")
        self.assertEqual(sorted((x["path"].rsplit("/", 1)[1], x["reason"]) for x in root["skipped_by_rule"]),
                         [(".worktrees", "excluded"), ("My OneDrive plugin", "cloud-name")])
        self.assertFalse([c for c in opener.call_args_list if "OneDrive" in os.fspath(c.args[0])], "the cloud-named plugin was opened")
        link_target = self.tmp / "target"
        make_plugin(link_target, "t")
        make_link(self, parent / "linked", link_target / "t")
        root["status"], root["reasons"], root["skipped_by_rule"] = "ok", [], []
        R.collect_skills([root])
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["link"]))

    def test_cloud_attribute_and_unreadable_make_the_root_partial(self):
        """bắt-lỗi: FR2.2 a child with cloud attributes (reason cloud) and a plugin whose manifest cannot be read (unreadable) make the root partial; the report lists them."""
        parent = self.tmp / "plugins"
        parent.mkdir()
        make_plugin(parent, "placeholder")
        broken = make_plugin(parent, "broken", "{")
        root = {"path": parent.as_posix(), "kind": "plugin-parent", "area": "plugins", "status": "ok", "reasons": [], "skipped_by_rule": []}
        real = _engine.fs.entry_is_cloud
        with mock.patch.object(_engine.fs, "entry_is_cloud", side_effect=lambda e: e.name == "placeholder" or real(e)):
            skills, skipped = R.collect_skills([root])
        self.assertEqual(skills, [])
        self.assertEqual((root["status"], sorted(root["reasons"])), ("partial", ["cloud", "unreadable"]))
        self.assertEqual(sorted((x["path"].rsplit("/", 1)[1], x["reason"]) for x in skipped),
                         [("placeholder", "cloud"), ("plugin.json", "unreadable")])
        self.assertEqual(root["skipped_by_rule"], [])

    def test_nested_scan_shares_the_directory_budget(self):
        """bắt-lỗi: RF-5.2 skills inside skills spend the one DOCTOR_MAX_DIRS budget of the run: past it the rest is left out with `limit` (root partial)."""
        parent = self.tmp / "plugins"
        parent.mkdir()
        plugin = make_plugin(parent, "p")
        make_skill(plugin / "skills" / "outer")
        for i in range(8):
            make_skill(plugin / "skills" / "outer" / ("g%d" % i) / "inner")
        root = {"path": parent.as_posix(), "kind": "plugin-parent", "area": "plugins", "status": "ok", "reasons": [], "skipped_by_rule": []}
        with mock.patch.object(C, "DOCTOR_MAX_DIRS", 6):
            skills, _ = R.collect_skills([root])
        self.assertLess(len(skills), 9)
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["limit"]))

    def test_cloud_name_inside_a_plugin_is_by_rule_and_placeholder_is_not(self):
        """bắt-lỗi: RF-5.3 a folder named like a cloud zone inside a plugin is cloud-name (root stays ok); a real placeholder is cloud (partial)."""
        parent = self.tmp / "plugins"
        parent.mkdir()
        plugin = make_plugin(parent, "p")
        make_skill(plugin / "skills" / "outer")
        make_skill(plugin / "skills" / "outer" / "onedrive-sync" / "inner")
        (plugin / "skills" / "outer" / "grp" / "OneDrive x").mkdir(parents=True)
        (plugin / "skills" / "outer" / "grp" / "OneDrive x" / "SKILL.md").write_text("x", encoding="utf-8")
        make_skill(plugin / "skills" / "outer" / "ph" / "inner")
        root = {"path": parent.as_posix(), "kind": "plugin-parent", "area": "plugins", "status": "ok", "reasons": [], "skipped_by_rule": []}
        skills, _ = R.collect_skills([root])
        self.assertEqual((root["status"], root["reasons"]), ("ok", []))
        self.assertEqual(sorted(x["reason"] for x in root["skipped_by_rule"]), ["cloud-name", "cloud-name"])
        root = dict(root, status="ok", reasons=[], skipped_by_rule=[])
        real = _engine.fs.entry_is_cloud
        with mock.patch.object(_engine.fs, "entry_is_cloud", side_effect=lambda e: e.name == "ph" or real(e)):
            R.collect_skills([root])
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["cloud"]))

    def test_error_roots_are_not_scanned(self):
        """bắt-lỗi: FR1.3 a root with status error is left alone and gives no skill."""
        root = {"path": (FIX / "plugins").as_posix(), "kind": "plugin-parent", "area": "plugins", "status": "error", "reasons": ["x"], "skipped_by_rule": []}
        with mock.patch("os.scandir", side_effect=AssertionError("listed")):
            self.assertEqual(R.collect_skills([root]), ([], []))

    def test_skipped_reasons_follow_the_table(self):
        """bắt-lỗi: FR2.2 the by-rule reasons are vendor, excluded, cloud-name, non-semver, other-version, no-manifest; every other reason makes a root partial."""
        self.assertEqual(R.SKIPPED_BY_RULE, frozenset({"vendor", "excluded", "cloud-name", "non-semver", "other-version", "no-manifest"}))
        root = {"path": "x", "kind": "plugin", "area": "a", "status": "ok", "reasons": [], "skipped_by_rule": []}
        for reason in ("cloud", "link", "secret-zone", "manifest-escape", "install-path-escape", "limit", "unreadable"):
            fresh = dict(root, reasons=[], skipped_by_rule=[])
            R.note_skip(fresh, "p/" + reason, reason)
            self.assertEqual((fresh["status"], fresh["reasons"], fresh["skipped_by_rule"]), ("partial", [reason], []), reason)
        for reason in sorted(R.SKIPPED_BY_RULE):
            fresh = dict(root, reasons=[], skipped_by_rule=[])
            R.note_skip(fresh, "p/" + reason, reason)
            self.assertEqual((fresh["status"], fresh["reasons"], fresh["skipped_by_rule"]), ("ok", [], [{"path": "p/" + reason, "reason": reason}]), reason)
        fresh = dict(root, status="error", reasons=["x"], skipped_by_rule=[])
        R.note_skip(fresh, "p", "link")
        self.assertEqual(fresh["status"], "error", "a partial reason never lifts or hides an error")


class TreeShaTests(TmpCase):
    def skill(self, name="s") -> Path:
        return make_skill(self.tmp / name)

    def expect(self, skill: Path) -> str:
        lines = []
        for path in sorted((p for p in skill.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"), key=lambda p: p.relative_to(skill).as_posix()):
            lines.append("%s\t%s\n" % (path.relative_to(skill).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
        return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()

    def test_tree_sha_matches_the_definition(self):
        """bắt-lỗi: PLAN contract: SHA-256 of '<posix rel path>\\t<sha256 of the bytes>\\n' lines sorted by path, over every regular file."""
        skill = self.skill()
        (skill / "references").mkdir()
        (skill / "references" / "a.md").write_bytes(b"alpha\r\nbeta\n")
        (skill / "scripts").mkdir()
        (skill / "scripts" / "run.py").write_bytes(b"print(1)\n")
        (skill / "B.txt").write_bytes(b"\x00\x01")
        self.assertEqual(R.tree_sha256(skill, C.CLOUD_MARKERS), self.expect(skill))

    def test_tree_sha_is_none_when_a_folder_cannot_be_listed(self):
        """bắt-lỗi: RF-5.4 a sub-folder that cannot be listed gives None, never the hash of a tree with a hole."""
        skill = self.skill()
        (skill / "locked").mkdir()
        (skill / "locked" / "f.txt").write_text("x", encoding="utf-8")
        self.assertIsNotNone(R.tree_sha256(skill, C.CLOUD_MARKERS))
        real = os.scandir

        def scan(path, *a, **k):
            if Path(os.fspath(path)).name == "locked":
                raise PermissionError(13, "denied")
            return real(path, *a, **k)
        with mock.patch("os.scandir", side_effect=scan):
            self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS))

    def test_tree_sha_is_none_when_the_skill_folder_itself_cannot_be_listed(self):
        """bắt-lỗi: RF-5.9 the skill folder that cannot be listed gives None, not the hash of the empty string."""
        skill = self.skill()
        real = os.scandir

        def scan(path, *a, **k):
            if Path(os.fspath(path)) == skill:
                raise PermissionError(13, "denied")
            return real(path, *a, **k)
        with mock.patch("os.scandir", side_effect=scan):
            self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS))

    def test_tree_sha_keeps_crlf_and_ignores_pycache(self):
        """bắt-lỗi: bytes are hashed as they are (CRLF counts), __pycache__ and .pyc do not, and the result does not depend on the order files were made."""
        one, two = self.skill("one"), self.skill("two")
        (two / "SKILL.md").write_bytes((one / "SKILL.md").read_bytes())
        (one / "f.md").write_bytes(b"x\r\ny\r\n")
        (one / "g.md").write_bytes(b"g")
        (two / "g.md").write_bytes(b"g")
        (two / "f.md").write_bytes(b"x\r\ny\r\n")
        a = R.tree_sha256(one, C.CLOUD_MARKERS)
        self.assertEqual(a, R.tree_sha256(two, C.CLOUD_MARKERS))
        (two / "f.md").write_bytes(b"x\ny\n")
        self.assertNotEqual(a, R.tree_sha256(two, C.CLOUD_MARKERS), "CRLF vs LF must differ")
        (two / "f.md").write_bytes(b"x\r\ny\r\n")
        (two / "__pycache__").mkdir()
        (two / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"junk")
        (two / "m.pyc").write_bytes(b"junk")
        self.assertEqual(a, R.tree_sha256(two, C.CLOUD_MARKERS))
        (two / "new.md").write_bytes(b"1")
        self.assertNotEqual(a, R.tree_sha256(two, C.CLOUD_MARKERS))

    def test_tree_sha_none_for_link_cloud_and_limits(self):
        """bắt-lỗi: a link, a cloud placeholder, a zone-named folder, a secret-named file, too many files or a file above 25 MB give None."""
        skill = self.skill()
        self.assertIsNotNone(R.tree_sha256(skill, C.CLOUD_MARKERS))
        (skill / "bulk.bin").write_bytes(b"0123456789")
        with mock.patch.object(R, "TREE_FILE_MAX", 5):
            self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS))
        self.assertEqual(R.TREE_FILE_MAX, 25 * 1024 * 1024)
        with mock.patch.object(C, "DOCTOR_MAX_FILES_PER_SKILL", 1):
            self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS))
        placeholder = skill / "bulk.bin"
        real = _engine.fs.entry_is_cloud
        with mock.patch.object(_engine.fs, "entry_is_cloud", side_effect=lambda e: e.name == "bulk.bin" or real(e)):
            with mock.patch.object(_engine.fs, "open_nofollow_read", side_effect=AssertionError("opened")):
                self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS))
        placeholder.unlink()
        (skill / "OneDrive copy").mkdir()
        self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS), "a folder named like a cloud zone is not entered, so the tree cannot be hashed whole")
        (skill / "OneDrive copy").rmdir()
        (skill / ".env").write_bytes(b"A=1")
        with mock.patch.object(_engine.fs, "open_nofollow_read", side_effect=AssertionError("opened")):
            self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS), "a secret-looking file is never opened")

    def test_tree_sha_none_for_a_link(self):
        """bắt-lỗi: a link inside the skill gives None (the link is not followed)."""
        skill = self.skill()
        other = self.tmp / "other"
        other.mkdir()
        make_link(self, skill / "door", other)
        with mock.patch.object(_engine.fs, "open_nofollow_read", side_effect=AssertionError("opened")):
            self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS))

    def test_tree_sha_none_when_a_file_is_replaced_by_a_link(self):
        """bắt-lỗi: UnsafeOpen (a file swapped for a link after listing) and any OSError give None, never an exception."""
        skill = self.skill()
        with mock.patch.object(_engine.fs, "open_nofollow_read", side_effect=_engine.fs.UnsafeOpen("swapped")):
            self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS))
        with mock.patch.object(_engine.fs, "open_nofollow_read", side_effect=OSError("denied")):
            self.assertIsNone(R.tree_sha256(skill, C.CLOUD_MARKERS))

    def test_tree_sha_none_for_a_missing_skill(self):
        """bắt-lỗi: a folder that is not there gives None."""
        self.assertIsNone(R.tree_sha256(self.tmp / "nope", C.CLOUD_MARKERS))

    def test_tree_sha_reads_bytes_not_text(self):
        """bắt-lỗi: the file is read through open_nofollow_read (not read_capped, which folds CRLF)."""
        skill = self.skill()
        with mock.patch.object(_engine.fs, "read_capped", side_effect=AssertionError("read_capped")):
            self.assertIsNotNone(R.tree_sha256(skill, C.CLOUD_MARKERS))


class TreeDigestSemanticTests(TmpCase):
    """RF-10.1/10.3: the byte hash stays, `.git` leaves it, and a second digest folds what an adapter rewrites."""

    BARE = b"---\nname: s\ndescription: D. Use when x.\n---\n\nBody\n"

    def pair(self, one_text: bytes, two_text: bytes):
        a, b = make_skill(self.tmp / "a" / "s"), make_skill(self.tmp / "b" / "s")
        (a / "SKILL.md").write_bytes(one_text)
        (b / "SKILL.md").write_bytes(two_text)
        return a, b

    def same(self, a, b) -> bool:
        return R.tree_digest_semantic(a, C.CLOUD_MARKERS) == R.tree_digest_semantic(b, C.CLOUD_MARKERS)

    def test_git_folder_is_not_part_of_the_hashes(self):
        """bắt-lỗi: RF-10.3 a `.git` folder in the source checkout changes neither tree_sha256 nor the semantic digest."""
        a, b = self.pair(self.BARE, self.BARE)
        before = R.tree_sha256(a, C.CLOUD_MARKERS)
        (a / ".git").mkdir()
        (a / ".git" / "HEAD").write_bytes(b"ref: x")
        self.assertEqual(R.tree_sha256(a, C.CLOUD_MARKERS), before)
        self.assertEqual(R.tree_sha256(a, C.CLOUD_MARKERS), R.tree_sha256(b, C.CLOUD_MARKERS))
        self.assertTrue(self.same(a, b))

    def test_quoted_frontmatter_value_is_the_same(self):
        """bắt-lỗi: a `description` wrapped in quotes, or with a unicode escape for the apostrophe, digests like the bare one."""
        a, b = self.pair(b"---\nname: s\ndescription: It's fine. Use when x.\n---\n\nBody\n",
                         b'---\nname: s\ndescription: "It\\u0027s fine. Use when x."\n---\n\nBody\n')
        self.assertNotEqual(R.tree_sha256(a, C.CLOUD_MARKERS), R.tree_sha256(b, C.CLOUD_MARKERS))
        self.assertTrue(self.same(a, b))

    def test_crlf_and_lf_are_the_same_in_text_files_only(self):
        """bắt-lỗi: CRLF vs LF is folded in SKILL.md and in text files, but not in a file of another kind."""
        a, b = self.pair(self.BARE.replace(b"\n", b"\r\n"), self.BARE)
        (a / "n.md").write_bytes(b"x\r\ny\r\n")
        (b / "n.md").write_bytes(b"x\ny\n")
        self.assertTrue(self.same(a, b))
        (a / "d.bin").write_bytes(b"x\r\ny")
        (b / "d.bin").write_bytes(b"x\ny")
        self.assertFalse(self.same(a, b))

    def test_a_changed_word_or_a_missing_file_still_differs(self):
        """bắt-lỗi: the body, a frontmatter value, a missing file and an extra file give a different semantic digest; .gitkeep and .pyc do not."""
        a, b = self.pair(self.BARE, self.BARE)
        self.assertTrue(self.same(a, b))
        (b / "SKILL.md").write_bytes(self.BARE.replace(b"Body", b"Bodies"))
        self.assertFalse(self.same(a, b))
        (b / "SKILL.md").write_bytes(self.BARE.replace(b"D. Use", b"E. Use"))
        self.assertFalse(self.same(a, b))
        (b / "SKILL.md").write_bytes(self.BARE)
        (a / "extra.md").write_bytes(b"1")
        self.assertFalse(self.same(a, b))
        (a / "extra.md").unlink()
        (a / ".gitkeep").write_bytes(b"")
        (a / "m.pyc").write_bytes(b"junk")
        self.assertTrue(self.same(a, b))

    def test_same_refusals_as_the_byte_hash(self):
        """bắt-lỗi: None for a missing folder, a link, a secret-looking file and a file above the limit, like tree_sha256."""
        a, _ = self.pair(self.BARE, self.BARE)
        self.assertIsNotNone(R.tree_digest_semantic(a, C.CLOUD_MARKERS))
        self.assertIsNone(R.tree_digest_semantic(self.tmp / "nope", C.CLOUD_MARKERS))
        (a / "bulk.bin").write_bytes(b"0123456789")
        with mock.patch.object(R, "TREE_FILE_MAX", 5):
            self.assertIsNone(R.tree_digest_semantic(a, C.CLOUD_MARKERS))
        (a / "bulk.bin").unlink()
        (a / ".env").write_bytes(b"A=1")
        with mock.patch.object(_engine.fs, "open_nofollow_read", side_effect=AssertionError("opened")):
            self.assertIsNone(R.tree_digest_semantic(a, C.CLOUD_MARKERS))
        (a / ".env").unlink()
        other = self.tmp / "other"
        other.mkdir()
        make_link(self, a / "door", other)
        self.assertIsNone(R.tree_digest_semantic(a, C.CLOUD_MARKERS))

    def test_a_warned_frontmatter_scalar_still_folds(self):
        """bắt-lỗi: RF-10.11 the parser warns (FM1, one finding) about a bare `: ` in a value; the quoted spelling of it must still digest alike."""
        a, b = self.pair(b"---\nname: s\ndescription: Use when x: y.\n---\n\nBody\n", b'---\nname: s\ndescription: "Use when x: y."\n---\n\nBody\n')
        self.assertTrue(self.same(a, b))

    def frontmatter(self, extra: bytes) -> bytes:
        return b"---\nname: s\ndescription: D. Use when x.\n" + extra + b"---\n\nBody\n"

    def test_lines_the_parser_drops_still_count(self):
        """bắt-lỗi: RF-10.10 a list item, a nested metadata line, a bad key and a duplicate key are dropped by parse_frontmatter; a change in them must differ."""
        cases = {
            "list item": (b"allowed-tools:\n  - Read\n", b"allowed-tools:\n  - Bash\n"),
            "nested metadata": (b"metadata:\n  group: a\n  deep:\n    x: 1\n", b"metadata:\n  group: a\n  deep:\n    x: 2\n"),
            "bad key": (b"[x]: 1\n", b"[y]: 2\n"),
            "duplicate key": (b"owner: A\nowner: C\n", b"owner: B\nowner: C\n"),
        }
        for name, (one, two) in cases.items():
            with self.subTest(name):
                a, b = self.pair(self.frontmatter(one), self.frontmatter(two))
                self.assertFalse(self.same(a, b))
                a, b = self.pair(self.frontmatter(one), self.frontmatter(one.replace(b"\n", b"\r\n").replace(b"\r\n", b"  \r\n")))
                self.assertTrue(self.same(a, b), "CRLF and trailing spaces are folded in the lines kept as they are")

    def test_unparsable_frontmatter_falls_back_to_folded_text(self):
        """bắt-lỗi: a SKILL.md without frontmatter, or not UTF-8, still digests (CRLF folded) and does not raise."""
        a, b = self.pair(b"no frontmatter\r\nhere\r\n", b"no frontmatter\nhere\n")
        self.assertTrue(self.same(a, b))
        (a / "SKILL.md").write_bytes(b"\xff\xfe\r\n")
        (b / "SKILL.md").write_bytes(b"\xff\xfe\n")
        self.assertTrue(self.same(a, b))


class DoctorRootsFromTests(TmpCase):
    def test_roots_from_conflicts(self):
        """bắt-lỗi: FR1.4 --roots-from with --roots or --roots-file is refused: exit 2, a message naming both, nothing scanned."""
        listing = self.tmp / "roots.txt"
        listing.write_text(str(self.tmp) + "\n", encoding="utf-8")
        for extra in (("--roots", str(self.tmp)), ("--roots-file", str(listing))):
            with self.subTest(extra):
                with mock.patch.object(doctor, "iter_skill_dirs", side_effect=AssertionError("scanned")):
                    code, out, err = run_doctor("--roots-from", "opcos", *extra, cwd=FIX)
                self.assertEqual(code, 2, out + err)
                self.assertIn("--roots-from", err)
                self.assertEqual(out, "")

    def test_roots_from_only_opcos(self):
        """bắt-lỗi: FR1.1 --roots-from takes `opcos` and nothing else (argparse exit 2)."""
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            studio.main(["doctor", "--roots-from", "nowhere"])
        self.assertEqual(caught.exception.code, 2)

    def test_no_paths_json_exits_2(self):
        """bắt-lỗi: FR1.3 no paths.json from the working folder up: exit 2 and «paths.json not found»."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPCOS_ROOT", None)
            code, out, err = run_doctor("--roots-from", "opcos", cwd=self.tmp)
        self.assertEqual(code, 2, out + err)
        self.assertIn("paths.json not found", err)

    def test_refused_paths_json_exits_2_with_the_reason(self):
        """bắt-lỗi: FR1.1 a paths.json above 256 KB: exit 2 and the reason limit in the message."""
        (self.tmp / "paths.json").write_bytes(b" " * (C.PATHS_JSON_MAX + 1))
        with mock.patch.dict(os.environ):
            os.environ.pop("OPCOS_ROOT", None)
            code, out, err = run_doctor("--roots-from", "opcos", cwd=self.tmp)
        self.assertEqual(code, 2, out + err)
        self.assertIn("paths.json", err)
        self.assertIn("limit", err)

    def test_all_roots_unusable_exits_2(self):
        """bắt-lỗi: FR1.3 every root an error: exit 2; one usable root: the run goes on."""
        (self.tmp / "paths.json").write_text(json.dumps({"areas": [{"id": "plugins", "rel_path": "gone"}, {"id": "opcos-plugin", "rel_path": "gone2"}]}), encoding="utf-8")
        with mock.patch.dict(os.environ):
            os.environ.pop("OPCOS_ROOT", None)
            code, out, err = run_doctor("--roots-from", "opcos", cwd=self.tmp)
        self.assertEqual(code, 2, out + err)
        self.assertIn("no usable root", err)
        (self.tmp / "plugins").mkdir()
        make_skill(make_plugin(self.tmp / "plugins", "p") / "skills" / "s")
        (self.tmp / "paths.json").write_text(json.dumps({"areas": [{"id": "plugins", "rel_path": "plugins"}, {"id": "opcos-plugin", "rel_path": "gone2"}]}), encoding="utf-8")
        with mock.patch.dict(os.environ):
            os.environ.pop("OPCOS_ROOT", None)
            code, out, err = run_doctor("--roots-from", "opcos", "--json", cwd=self.tmp)
        self.assertIn(code, (0, 1), out + err)
        report = json.loads(out)
        self.assertEqual(report["totals"]["skills"], 1)
        self.assertEqual([(r["area"], r["status"]) for r in report["roots_status"]], [("opcos-plugin", "error"), ("plugins", "ok")])

    def test_fixture_run_json(self):
        """bắt-lỗi: FR1.2 on the fixture the report holds 5 skills, none under tests/examples/evals/assets/skill-template, schema 1, the skipped list and roots_status."""
        with mock.patch.dict(os.environ):
            os.environ.pop("OPCOS_ROOT", None)
            code, out, err = run_doctor("--roots-from", "opcos", "--json", cwd=FIX / "plugins")
        self.assertIn(code, (0, 1), out + err)
        report = json.loads(out)
        self.assertEqual(report["schema"], 1)
        self.assertEqual(sorted(Path(s["path"]).name for s in report["skills"]), ["a", "b", "c", "h", "p-root"])
        for part in ("/tests/", "/evals/", "/examples/", "/assets/skill-template"):
            self.assertFalse([s for s in report["skills"] if part in s["path"][len(FIX.as_posix()):] + "/"], part)
        reasons = sorted((Path(x["path"]).name, x["reason"]) for x in report["skipped"])
        self.assertIn(("vendor-x", "vendor"), reasons)
        self.assertIn(("plugin.json", "manifest-escape"), reasons)
        by_area = {r["area"]: r for r in report["roots_status"]}
        self.assertEqual({k: v["status"] for k, v in by_area.items()}, {"opcos-plugin": "ok", "plugins": "partial", "system-plugins": "ok"})
        self.assertEqual(len(report["roots"]), 3)

    def test_fixture_run_text(self):
        """bắt-lỗi: FR1.2 the text run prints the totals and a line per root that is not ok."""
        with mock.patch.dict(os.environ):
            os.environ.pop("OPCOS_ROOT", None)
            code, out, err = run_doctor("--roots-from", "opcos", cwd=FIX)
        self.assertIn(code, (0, 1), out + err)
        self.assertIn("5 skills", out)
        self.assertIn("root plugins: partial (manifest-escape)", out)

    def test_old_roots_report_has_no_new_keys(self):
        """bắt-lỗi: FR1.4 without --roots-from the JSON has no roots_status: the 0.2.0 contract is kept."""
        code, out, err = run_doctor("--roots", str(FIX / "plugins" / "p-default" / "skills"), "--json")
        self.assertIn(code, (0, 1), out + err)
        self.assertNotIn("roots_status", json.loads(out))

    def test_out_inside_a_scanned_root_is_refused(self):
        """bắt-lỗi: FR1.1 with --roots-from the --out rule holds for the opcos roots: a report inside plugins/ is refused, exit 2, nothing written."""
        target = self.tmp / "plugins"
        shutil.copytree(FIX, self.tmp / "tree")
        report = self.tmp / "tree" / "plugins" / "report.json"
        with mock.patch.dict(os.environ):
            os.environ.pop("OPCOS_ROOT", None)
            code, out, err = run_doctor("--roots-from", "opcos", "--out", str(report), cwd=self.tmp / "tree")
        self.assertEqual(code, 2, out + err)
        self.assertIn("scanned root", err)
        self.assertFalse(report.exists())
        good = self.tmp / "report.json"
        with mock.patch.dict(os.environ):
            os.environ.pop("OPCOS_ROOT", None)
            code, out, err = run_doctor("--roots-from", "opcos", "--out", str(good), cwd=self.tmp / "tree")
        self.assertIn(code, (0, 1), out + err)
        self.assertEqual(json.loads(good.read_text(encoding="utf-8"))["schema"], 1)


class OutProblemKindTests(TmpCase):
    """`out_problem(..., kind=...)`: the kind decides which existing file may be overwritten."""

    def problem(self, out, kind="doctor", roots=()):
        return doctor.out_problem(Path(out), list(roots), None, [], False, (), kind=kind)

    def test_public_name_and_alias(self):
        """bắt-lỗi: TK5 out_problem is public and _out_problem stays as an alias; kind defaults to doctor."""
        self.assertIs(doctor._out_problem, doctor.out_problem)
        self.assertIsNone(self.problem(self.tmp / "new.json"))
        self.assertIsNone(doctor.out_problem(self.tmp / "new.json", [], None))
        with self.assertRaises(ValueError):
            self.problem(self.tmp / "new.json", kind="other")

    def test_json_kinds_overwrite_only_an_empty_file_or_a_schema_report(self):
        """bắt-lỗi: doctor and catalog-json overwrite an empty .json or one that starts with {"schema"; anything else is refused."""
        for kind in ("doctor", "catalog-json"):
            with self.subTest(kind):
                ok = self.tmp / "ok.json"
                ok.write_text('{"schema": 1}', encoding="utf-8")
                self.assertIsNone(self.problem(ok, kind))
                ok.write_text("", encoding="utf-8")
                self.assertIsNone(self.problem(ok, kind))
                ok.write_bytes(b"\xef\xbb\xbf" + b'{"schema": 1}')
                self.assertIsNone(self.problem(ok, kind))
                bad = self.tmp / "bad.json"
                bad.write_text('{"other": 1}', encoding="utf-8")
                self.assertIn("not a", self.problem(bad, kind))
                md = self.tmp / "x.md"
                md.write_text('{"schema": 1}', encoding="utf-8")
                self.assertIn("not a .json", self.problem(md, kind))
                catalog = self.tmp / "catalog.md"
                catalog.write_text("<!-- studio catalog -->\n# x\n", encoding="utf-8")
                self.assertIn("not a .json", self.problem(catalog, kind), "a catalog .md is not overwritten by a json kind")

    def test_doctor_message_is_unchanged(self):
        """bắt-lỗi: the messages of kind doctor are the 0.2.0 ones (the contract suite compares them)."""
        bad = self.tmp / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        self.assertEqual(self.problem(bad), "--out would overwrite an existing file that is not a doctor report (it must start with {\"schema\"): %s" % bad)
        md = self.tmp / "x.md"
        md.write_text("x", encoding="utf-8")
        self.assertEqual(self.problem(md), "--out would overwrite an existing file that is not a .json report: %s" % md)

    def test_catalog_md_kind(self):
        """bắt-lỗi: catalog-md overwrites an empty .md or one whose first line is <!-- studio catalog -->; a json report, a plain .md and a .txt are refused; messages say --md."""
        ok = self.tmp / "CATALOG.md"
        ok.write_text("<!-- studio catalog -->\n\n# Catalog\n", encoding="utf-8")
        self.assertIsNone(self.problem(ok, "catalog-md"))
        ok.write_bytes(b"\xef\xbb\xbf<!-- studio catalog -->\r\n# Catalog\r\n")
        self.assertIsNone(self.problem(ok, "catalog-md"))
        ok.write_text("", encoding="utf-8")
        self.assertIsNone(self.problem(ok, "catalog-md"))
        plain = self.tmp / "README.md"
        plain.write_text("# My notes\n", encoding="utf-8")
        found = self.problem(plain, "catalog-md")
        self.assertTrue(found.startswith("--md would overwrite an existing file that is not a catalog"), found)
        later = self.tmp / "late.md"
        later.write_text("# T\n<!-- studio catalog -->\n", encoding="utf-8")
        self.assertIn("not a catalog", self.problem(later, "catalog-md"), "the marker must be the first line")
        report = self.tmp / "report.json"
        report.write_text('{"schema": 1}', encoding="utf-8")
        self.assertIn("not a .md", self.problem(report, "catalog-md"))
        text = self.tmp / "x.txt"
        text.write_text("", encoding="utf-8")
        self.assertIn("not a .md", self.problem(text, "catalog-md"))
        self.assertIsNone(self.problem(self.tmp / "fresh.md", "catalog-md"))

    def test_other_rules_hold_for_every_kind_and_run_twice(self):
        """bắt-lỗi: Trọng tâm 4: the zone, secret-name, scanned-root and skills/ rules hold for every kind, and writing the same file a second time is allowed."""
        root = self.tmp / "scanned"
        root.mkdir()
        for kind, name in (("doctor", "r.json"), ("catalog-json", "c.json"), ("catalog-md", "CATALOG.md")):
            with self.subTest(kind):
                self.assertIn("scanned root", self.problem(root / name, kind, [root]))
                self.assertIn("secret-looking", self.problem(self.tmp / ".env.json" if kind != "catalog-md" else self.tmp / ".env.md", kind))
                self.assertIn("skills/", self.problem(self.tmp / "skills" / name, kind))
                self.assertIn("zone", self.problem(self.tmp / "OneDrive x" / name, kind))
                target = self.tmp / name
                self.assertIsNone(self.problem(target, kind, [root]))
                target.write_text('{"schema": 1}\n' if kind != "catalog-md" else "<!-- studio catalog -->\n", encoding="utf-8")
                self.assertIsNone(self.problem(target, kind, [root]), "second run over its own file")


if __name__ == "__main__":
    unittest.main()
