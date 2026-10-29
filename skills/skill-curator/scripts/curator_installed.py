"""The copies of plugins installed in each harness, found by three locators (SPR-04 TK10, FR3).

Internal module of `skill-curator` (`curator_catalog`); do not run it. It uses the engine modules `studio_*` that the loader has already put in `sys.modules`.
Read-only. It reads only: Claude's `plugins/installed_plugins.json` and the install folders it names, the folders `plugins/cache/<market>/<plugin>/<version>`
of Codex, and `config/plugins/<plugin>/skills` of Antigravity. It never walks a whole `cache/`, never reads a harness configuration file, and every path is
judged by name, link, cloud attribute and real place **before** it is listed or opened.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import studio_const as C
import studio_doctor as doctor
import studio_fs as fs
import studio_roots as roots_mod

HARNESS_BASE = {"claude": ".claude", "codex": ".codex", "antigravity": ".gemini"}
INDEX_MAX = 1024 * 1024  # the Claude index above this is refused unread (FR3.3)
INDEX_PLUGINS_MAX = 5000  # plugins of the index that are looked at; the rest is reported as `limit`
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
_ESCAPE = "install-path-escape"


def _posix(path) -> str:
    return os.fspath(path).replace("\\", "/")


def _semver_key(name: str):
    """A sortable key for a semver folder name, or None when the name is not one (a pre-release sorts below its release, numbers below words)."""
    found = SEMVER.match(name)
    if not found:
        return None
    pre = tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in found.group(4).split(".")) if found.group(4) else ()
    return (int(found.group(1)), int(found.group(2)), int(found.group(3)), 0 if found.group(4) else 1, pre)


def _problem(path: Path, base: Path, markers: tuple) -> str | None:
    """Why `path` may not be used as a folder of the harness at `base` (a reason word of the roots table), else None. Names and lstat only, until the very
    last test, which resolves the path once everything before it has shown that it holds no link and no zone. Order: outside by spelling, zone by name,
    link anywhere between `base` and the path, cloud placeholder, real place outside `base`."""
    given = os.path.normcase(os.path.abspath(os.fspath(path)))
    top = os.path.normcase(os.path.abspath(os.fspath(base))).rstrip(os.sep)
    if not given.startswith(top + os.sep):
        return _ESCAPE
    zone = fs.zone_reason(path, markers)
    if zone:
        return "cloud-name" if zone == "cloud" else zone
    if fs.link_in_chain(path, base) is not None:
        return "link"
    if fs.path_is_cloud(path):
        return "cloud"
    if not fs.valid_resolved_under(path, base):
        return _ESCAPE
    return None


def _entry_problem(path, base: Path, markers: tuple) -> str | None:
    """`_problem` for a path an index gives as text: anything wrong with it is `install-path-escape`, one reason for every way an index can lie."""
    if not isinstance(path, str) or not path.strip() or "\x00" in path or not os.path.isabs(path):
        return _ESCAPE
    return _ESCAPE if _problem(Path(path), base, markers) else None


def _usable_dir(path: Path) -> bool:
    return fs._is_dir_quiet(path)


def _children(folder: Path, root: dict) -> list:
    """The sorted names of the folders (and links, which the caller refuses) directly in `folder`; an unreadable folder is noted on the root."""
    try:
        with os.scandir(folder) as scan:
            names = sorted(e.name for e in scan if e.is_dir(follow_symlinks=False) or e.is_symlink())
    except OSError:
        roots_mod.note_skip(root, _posix(folder), "unreadable")
        return []
    return names


def _default_skills(plugin: Path, root: dict, markers: tuple) -> list:
    """The skill folders under `<plugin>/skills` (the place a plugin without a manifest, or an Antigravity plugin, keeps them)."""
    target = plugin / "skills"
    if not os.path.lexists(target):
        return []
    if fs.is_link(target) or fs.path_is_cloud(target) or not _usable_dir(target):
        roots_mod.note_skip(root, _posix(target), "link" if fs.is_link(target) else "unreadable")
        return []
    found, skipped = doctor.iter_skill_dirs([target], False, tuple(m for m in markers if m not in C.CLOUD_MARKERS))
    for item in roots_mod._rule_names(skipped, tuple(m for m in markers if m not in C.CLOUD_MARKERS)):
        roots_mod.note_skip(root, item["path"], item["reason"])
    return found


def _plugin_skills(plugin: Path, manifest_dir: str, root: dict, markers: tuple, budget: dict) -> list:
    """The skill folders of an installed plugin: those its own manifest declares; with no manifest at all, the `skills/` folder."""
    if not os.path.lexists(plugin / manifest_dir / "plugin.json"):
        if not os.path.lexists(plugin / "skills"):  # nothing this harness could read: say so, or the plugin looks like it is not installed at all
            roots_mod.note_skip(root, _posix(plugin), "no-manifest")
            return []
        return _default_skills(plugin, root, markers)
    _, skills, skipped = roots_mod._plugin_scan(plugin, markers, budget, manifest_dir)
    for item in skipped:
        roots_mod.note_skip(root, item["path"], item["reason"])
    return skills


def _record(items: list, root: dict, harness: str, plugin: str, skills: list, version, scope, home: Path | None = None) -> None:
    """Append one Installed per skill folder. A folder that is the plugin's own (`home`: a plugin that is one skill at its root) takes the plugin's name:
    the install folder is called after a version, while at the source the folder is the plugin's own."""
    for folder in skills:
        if len(items) >= C.DOCTOR_MAX_SKILLS:
            roots_mod.note_skip(root, _posix(folder), "limit")
            return
        items.append({"harness": harness, "plugin": plugin, "skill": plugin if home is not None and folder == home else folder.name, "path": _posix(folder), "version": version, "scope": scope})


