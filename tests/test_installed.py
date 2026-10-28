"""SPR-04 TK10 (FR3.1-FR3.4, SC2, SC16): the installed copies of each harness, read by three locators and matched with the source skills.

Run: python -X utf8 -m unittest tests.test_installed -v
"""
from __future__ import annotations

import builtins
import contextlib
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
import test_catalog as TC  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOMES = ROOT / "tests" / "fixtures" / "homes"
CURATOR_DIR = ROOT / "skills" / "skill-curator" / "scripts"
studio = _engine.engine
MARKERS = _engine.const.CLOUD_MARKERS


def load_installed():
    """`curator_installed` as `studio.py catalog` loads it: the curator folder is fixed from the engine file and put on the path after the engine."""
    module, problem = studio.load_curator_catalog()
    assert module is not None, problem
    import curator_installed
    assert Path(curator_installed.__file__).resolve().parent == CURATOR_DIR.resolve()
    return curator_installed


def make_junction(link: Path, target: Path) -> bool:
    """A directory link at `link` to `target` (a junction on Windows, a symlink elsewhere); False when this machine cannot make one."""
    try:
        if os.name == "nt":
            done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            return done.returncode == 0 and link.exists()
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


def drop_link(link: Path) -> None:
    try:
        os.rmdir(link) if os.name == "nt" else os.unlink(link)
    except OSError:
        pass


class HomeCase(unittest.TestCase):
    def setUp(self):
        _engine.clear_caches()
        self.addCleanup(_engine.clear_caches)
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-installed-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mod = load_installed()

    def home(self, fixture="ok", name="home", outside: Path = None) -> Path:
        """A copy of tests/fixtures/homes/<fixture> in the temporary folder with the placeholders of the Claude index filled in."""
        dest = self.tmp / name
        shutil.copytree(HOMES / fixture, dest)
        index = dest / ".claude" / "plugins" / "installed_plugins.json"
        if index.is_file():
            text = index.read_text(encoding="utf-8").replace("@HOME@", dest.as_posix())
            if outside is not None:
                text = text.replace("@OUTSIDE@", outside.as_posix())
            index.write_bytes(text.encode("utf-8"))
        return dest

    def locate(self, harness: str, home: Path):
        return self.mod.locate(harness, home, MARKERS)

    @staticmethod
    def skills(items) -> list:
        return sorted((i["plugin"], i["skill"], i["version"]) for i in items)

    def index_with(self, home: Path, plugins: dict) -> None:
        (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8")


class LocatorTests(HomeCase):
    def test_claude_reads_only_the_install_path_of_the_index(self):
        """bắt-lỗi: FR3.1 Claude lists the skills of the `installPath` of every index entry and does not walk the old versions kept in cache/."""
        items, root = self.locate("claude", self.home())
        self.assertEqual((root["status"], root["kind"], root["area"], root["reasons"]), ("ok", "harness", "claude", []))
        self.assertEqual(self.skills(items), [("demo", "alpha", "1.0.0"), ("demo", "beta", "1.0.0"), ("extra", "gamma", "0.1.0")])
        self.assertTrue(all(i["harness"] == "claude" and i["scope"] == "user" for i in items))
        self.assertNotIn("stale", [i["skill"] for i in items])

    def test_codex_highest_semver(self):
        """bắt-lỗi: FR3.1 Codex takes the highest version by number (1.10.0 above 1.2.0), lists the others as other-version and the root stays ok."""
        items, root = self.locate("codex", self.home())
        self.assertEqual(self.skills(items), [("demo", "alpha", "1.10.0"), ("demo", "beta", "1.10.0")])
        self.assertTrue(items[0]["path"].replace("\\", "/").endswith("/demo/1.10.0/skills/alpha") or items[1]["path"].replace("\\", "/").endswith("/demo/1.10.0/skills/alpha"))
        reasons = {(x["path"].replace("\\", "/").rsplit("/", 1)[-1], x["reason"]) for x in root["skipped_by_rule"]}
        self.assertIn(("1.2.0", "other-version"), reasons)
        self.assertEqual(root["status"], "ok")
        self.assertEqual(root["reasons"], [])

    def test_codex_non_semver_skipped(self):
        """bắt-lỗi: a Codex folder that is not a semver (`latest`) is never the installed copy, even when it holds a newer-looking manifest; by rule, root ok."""
        items, root = self.locate("codex", self.home())
        self.assertNotIn("latest", " ".join(i["path"] for i in items))
        self.assertIn(("latest", "non-semver"), {(x["path"].rsplit("/", 1)[-1], x["reason"]) for x in root["skipped_by_rule"]})
        self.assertEqual(root["status"], "ok")

    def test_codex_only_non_semver_gives_no_copy(self):
        home = self.home()
        for name in ("1.2.0", "1.10.0"):
            shutil.rmtree(home / ".codex" / "plugins" / "cache" / "mk" / "demo" / name)
        items, root = self.locate("codex", home)
        self.assertEqual(items, [])
        self.assertEqual(root["status"], "ok")

    def test_antigravity_layout(self):
        """bắt-lỗi: FR3.1 Antigravity lists plugins/<plugin>/skills/<skill>; the version comes from the plugin's plugin.json when there is one."""
        items, root = self.locate("antigravity", self.home())
        self.assertEqual((root["status"], root["area"]), ("ok", "antigravity"))
        self.assertEqual(self.skills(items), [("demo", "alpha", "1.0.0"), ("demo", "beta", "1.0.0")])
        self.assertTrue(all(i["harness"] == "antigravity" and i["scope"] is None for i in items))

    def test_antigravity_without_plugin_json_has_no_version(self):
        home = self.home()
        (home / ".gemini" / "config" / "plugins" / "demo" / "plugin.json").unlink()
        items, root = self.locate("antigravity", home)
        self.assertEqual(root["status"], "ok")
        self.assertEqual({i["version"] for i in items}, {None})

    def test_single_skill_plugin_is_named_after_the_plugin(self):
        """bắt-lỗi: a plugin that is one skill at its root (`skills: ./`) installs into a folder named after a version; the skill is still named after the
        plugin, as at the source (where the folder is the plugin's own), so that the two ends meet."""
        home = self.home()
        one = home / ".claude" / "plugins" / "cache" / "mk" / "solo" / "2.2.3"
        (one / ".claude-plugin").mkdir(parents=True)
        (one / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "solo", "skills": "./"}), encoding="utf-8")
        TC.make_skill(one)
        self.index_with(home, {"solo@mk": [{"scope": "user", "installPath": one.as_posix(), "version": "2.2.3"}]})
        items, root = self.locate("claude", home)
        self.assertEqual((root["status"], [(i["plugin"], i["skill"], i["version"]) for i in items]), ("ok", [("solo", "solo", "2.2.3")]))
        codex = home / ".codex" / "plugins" / "cache" / "mk" / "solo" / "2.2.3"
        (codex / ".codex-plugin").mkdir(parents=True)
        (codex / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "solo", "skills": "./"}), encoding="utf-8")
        TC.make_skill(codex)
        items, root = self.locate("codex", home)
        self.assertIn(("solo", "solo", "2.2.3"), [(i["plugin"], i["skill"], i["version"]) for i in items])

    def test_missing_harness_folder_is_error(self):
        """bắt-lỗi: FR3.3 a harness that is not installed has no locator: the root is `error`, nothing is listed."""
        home = self.tmp / "empty-home"
        home.mkdir()
        for harness in ("claude", "codex", "antigravity"):
            items, root = self.locate(harness, home)
            self.assertEqual((items, root["status"]), ([], "error"), harness)
            self.assertTrue(root["reasons"], harness)

    def test_index_missing(self):
        items, root = self.locate("claude", self.home("missing"))
        self.assertEqual((items, root["status"], root["reasons"]), ([], "error", ["index-missing"]))

    def test_index_not_json(self):
        """bắt-lỗi: FR3.3 an index that is not JSON makes the root `error` with `index-unreadable` and lists nothing."""
        items, root = self.locate("claude", self.home("bad-json"))
        self.assertEqual((items, root["status"], root["reasons"]), ([], "error", ["index-unreadable"]))

    def test_index_wrong_shape(self):
        home = self.home()
        for text in ("[]", '{"plugins": []}', '{"version": 2}'):
            (home / ".claude" / "plugins" / "installed_plugins.json").write_text(text, encoding="utf-8")
            items, root = self.locate("claude", home)
            self.assertEqual((items, root["status"], root["reasons"]), ([], "error", ["index-unreadable"]), text)

    def test_index_too_big(self):
        """bắt-lỗi: FR3.3 an index above 1 MB is refused unread: `error`, `index-too-big`, no entry listed."""
        home = self.home()
        (home / ".claude" / "plugins" / "installed_plugins.json").write_bytes(b'{"version": 2, "plugins": {}, "pad": "' + b"x" * (1024 * 1024 + 10) + b'"}')
        with mock.patch.object(json, "loads", side_effect=AssertionError("a too big index must not be parsed")):
            items, root = self.locate("claude", home)
        self.assertEqual((items, root["status"], root["reasons"]), ([], "error", ["index-too-big"]))

    def test_nothing_is_written(self):
        """bắt-lỗi: locating only reads: no file is created or changed under the home folder."""
        home = self.home()

        def listing():
            return sorted((p.relative_to(home).as_posix(), p.stat().st_size, p.stat().st_mtime_ns) for p in home.rglob("*"))
        before = listing()
        for harness in ("claude", "codex", "antigravity"):
            self.locate(harness, home)
        self.assertEqual(listing(), before)