def _text(value, limit: int = 200):
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def _claude(base: Path, root: dict, markers: tuple, items: list) -> None:
    index = base / "plugins" / "installed_plugins.json"
    if not os.path.lexists(index):
        root["status"], root["reasons"] = "error", ["index-missing"]
        return
    if fs.link_in_chain(index, base) is not None:  # `plugins/` or the index itself is a link
        root["status"], root["reasons"] = "error", ["link"]
        return
    try:
        data = roots_mod._read_json(index, INDEX_MAX, markers, base)
    except roots_mod.RootError as exc:
        root["status"], root["reasons"] = "error", ["index-too-big" if exc.reason == "limit" else "index-unreadable" if exc.reason == "unreadable" else exc.reason]
        return
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        root["status"], root["reasons"] = "error", ["index-unreadable"]
        return
    budget = {"left": C.DOCTOR_MAX_DIRS, "cut": False}
    for count, (key, entries) in enumerate(plugins.items()):
        if count >= INDEX_PLUGINS_MAX:
            roots_mod.note_skip(root, _posix(index), "limit")
            break
        name = _text(key.rsplit("@", 1)[0] if isinstance(key, str) else None)
        if name is None or not isinstance(entries, list):
            roots_mod.note_skip(root, _posix(index), _ESCAPE)
            continue
        if len(entries) > C.MANIFEST_SKILLS_MAX:  # the entries past the limit are not read: said, not silent
            roots_mod.note_skip(root, _posix(index), "limit")
        for entry in entries[:C.MANIFEST_SKILLS_MAX]:
            where = entry.get("installPath") if isinstance(entry, dict) else None
            if _entry_problem(where, base, markers):
                roots_mod.note_skip(root, _posix(index), _ESCAPE)
                continue
            plugin = Path(os.path.abspath(where))
            if not _usable_dir(plugin):
                roots_mod.note_skip(root, _posix(plugin), "unreadable")
                continue
            _record(items, root, "claude", name, _plugin_skills(plugin, ".claude-plugin", root, markers, budget), _text(entry.get("version")), _text(entry.get("scope")), plugin)