class UntrustedIndexTests(HomeCase):
    """FR3.4 and review focus 2: an entry that leaves the harness folder, enters a zone or passes a link is dropped, the root is `partial`, nothing is opened."""

    def outside(self, name="outside") -> Path:
        folder = self.tmp / name / "evil"
        (folder / ".claude-plugin").mkdir(parents=True)
        (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "evil"}), encoding="utf-8")
        TC.make_skill(folder / "skills" / "loot")
        return folder

    @contextlib.contextmanager
    def watch_opens(self, forbidden: Path):
        """Record every path the engine lists or opens; the test asserts none of them is under `forbidden`."""
        seen = []
        real_open, real_scandir, real_os_open, real_lstat = builtins.open, os.scandir, os.open, os.lstat

        def note(path):
            try:
                seen.append(os.path.normcase(os.path.abspath(os.fsdecode(path))))
            except (TypeError, ValueError):
                pass

        def opener(path, *a, **k):
            note(path)
            return real_open(path, *a, **k)

        def scanner(path=".", *a, **k):
            note(path)
            return real_scandir(path, *a, **k)

        def os_opener(path, *a, **k):
            note(path)
            return real_os_open(path, *a, **k)

        with mock.patch.object(builtins, "open", opener), mock.patch.object(os, "scandir", scanner), mock.patch.object(os, "open", os_opener):
            yield seen
        bad = os.path.normcase(os.path.abspath(forbidden))
        self.assertEqual([p for p in seen if p == bad or p.startswith(bad + os.sep)], [], "a forbidden path was opened or listed")

    def test_install_path_escape(self):
        """bắt-lỗi: FR3.4 an installPath outside ~/.claude is dropped without being listed or opened; the good entry stays; root partial, install-path-escape."""
        outside = self.outside()
        home = self.home("escape", outside=outside)
        with self.watch_opens(outside):
            items, root = self.locate("claude", home)
        self.assertEqual(self.skills(items), [("demo", "alpha", "1.0.0")])
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["install-path-escape"]))

    def test_outside_path_is_refused_by_spelling_before_any_probe(self):
        """bắt-lỗi: an installPath outside ~/.claude is refused by its spelling alone: no link probe, cloud probe or resolve is made on it (a UNC path would reach the network)."""
        outside = self.outside("probe")
        home = self.home("escape", outside=outside)
        gone = os.path.normcase(os.path.abspath(outside))
        fs = _engine.fs

        def guard(real):
            def probe(path, *a, **k):
                self.assertFalse(os.path.normcase(os.path.abspath(os.fspath(path))).startswith(gone), "probed a path outside the harness folder")
                return real(path, *a, **k)
            return probe
        with mock.patch.object(fs, "link_in_chain", guard(fs.link_in_chain)), mock.patch.object(fs, "is_link", guard(fs.is_link)),                 mock.patch.object(fs, "path_is_cloud", guard(fs.path_is_cloud)), mock.patch.object(fs, "valid_resolved_under", guard(fs.valid_resolved_under)):
            items, root = self.locate("claude", home)
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["install-path-escape"]))

    def test_index_behind_a_link_is_error(self):
        """bắt-lỗi: FR3.3 `plugins/` (or the index) being a link makes the Claude locator unusable: error `link`, nothing read."""
        home = self.home()
        folder = (home / ".claude" / "plugins").as_posix().lower()
        real = _engine.fs.is_link
        with mock.patch.object(_engine.fs, "is_link", lambda p: os.fspath(p).replace("\\", "/").lower().rstrip("/") == folder or real(p)):
            items, root = self.locate("claude", home)
        self.assertEqual((items, root["status"], root["reasons"]), ([], "error", ["link"]))

    def test_install_path_secret_zone(self):
        """bắt-lỗi: an installPath that is ~/.secret (or a folder called .secret inside the harness folder) is dropped by name and never opened."""
        home = self.home()
        secret = home / ".secret" / "evil"
        (secret / ".claude-plugin").mkdir(parents=True)
        TC.make_skill(secret / "skills" / "loot")
        inside = home / ".claude" / "plugins" / "cache" / "mk" / ".secret" / "evil2"
        (inside / ".claude-plugin").mkdir(parents=True)
        TC.make_skill(inside / "skills" / "loot2")
        self.index_with(home, {"a@mk": [{"scope": "user", "installPath": secret.as_posix(), "version": "1"}],
                               "b@mk": [{"scope": "user", "installPath": inside.as_posix(), "version": "1"}]})
        with self.watch_opens(home / ".secret"), self.watch_opens(inside):
            items, root = self.locate("claude", home)
        self.assertEqual(items, [])
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["install-path-escape"]))

    def test_install_path_cloud(self):
        """bắt-lỗi: an installPath whose name carries a cloud marker (OneDrive) is dropped by name, never touched; root partial."""
        home = self.home()
        cloudy = home / ".claude" / "plugins" / "cache" / "OneDrive - X" / "evil"
        (cloudy / ".claude-plugin").mkdir(parents=True)
        TC.make_skill(cloudy / "skills" / "loot")
        self.index_with(home, {"c@mk": [{"scope": "user", "installPath": cloudy.as_posix(), "version": "1"}]})
        with self.watch_opens(cloudy):
            items, root = self.locate("claude", home)
        self.assertEqual((items, root["status"], root["reasons"]), ([], "partial", ["install-path-escape"]))

    def test_install_path_cloud_placeholder(self):
        """bắt-lỗi: an install folder that is a cloud placeholder by file attribute is dropped as `cloud` (partial) and not listed."""
        home = self.home()
        target = (home / ".claude" / "plugins" / "cache" / "mk" / "demo" / "1.0.0").as_posix().lower()
        real = _engine.fs.path_is_cloud
        with mock.patch.object(_engine.fs, "path_is_cloud", lambda p: os.path.normcase(os.fspath(p)).replace("\\", "/").lower() == target or real(p)):
            items, root = self.locate("claude", home)
        self.assertEqual(self.skills(items), [("extra", "gamma", "0.1.0")])
        self.assertEqual(root["status"], "partial")
        self.assertIn("install-path-escape", root["reasons"])

    def test_install_path_not_absolute_or_not_text(self):
        home = self.home()
        self.index_with(home, {"a@mk": [{"scope": "user", "installPath": "cache/mk/demo/1.0.0", "version": "1"}],
                               "b@mk": [{"scope": "user", "installPath": 7, "version": "1"}],
                               "c@mk": [{"scope": "user", "version": "1"}],
                               "d@mk": [{"scope": "user", "installPath": "\\\\server\\share\\x", "version": "1"}],
                               "e@mk": "not a list", "f@mk": [3]})
        items, root = self.locate("claude", home)
        self.assertEqual((items, root["status"]), ([], "partial"))
        self.assertEqual(root["reasons"], ["install-path-escape"])

    def test_install_path_with_dotdot_is_judged_after_normalising(self):
        """bắt-lỗi: `<harness>/../outside` is outside: the path is normalised before the containment test."""
        outside = self.outside()
        home = self.home()
        sneaky = (home / ".claude" / "plugins" / ".." / ".." / ".." / outside.relative_to(self.tmp)).as_posix()
        self.index_with(home, {"evil@mk": [{"scope": "user", "installPath": sneaky, "version": "1"}]})
        with self.watch_opens(outside):
            items, root = self.locate("claude", home)
        self.assertEqual((items, root["status"], root["reasons"]), ([], "partial", ["install-path-escape"]))

    def test_install_path_junction_to_a_forbidden_folder(self):
        """bắt-lỗi: PoC of the security reviewer: a real junction (symlink on POSIX) inside ~/.claude/plugins/cache whose target is a .secret-like folder outside
        the harness is not followed: the entry is dropped, the folder behind it is neither listed nor opened, the root is partial."""
        home = self.home()
        target = self.tmp / "zone" / ".secret" / "evil"
        (target / ".claude-plugin").mkdir(parents=True)
        (target / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "evil"}), encoding="utf-8")
        TC.make_skill(target / "skills" / "loot")
        link = home / ".claude" / "plugins" / "cache" / "mk" / "evil-link"
        if not make_junction(link, target):
            self.skipTest("cannot make a directory link on this machine (CI Ubuntu runs it)")
        self.addCleanup(drop_link, link)
        self.index_with(home, {"evil@mk": [{"scope": "user", "installPath": link.as_posix(), "version": "1"}]})
        with self.watch_opens(target):
            items, root = self.locate("claude", home)
        self.assertEqual((items, root["status"], root["reasons"]), ([], "partial", ["install-path-escape"]))

    def test_install_path_junction_to_another_place(self):
        """bắt-lỗi: the same with a harmless-looking target (a plain folder outside the harness): a link is dropped whatever it points at."""
        outside = self.outside("other-drive")
        home = self.home()
        link = home / ".claude" / "plugins" / "cache" / "mk" / "evil-link"
        if not make_junction(link, outside):
            self.skipTest("cannot make a directory link on this machine (CI Ubuntu runs it)")
        self.addCleanup(drop_link, link)
        self.index_with(home, {"evil@mk": [{"scope": "user", "installPath": link.as_posix(), "version": "1"}]})
        with self.watch_opens(outside):
            items, root = self.locate("claude", home)
        self.assertEqual((items, root["status"], root["reasons"]), ([], "partial", ["install-path-escape"]))

    def test_link_in_the_chain_is_dropped_by_patch(self):
        """bắt-lỗi: the link test also holds where this machine cannot make a link: `fs.is_link` answering True for a folder of the chain drops the entry."""
        home = self.home()
        cache = (home / ".claude" / "plugins" / "cache").as_posix().lower()
        real = _engine.fs.is_link
        with mock.patch.object(_engine.fs, "is_link", lambda p: os.fspath(p).replace("\\", "/").lower().rstrip("/") == cache or real(p)):
            items, root = self.locate("claude", home)
        self.assertEqual((items, root["status"], root["reasons"]), ([], "partial", ["install-path-escape"]))

    def test_resolved_outside_is_dropped_by_patch(self):
        """bắt-lỗi: the last test before opening resolves the path: an install folder whose real place is outside the harness folder is dropped."""
        home = self.home()
        real = _engine.fs.valid_resolved_under
        wanted = os.path.normcase(os.fspath(home / ".claude" / "plugins" / "cache" / "mk" / "demo" / "1.0.0"))
        with mock.patch.object(_engine.fs, "valid_resolved_under", lambda c, p: False if os.path.normcase(os.fspath(c)) == wanted else real(c, p)):
            items, root = self.locate("claude", home)
        self.assertEqual(self.skills(items), [("extra", "gamma", "0.1.0")])
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["install-path-escape"]))

    def test_codex_and_antigravity_entries_are_checked_too(self):
        """bắt-lỗi: a Codex or Antigravity folder that is a link or sits outside the harness folder is dropped and the root is partial."""
        outside = self.outside("cx")
        home = self.home()
        for harness, link in (("codex", home / ".codex" / "plugins" / "cache" / "mk" / "evil"), ("antigravity", home / ".gemini" / "config" / "plugins" / "evil")):
            if not make_junction(link, outside):
                self.skipTest("cannot make a directory link on this machine (CI Ubuntu runs it)")
            self.addCleanup(drop_link, link)
            with self.watch_opens(outside):
                items, root = self.locate(harness, home)
            self.assertNotIn("evil", [i["plugin"] for i in items], harness)
            self.assertEqual(root["status"], "partial", harness)
            self.assertEqual(root["reasons"], ["link"], harness)

    def test_manifest_escape_inside_an_install_is_partial(self):
        """bắt-lỗi: an installed manifest whose `skills` leaves the plugin is dropped as manifest-escape; the root is partial."""
        home = self.home()
        manifest = home / ".claude" / "plugins" / "cache" / "mk" / "demo" / "1.0.0" / ".claude-plugin" / "plugin.json"
        manifest.write_text(json.dumps({"name": "demo", "skills": "../../../../../.secret"}), encoding="utf-8")
        items, root = self.locate("claude", home)
        self.assertEqual(self.skills(items), [("extra", "gamma", "0.1.0")])
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["manifest-escape"]))


def source_tree(case: HomeCase) -> Path:
    """A source plugin `demo` (skills alpha equal to the installed copy, beta changed) and `mine` (only at the source), found as `--roots <tree>/demo/skills`."""
    base = case.tmp / "src"
    plugin = base / "demo"
    if plugin.exists():
        return plugin
    shutil.copytree(HOMES / "ok" / ".claude" / "plugins" / "cache" / "mk" / "demo" / "1.0.0", plugin)
    (plugin / "skills" / "beta" / "SKILL.md").write_bytes((plugin / "skills" / "beta" / "SKILL.md").read_bytes() + b"\nSource changed it.\n")
    return plugin


class MatchTests(HomeCase):
    def catalog(self, home: Path, harnesses="claude,codex,antigravity", tree=None, *extra):
        plugin = tree or source_tree(self)
        out = self.tmp / ("out-%d.json" % len(list(self.tmp.glob("out-*.json"))))
        code, so, se = TC.run_catalog("--roots", str(plugin / "skills"), "--installed", harnesses, "--home", str(home), "--out", str(out), *extra)
        return code, json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None, so + se

    def test_match_and_differ(self):
        """bắt-lỗi: FR3.2 alpha equals the installed copy in every harness (`match`, version of the copy), beta differs (`differ`)."""
        code, report, text = self.catalog(self.home())
        self.assertEqual(code, 0, text)
        rows = {r["name"]: r for r in report["skills"]}
        self.assertEqual({h: v["state"] for h, v in rows["alpha"]["installed"].items()}, {"claude": "match", "codex": "match", "antigravity": "match"})
        self.assertEqual(rows["alpha"]["installed"]["codex"]["version"], "1.10.0")
        self.assertEqual({h: v["state"] for h, v in rows["beta"]["installed"].items()}, {"claude": "differ", "codex": "differ", "antigravity": "differ"})
        self.assertEqual(rows["beta"]["installed"]["claude"]["version"], "1.0.0")
        self.assertEqual([r["area"] for r in report["roots"] if r["kind"] == "harness"], ["claude", "codex", "antigravity"])
        self.assertTrue(all(r["status"] == "ok" for r in report["roots"]))

    def test_installed_only(self):
        """bắt-lỗi: FR3.2 a plugin that exists only as an installed copy is listed in `installed_only` (once per harness), not in the rows."""
        code, report, text = self.catalog(self.home())
        self.assertEqual([(i["harness"], i["plugin"], i["skill"]) for i in report["installed_only"]], [("claude", "extra", "gamma")])
        self.assertEqual(report["totals"]["skills"], 2)
        self.assertEqual([r["name"] for r in report["skills"]], ["alpha", "beta"])

    def test_only_the_asked_harnesses_are_read(self):
        code, report, text = self.catalog(self.home(), "codex")
        rows = {r["name"]: r for r in report["skills"]}
        self.assertEqual(rows["alpha"]["installed"]["codex"]["state"], "match")
        self.assertEqual(rows["alpha"]["installed"]["claude"]["state"], "absent")
        self.assertEqual([r["area"] for r in report["roots"] if r["kind"] == "harness"], ["codex"])
        self.assertEqual(report["installed_only"], [])

    def test_exit_codes_follow_the_harness_roots(self):
        """bắt-lỗi: exit 1 when a harness root is error or partial, 0 when all are ok, and the lines of the other roots are still in the report."""
        code, report, text = self.catalog(self.home("bad-json"), "claude")
        self.assertEqual(code, 1, text)
        self.assertEqual([(r["area"], r["status"], r["reasons"]) for r in report["roots"] if r["kind"] == "harness"], [("claude", "error", ["index-unreadable"])])
        self.assertEqual(report["totals"]["roots_not_ok"], 1)
        self.assertEqual({v["state"] for r in report["skills"] for v in r["installed"].values()}, {"absent"})
        outside = UntrustedIndexTests.outside(self)
        code, report, text = self.catalog(self.home("escape", "esc", outside=outside), "claude")
        self.assertEqual(code, 1, text)
        self.assertEqual([r["status"] for r in report["roots"] if r["kind"] == "harness"], ["partial"])
        self.assertEqual({r["name"]: r["installed"]["claude"]["state"] for r in report["skills"]}["alpha"], "match")

    def test_home_flag_is_hidden_and_default_home_is_not_touched_by_tests(self):
        code, out, err = TC.run_catalog("--help")
        self.assertNotIn("--home", out)
        self.assertIn("--installed", out)

    def test_harness_roots_do_not_change_the_doctor_counts(self):
        """bắt-lỗi: the harness roots are not skill roots: skills and doctor counts are the same with and without --installed."""
        plain = self.catalog(self.home(), "claude", None)[1]
        out = self.tmp / "none.json"
        code, so, se = TC.run_catalog("--roots", str(source_tree(self) / "skills"), "--out", str(out))
        bare = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([(r["name"], r["doctor"]) for r in plain["skills"]], [(r["name"], r["doctor"]) for r in bare["skills"]])

    def test_harness_folders_are_never_handed_to_doctor_as_skill_roots(self):
        """bắt-lỗi: the doctor run behind the catalog gets the source roots only: ~/.claude and the like hold copies and would be walked as a whole."""
        seen = []
        real = _engine.doctor.doctor_run

        def spy(roots, *a, **k):
            seen.extend(os.path.normcase(os.fspath(r)) for r in roots)
            return real(roots, *a, **k)
        home = self.home()
        with mock.patch.object(_engine.doctor, "doctor_run", spy):
            code, report, text = self.catalog(home)
        self.assertTrue(seen)
        self.assertEqual([r for r in seen if os.path.normcase(os.fspath(home)) in r], [])

    def test_prefers_a_matching_scope_over_a_differing_one(self):
        """bắt-lỗi: two entries of one plugin (two scopes): the state is `match` when any of them matches."""
        home = self.home()
        other = home / ".claude" / "plugins" / "cache" / "mk" / "demo" / "0.9.0"
        (other / "skills" / "alpha").mkdir(parents=True, exist_ok=True)
        TC.make_skill(other / "skills" / "alpha", "alpha")
        (other / "skills" / "alpha" / "SKILL.md").write_text("---\nname: alpha\ndescription: Different. Use when testing.\n---\n\n# alpha\n", encoding="utf-8")
        self.index_with(home, {"demo@mk": [{"scope": "project", "installPath": other.as_posix(), "version": "0.9.0"},
                                           {"scope": "user", "installPath": (home / ".claude" / "plugins" / "cache" / "mk" / "demo" / "1.0.0").as_posix(), "version": "1.0.0"}]})
        code, report, text = self.catalog(home, "claude")
        self.assertEqual({r["name"]: r["installed"]["claude"] for r in report["skills"]}["alpha"], {"state": "match", "version": "1.0.0", "compare": "byte"})