def _listing(folder: Path, base: Path, root: dict, markers: tuple) -> list:
    """The child folders of `folder` that pass `_problem`; the others are noted on the root by their reason."""
    found = []
    for name in _children(folder, root):
        child = folder / name
        reason = _problem(child, base, markers)
        if reason:
            roots_mod.note_skip(root, _posix(child), reason)
        else:
            found.append(child)
    return found


def _locator_folder(folder: Path, base: Path, root: dict, markers: tuple) -> bool:
    """True when the folder a locator lists is usable; else the root becomes `error` (`not-found`, or why the folder may not be used)."""
    reason = _problem(folder, base, markers) if os.path.lexists(folder) else "not-found"
    if reason is None and not _usable_dir(folder):
        reason = "not-found"
    if reason:
        root["status"], root["reasons"] = "error", [reason]
    return reason is None


def _codex(base: Path, root: dict, markers: tuple, items: list) -> None:
    cache = base / "plugins" / "cache"
    if not _locator_folder(cache, base, root, markers):
        return
    budget = {"left": C.DOCTOR_MAX_DIRS, "cut": False}
    for market in _listing(cache, base, root, markers):
        for plugin in _listing(market, base, root, markers):
            versions = []
            for name in _children(plugin, root):
                key = _semver_key(name)
                if key is None:
                    roots_mod.note_skip(root, _posix(plugin / name), "non-semver")
                else:
                    versions.append((key, name))
            if not versions:
                continue
            versions.sort()
            for _, name in versions[:-1]:
                roots_mod.note_skip(root, _posix(plugin / name), "other-version")
            top = plugin / versions[-1][1]
            reason = _problem(top, base, markers)
            if reason:
                roots_mod.note_skip(root, _posix(top), reason)
                continue
            _record(items, root, "codex", plugin.name, _plugin_skills(top, ".codex-plugin", root, markers, budget), versions[-1][1], None, top)


def _antigravity(base: Path, root: dict, markers: tuple, items: list) -> None:
    plugins = base / "config" / "plugins"
    if not _locator_folder(plugins, base, root, markers):
        return
    for plugin in _listing(plugins, base, root, markers):
        version = None
        try:
            data = roots_mod._read_json(plugin / "plugin.json", C.MANIFEST_MAX, markers, base) if os.path.lexists(plugin / "plugin.json") else None
            version = _text(data.get("version")) if isinstance(data, dict) else None
        except roots_mod.RootError as exc:
            roots_mod.note_skip(root, _posix(plugin / "plugin.json"), exc.reason)
        _record(items, root, "antigravity", plugin.name, _default_skills(plugin, root, markers), version, None)


_LOCATORS = {"claude": _claude, "codex": _codex, "antigravity": _antigravity}


def locate(harness: str, home: Path, markers: tuple = C.CLOUD_MARKERS) -> tuple:
    """(Installed records, Root) of the copies installed in `harness` below `home`. The Root is {kind: harness, area: <harness>} whose status is `ok`;
    `partial` when an entry was left out that no rule asked for (a link, a zone, a place outside the harness folder, a manifest that leaves its plugin);
    `error` when the locator itself is not usable (no harness folder, an index that is missing, above 1 MB or not JSON), and then nothing is listed."""
    base = Path(os.path.abspath(os.fspath(home))) / HARNESS_BASE[harness]
    root = roots_mod._new_root(base, "harness", harness)
    items: list = []
    reason = fs.zone_reason(base, markers)
    if not reason and os.path.lexists(base):
        reason = "link" if fs.is_link(base) else "cloud" if fs.path_is_cloud(base) else None
    if reason:
        root["status"], root["reasons"] = "error", [reason]
    elif not _usable_dir(base):
        root["status"], root["reasons"] = "error", ["not-found"]
    else:
        _LOCATORS[harness](base, root, markers, items)
    if root["status"] == "error":
        items = []
    return items, root