class SemanticMatchTests(HomeCase):
    """FR3.2 (as of 29/10): `match` is equal bytes OR equal after folding what an adapter rewrites; the JSON says which (`compare`)."""

    catalog = MatchTests.catalog

    def rewrite_alpha(self, home: Path, harness_dir=".gemini/config/plugins/demo/skills/alpha") -> Path:
        """The installed alpha as an adapter would write it: CRLF line ends and a quoted description."""
        skill = home / harness_dir
        text = (skill / "SKILL.md").read_bytes().decode("utf-8").replace("\r\n", "\n")
        text = text.replace("description: Fixture skill alpha. Use when testing installed copies.", 'description: "Fixture skill alpha. Use when testing installed copies."')
        (skill / "SKILL.md").write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        return skill

    def states(self, report, name="alpha"):
        return {h: (v["state"], v["compare"]) for h, v in {r["name"]: r for r in report["skills"]}[name]["installed"].items()}

    def test_adapter_rewrite_is_a_semantic_match(self):
        """bắt-lỗi: RF-10.1 an Antigravity copy with a quoted description and CRLF is `match` with compare `semantic`; byte-equal copies say `byte`."""
        home = self.home()
        self.rewrite_alpha(home)
        code, report, text = self.catalog(home)
        self.assertEqual(self.states(report), {"claude": ("match", "byte"), "codex": ("match", "byte"), "antigravity": ("match", "semantic")})
        self.assertEqual(self.states(report, "beta"), {"claude": ("differ", None), "codex": ("differ", None), "antigravity": ("differ", None)})

    def test_absent_has_no_compare(self):
        code, report, text = self.catalog(self.home(), "codex")
        self.assertEqual(self.states(report), {"claude": ("absent", None), "codex": ("match", "byte"), "antigravity": ("absent", None)})

    def test_a_missing_or_extra_file_in_the_copy_still_differs(self):
        """bắt-lỗi: RF-10.1 a file the adapter dropped, or one it added, is `differ` even when SKILL.md says the same."""
        home = self.home()
        skill = self.rewrite_alpha(home)
        (skill / "extra.md").write_bytes(b"added")
        self.assertEqual(self.states(self.catalog(home)[1])["antigravity"], ("differ", None))
        (skill / "extra.md").unlink()
        tree = source_tree(self)
        (tree / "skills" / "alpha" / "references").mkdir()
        (tree / "skills" / "alpha" / "references" / "r.md").write_bytes(b"only at the source")
        self.assertEqual(self.states(self.catalog(home, tree=tree)[1])["antigravity"], ("differ", None))

    def test_a_changed_word_in_the_copy_still_differs(self):
        home = self.home()
        skill = self.rewrite_alpha(home)
        (skill / "SKILL.md").write_bytes((skill / "SKILL.md").read_bytes().replace(b"Body.", b"Bodies."))
        self.assertEqual(self.states(self.catalog(home)[1])["antigravity"], ("differ", None))

    def test_catalog_md_shows_a_semantic_match_as_khop(self):
        """bắt-lỗi: CATALOG.md has one word for both kinds of match."""
        home = self.home()
        self.rewrite_alpha(home)
        report = self.catalog(home)[1]
        line = [x for x in TC.load_catalog_module().render_md(report).splitlines() if x.startswith("| alpha ")][0]
        self.assertEqual([c.strip() for c in line.split("|")[4:7]], ["khớp", "khớp", "khớp"])

    def test_same_content_for_two_items(self):
        """bắt-lỗi: TK11's shared comparison returns (equal, how): byte, semantic, or (False, None) when different or unreadable."""
        mod = TC.load_catalog_module()
        home = self.home()
        self.rewrite_alpha(home)
        src = source_tree(self) / "skills" / "alpha"
        claude = home / ".claude" / "plugins" / "cache" / "mk" / "demo" / "1.0.0" / "skills" / "alpha"
        gem = home / ".gemini" / "config" / "plugins" / "demo" / "skills" / "alpha"
        beta = home / ".gemini" / "config" / "plugins" / "demo" / "skills" / "beta"
        self.assertEqual(mod.same_content({"path": src}, {"path": claude}), (True, "byte"))
        self.assertEqual(mod.same_content({"path": src.as_posix()}, {"path": gem.as_posix()}), (True, "semantic"))
        self.assertEqual(mod.same_content({"path": src}, {"path": src.parent / "beta"}), (False, None))
        self.assertEqual(mod.same_content({"path": gem}, {"path": beta}), (False, None))
        self.assertEqual(mod.same_content({"path": src}, {"path": self.tmp / "nope"}), (False, None))


class NoManifestTests(HomeCase):
    """RF-10.2: an install with no manifest of its own harness and no `skills/` is reported, not silently absent."""

    def test_codex_install_with_nothing_to_read_is_noted_by_rule(self):
        home = self.home()
        bare = home / ".codex" / "plugins" / "cache" / "mk" / "solo" / "2.2.3"
        (bare / ".claude-plugin").mkdir(parents=True)
        (bare / "SKILL.md").write_bytes(b"---\nname: solo\ndescription: D. Use when x.\n---\n")
        items, root = self.locate("codex", home)
        self.assertNotIn("solo", [i["plugin"] for i in items])
        self.assertIn(("2.2.3", "no-manifest"), {(x["path"].rsplit("/", 1)[-1], x["reason"]) for x in root["skipped_by_rule"]})
        self.assertEqual((root["status"], root["reasons"]), ("ok", []))

    def test_claude_install_with_nothing_to_read_is_noted_by_rule(self):
        home = self.home()
        bare = home / ".claude" / "plugins" / "cache" / "mk" / "bare" / "1.0.0"
        bare.mkdir(parents=True)
        self.index_with(home, {"bare@mk": [{"scope": "user", "installPath": bare.as_posix(), "version": "1.0.0"}]})
        items, root = self.locate("claude", home)
        self.assertEqual(items, [])
        self.assertEqual([x["reason"] for x in root["skipped_by_rule"]], ["no-manifest"])
        self.assertEqual(root["status"], "ok")

    def test_a_plugin_with_skills_but_no_manifest_is_still_read(self):
        home = self.home()
        shutil.rmtree(home / ".codex" / "plugins" / "cache" / "mk" / "demo" / "1.10.0" / ".codex-plugin")
        items, root = self.locate("codex", home)
        self.assertEqual(self.skills(items), [("demo", "alpha", "1.10.0"), ("demo", "beta", "1.10.0")])
        self.assertEqual([x for x in root["skipped_by_rule"] if x["reason"] == "no-manifest"], [])


@unittest.skipUnless(os.name == "nt", "Windows spellings of a path")
class WindowsInstallPathTests(HomeCase):
    """RF-10.4: spellings a Windows index may use for a place outside ~/.claude are refused by name, before any probe (a UNC path would reach the network)."""

    def spellings(self, home: Path) -> list:
        good = home / ".claude" / "plugins" / "cache" / "mk" / "demo" / "1.0.0"
        out = [r"\\localhost\c$\Users\x\.claude\plugins\evil", r"\\?\UNC\server\share\evil", r"\\?\C:\Users\x\evil", r"\\.\C:\Users\x\evil",
               "\\\\?\\" + str(good), "\\\\.\\" + str(good), r"D:\evil" if str(home)[:2].upper() != "D:" else r"E:\evil"]
        try:
            import ctypes
            buffer = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(str(good), buffer, 1024) and buffer.value.lower() != str(good).lower():
                out.append(buffer.value)  # the 8.3 spelling of a real folder: another spelling, so refused
        except (AttributeError, OSError):
            pass
        return out

    def test_windows_spellings_are_refused_before_any_probe(self):
        home = self.home()
        top = os.path.normcase(os.path.abspath(home / ".claude"))
        fs = _engine.fs
        probed = []

        def guard(real):
            def probe(path, *a, **k):
                where = os.path.normcase(os.path.abspath(os.fspath(path)))
                if not (where == top or where.startswith(top + os.sep)):
                    probed.append(where)
                return real(path, *a, **k)
            return probe
        good = home / ".claude" / "plugins" / "cache" / "mk" / "demo" / "1.0.0"
        for spelling in self.spellings(home):
            with self.subTest(spelling=spelling):
                self.index_with(home, {"demo@mk": [{"scope": "user", "installPath": good.as_posix(), "version": "1.0.0"}],
                                       "evil@mk": [{"scope": "user", "installPath": spelling, "version": "9"}]})
                del probed[:]
                with mock.patch.object(fs, "link_in_chain", guard(fs.link_in_chain)), mock.patch.object(fs, "is_link", guard(fs.is_link)), \
                        mock.patch.object(fs, "path_is_cloud", guard(fs.path_is_cloud)), mock.patch.object(fs, "valid_resolved_under", guard(fs.valid_resolved_under)):
                    items, root = self.locate("claude", home)
                self.assertEqual(probed, [])
                self.assertEqual(self.skills(items), [("demo", "alpha", "1.0.0"), ("demo", "beta", "1.0.0")])
                self.assertEqual((root["status"], root["reasons"]), ("partial", ["install-path-escape"]))


class IndexLimitTests(HomeCase):
    def test_entries_beyond_the_per_plugin_limit_are_reported(self):
        """bắt-lỗi: RF-10.9 entries of one plugin beyond MANIFEST_SKILLS_MAX are not read, and the root says `limit` (partial), not silence."""
        home = self.home()
        good = (home / ".claude" / "plugins" / "cache" / "mk" / "demo" / "1.0.0").as_posix()
        entries = [{"scope": "user", "installPath": good, "version": "1.0.0"}] * 3
        self.index_with(home, {"demo@mk": entries})
        with mock.patch.object(_engine.const, "MANIFEST_SKILLS_MAX", 2):
            items, root = self.locate("claude", home)
        self.assertEqual((root["status"], root["reasons"]), ("partial", ["limit"]))
        with mock.patch.object(_engine.const, "MANIFEST_SKILLS_MAX", 3):
            items, root = self.locate("claude", home)
        self.assertEqual((root["status"], root["reasons"]), ("ok", []))


class EvalsCatalogRecursionTests(TC.TmpCase):
    def test_deeply_nested_evals_catalog_does_not_crash(self):
        """bắt-lỗi: RF-9.1 an evals/catalog.json nested a few hundred thousand levels deep (under the size limit) is not valid data: model_evaluated is null,
        one NOTE says why, and the catalog still comes out."""
        plugin = self.tmp / "deep"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "deep", "version": "1.0.0"}), encoding="utf-8")
        TC.make_skill(plugin / "skills" / "one")
        (plugin / "evals").mkdir()
        (plugin / "evals" / "catalog.json").write_bytes(b"[" * 400000)
        out = self.tmp / "deep.json"
        code, so, se = TC.run_catalog("--roots", str(plugin / "skills"), "--out", str(out))
        self.assertEqual(code, 0, se)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([r["model_evaluated"] for r in report["skills"]], [None])
        self.assertIn("NOTE", se)
        self.assertIn("catalog.json", se)


if __name__ == "__main__":
    unittest.main()
