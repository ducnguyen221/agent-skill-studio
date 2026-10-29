"""Scan roots of an OpcOS tree: paths.json, the plugins below it, the skill folders their manifests declare, and a hash of a skill tree (SPR-04 TK5).

Internal module of `studio.py`; do not run it. It reaches the other studio modules through the module object (FR4.5).
Read-only and link-safe like the rest of the engine: every path goes through the zone, link and cloud checks before anything is opened, a
manifest can never lead the scan outside its plugin, and the only environment variable read is OPCOS_ROOT.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Mapping

import studio_const as C
import studio_doctor as doctor
import studio_fs as fs

SEMANTIC_TEXT_SUFFIXES = frozenset({".md", ".txt", ".py", ".json", ".yaml", ".yml", ".csv", ".toml", ".ps1", ".sh", ".js", ".ts", ".html", ".css"})  # CRLF is folded to LF in these by tree_digest_semantic
TREE_FILE_MAX = 25 * 1024 * 1024  # a file above this is not hashed: the tree has no hash (tree_sha256 returns None)
# Why a path was left out *by a rule* (FR2.2): the root stays ok. Any other reason (cloud, link, secret-zone, manifest-escape, install-path-escape, limit, unreadable) makes it partial.
SKIPPED_BY_RULE = frozenset({"vendor", "excluded", "cloud-name", "non-semver", "other-version", "no-manifest"})
# Folders below a skill that hold its material, never another skill (05-forensics/05a-reading is a skill, 05-forensics/assets/skill-template is a template).
_NOT_NESTED = frozenset(name.casefold() for name in C.ST8_ALLOWED_DIRS | C.SKIP_DIRS) | {"examples", "fixtures", "templates", "docs", "node_modules", "dist", "build"}
_EXCLUDED_NAMES = frozenset(part for part in C.DOCTOR_EXCLUDE_PARTS if "/" not in part)  # .worktrees, .tmp, node_modules...


class RootError(Exception):
    """A source of roots that cannot be used. `reason` is one of the reason words of the roots table (cloud, link, secret-zone, limit, unreadable)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _posix(path) -> str:
    return os.fspath(path).replace("\\", "/")


def _extra(markers: tuple) -> tuple:
    """The markers beyond the built-in ones: iter_skill_dirs takes only those (`--skip-marker`)."""
    return tuple(m for m in markers if m not in C.CLOUD_MARKERS)


def _plain_file_problem(path: Path, markers: tuple, limit: int, base: Path) -> tuple:
    """(reason, text) why `path` may not be read, else None. Decided by name, link and cloud attributes first, size last; nothing is opened.
    `base` is the trusted folder the file belongs to: a link or junction at the file or at any folder from `base` down to it is refused (RF-S1), and so is
    a real path (after resolving) in a cloud or secret zone, which the spelling of the path alone would not show."""
    if fs.input_name_problem(path, markers):
        reason = fs.zone_reason(path, markers) or "unreadable"
        return reason, "its name or place is refused (%s)" % reason
    if fs.link_in_chain(path, base) is not None:
        return "link", "is a link or lies below one; not followed"
    try:
        real = path.resolve()
    except (OSError, RuntimeError):
        return "unreadable", "cannot be resolved; not read"
    reason = fs.zone_reason(real, markers)
    if reason:
        return reason, "its real path is in a %s place; not read" % reason
    if fs.path_is_cloud(path):
        return "cloud", "is a cloud placeholder; not read"
    try:
        info = os.lstat(path)
    except OSError:
        return "unreadable", "cannot be read"
    if not stat.S_ISREG(info.st_mode):
        return "unreadable", "is not a regular file"
    if info.st_size > limit:
        return "limit", "is above %d bytes; not read" % limit
    return None


def _read_json(path: Path, limit: int, markers: tuple, base: Path, single_link: bool = True):
    """The JSON value of a small plain file below the trusted folder `base`; RootError (cloud, secret-zone, link, limit, unreadable) otherwise.
    At most `limit` bytes are read. A file with a second name (hard link) is refused unless `single_link` is False (FR6.1)."""
    problem = _plain_file_problem(path, markers, limit, base)
    if problem:
        raise RootError(problem[0], "%s %s (%s)" % (path.name, problem[1], problem[0]))
    try:
        with fs.open_nofollow_read(path, expect_stat=os.lstat(path), single_link=single_link, anchor=base) as handle:
            data = handle.read(limit + 1)
    except fs.UnsafeOpen as exc:
        if "hard link" in str(exc):
            raise RootError("link", "%s has more than one name (hard link); not read (link)" % path.name)
        if "link" in str(exc) or "reparse" in str(exc):
            raise RootError("link", "%s is a link; not read (link)" % path.name)
        raise RootError("unreadable", "%s cannot be read (%s)" % (path.name, "not a plain file or changed while opening"))
    except OSError as exc:
        raise RootError("unreadable", "%s cannot be read (%s)" % (path.name, exc.strerror or type(exc).__name__))
    if len(data) > limit:
        raise RootError("limit", "%s is above %d bytes; not read (limit)" % (path.name, limit))
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        raise RootError("unreadable", "%s is not JSON (unreadable)" % path.name)


def find_paths_json(start: Path, env: Mapping[str, str], markers: tuple = C.CLOUD_MARKERS) -> Path | None:
    """`$OPCOS_ROOT/paths.json` when there is one, else the first paths.json in `start` or up to PATHS_JSON_UP folders above it; None when there is none.
    A file that is there but may not be used (above PATHS_JSON_MAX, a link, a cloud placeholder, not a regular file, in a cloud or secret zone) raises
    RootError with the reason: the search does not go on to a farther file. A folder of the walk up whose name is a zone is not looked into."""
    candidates = []
    given = env.get("OPCOS_ROOT") if env else None
    if isinstance(given, str) and given.strip():
        candidates.append((Path(os.path.abspath(os.path.expanduser(given.strip()))), True))
    here = Path(os.path.abspath(os.fspath(start)))
    for level, folder in enumerate([here, *here.parents]):
        if level > C.PATHS_JSON_UP:
            break
        candidates.append((folder, False))
    for folder, explicit in candidates:
        candidate = folder / "paths.json"
        reason = fs.zone_reason(candidate, markers) or ("cloud" if fs.path_is_cloud(folder) else None)  # by name and one lstat of the folder; the file is touched after
        if reason:
            if explicit:
                raise RootError(reason, "paths.json of OPCOS_ROOT is in a %s place; not read (%s)" % (reason, reason))
            continue
        try:
            os.lstat(candidate)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            raise RootError("unreadable", "%s cannot be probed (unreadable)" % candidate)
        problem = _plain_file_problem(candidate, markers, C.PATHS_JSON_MAX, folder)  # folder = OPCOS_ROOT (or the folder of the walk up): a link there is refused
        if problem:
            raise RootError(problem[0], "%s %s (%s)" % (candidate, problem[1], problem[0]))
        return candidate
    return None


def _rel_path(base: Path, rel) -> Path | None:
    """`rel` (an area's rel_path) below `base`, else None: it must be a non-empty string, relative to the folder of paths.json (not absolute, not
    starting with ~, no `..`, no drive or stream colon, no device or 8.3 name)."""
    if not isinstance(rel, str) or not rel.strip() or "\x00" in rel or rel[0] in "~/\\" or os.path.isabs(rel):
        return None
    parts = [part for part in re.split(r"[\\/]+", rel) if part not in ("", ".")]
    if any(part == ".." or fs.unsafe_windows_name(part) for part in parts):
        return None
    return base.joinpath(*parts) if parts else base


def _new_root(path, kind: str, area: str, status: str = "ok", reasons: list | None = None) -> dict:
    return {"path": _posix(path) if path else "", "kind": kind, "area": area, "status": status, "reasons": list(reasons or []), "skipped_by_rule": []}


def _make_root(path: Path, kind: str, area: str, markers: tuple, base: Path, optional: bool = False) -> dict | None:
    """The Root for a folder: `error` unless it is a real local folder that is neither too broad nor in a zone. `optional` and absent: None, not an error."""
    reason = fs.zone_reason(path, markers)
    if reason:
        return _new_root(path, kind, area, "error", [reason])
    if optional and not os.path.lexists(path):
        return None
    if fs.root_too_broad(path, markers):
        return _new_root(path, kind, area, "error", ["too-broad"])
    if fs.link_in_chain(path, base) is not None:  # a link at the root or anywhere between paths.json and it: unusable as a whole, so error rather than partial
        return _new_root(path, kind, area, "error", ["link"])
    if fs.path_is_cloud(path):
        return _new_root(path, kind, area, "error", ["cloud"])
    if not fs._is_dir_quiet(path):
        return _new_root(path, kind, area, "error", ["not-found"])
    return _new_root(path, kind, area)


def opcos_roots(paths_file: Path, include_system_plugins: bool = True, markers: tuple = C.CLOUD_MARKERS) -> list:
    """The scan roots named by paths.json: area `opcos-plugin` -> one `plugin` root, area `plugins` -> a `plugin-parent` root, and, with
    `include_system_plugins`, `plugins/` inside the `system` area when that folder exists -> a `plugin-parent` root of area `system-plugins`.
    Areas are looked up by `id`; `rel_path` is read relative to the folder holding paths.json and the variables an area names are never used.
    Each root is {path, kind, area, status, reasons, skipped_by_rule}; here the status is `ok` or `error` (collect_skills adds `partial`). A paths.json
    that cannot be read raises RootError."""
    paths_file = Path(os.path.abspath(os.fspath(paths_file)))
    data = _read_json(paths_file, C.PATHS_JSON_MAX, markers, paths_file.parent, single_link=False)
    areas = data.get("areas") if isinstance(data, dict) else None
    if not isinstance(areas, list):
        raise RootError("unreadable", "paths.json has no areas list (unreadable)")
    by_id: dict = {}
    for item in areas:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            by_id.setdefault(item["id"], item)
    base = paths_file.parent
    roots = []
    for area_id, kind, area in (("opcos-plugin", "plugin", "opcos-plugin"), ("plugins", "plugin-parent", "plugins")):
        entry = by_id.get(area_id)
        if entry is None:
            roots.append(_new_root(None, kind, area, "error", ["area-missing"]))
            continue
        path = _rel_path(base, entry.get("rel_path"))
        roots.append(_new_root(None, kind, area, "error", ["rel-path-refused"]) if path is None else _make_root(path, kind, area, markers, base))
    if include_system_plugins and "system" in by_id:
        system = _rel_path(base, by_id["system"].get("rel_path"))
        if system is not None:
            found = _make_root(system / "plugins", "plugin-parent", "system-plugins", markers, base, optional=True)
            if found is not None:
                roots.append(found)
    return roots


def note_skip(root: dict, path: str, reason: str) -> None:
    """Record that `path` was left out of `root` for `reason`: by rule it is listed in skipped_by_rule and the root stays as it is; any other reason adds the
    reason word to `reasons` and turns an `ok` root into `partial` (an `error` root stays an error)."""
    if reason in SKIPPED_BY_RULE:
        entry = {"path": path, "reason": reason}
        if entry not in root["skipped_by_rule"]:
            root["skipped_by_rule"].append(entry)
        return
    if reason not in root["reasons"]:
        root["reasons"].append(reason)
    if root["status"] == "ok":
        root["status"] = "partial"


def _rule_names(skipped: list, extra: tuple) -> list:
    """`skipped` with `cloud` turned into `cloud-name` where the folder's own name carries the marker (a rule: the root stays ok); a placeholder keeps `cloud`."""
    markers = (*C.CLOUD_MARKERS, *extra)
    return [dict(item, reason="cloud-name") if item["reason"] == "cloud" and fs.zone_named(item["path"].rsplit("/", 1)[-1], markers) else item for item in skipped]


def _declared_dir(plugin: Path, entry, markers: tuple) -> tuple:
    """(folder, None) for a `skills` entry of a manifest that stays inside `plugin`, else (None, reason). `./` and `.` are the plugin folder itself."""
    if not isinstance(entry, str) or not entry.strip() or "\x00" in entry or entry[0] in "~/\\" or os.path.isabs(entry):
        return None, "manifest-escape"
    parts = [part for part in re.split(r"[\\/]+", entry) if part not in ("", ".")]
    if any(part == ".." or fs.unsafe_windows_name(part) for part in parts):
        return None, "manifest-escape"
    target = plugin.joinpath(*parts) if parts else plugin
    zone = fs.zone_reason(target, markers)  # by name: nothing is touched
    if zone:
        return None, "cloud-name" if zone == "cloud" else zone
    if fs.link_in_chain(target, plugin) is not None:
        return None, "manifest-escape"
    if fs.path_is_cloud(target):
        return None, "cloud"
    return target, None


def _nested_skills(skill: Path, extra: tuple, skipped: list, budget: dict, depth: int = 0) -> list:
    """Skills below a skill. iter_skill_dirs stops at the first SKILL.md, but a skill may hold skills (05-forensics holds 05a..05d), so the folders of a skill
    that are not material (references, scripts, assets, tests, evals, examples, fixtures..., hidden and superseded folders) are scanned one by one.
    `budget` ({left, cut}) is shared by every call of one scan: each folder listed spends one of DOCTOR_MAX_DIRS and what is left unscanned is reported once as `limit`."""
    found = []
    if depth >= C.DOCTOR_MAX_SKILL_DEPTH:
        return found
    if budget["left"] <= 0:
        if not budget["cut"]:
            budget["cut"] = True
            skipped.append({"path": _posix(skill), "reason": "limit"})
        return found
    budget["left"] -= 1
    try:
        with os.scandir(skill) as scan:
            entries = sorted(scan, key=lambda e: e.name)
    except OSError:
        skipped.append({"path": _posix(skill), "reason": "unreadable"})
        return found
    for entry in entries:
        low = entry.name.casefold()
        if entry.name.startswith(".") or low in _NOT_NESTED or low.startswith("superseded"):
            continue
        try:
            if not (entry.is_dir(follow_symlinks=False) or entry.is_symlink()):
                continue
        except OSError:
            continue
        child = skill / entry.name
        reason = fs.zone_reason(child, (*C.CLOUD_MARKERS, *extra))
        if reason:
            skipped.append({"path": _posix(child), "reason": "cloud-name" if reason == "cloud" else reason})
        elif fs.entry_is_cloud(entry):
            skipped.append({"path": _posix(child), "reason": "cloud"})
        elif entry.is_symlink() or fs.is_link(child):
            skipped.append({"path": _posix(child), "reason": "link"})
        else:
            if budget["left"] <= 0:
                _nested_skills(child, extra, skipped, budget, depth + 1)  # reports the limit once
                continue
            budget["left"] -= 1
            below, skp = doctor.iter_skill_dirs([child], False, extra)
            skipped.extend(_rule_names(skp, extra))
            for item in below:
                found.append(item)
                found.extend(_nested_skills(item, extra, skipped, budget, depth + 1))
    return found


def _plugin_scan(plugin: Path, markers: tuple, budget: dict | None = None, manifest_dir: str = ".claude-plugin") -> tuple:
    """(plugin name, skill folders, skipped[{path, reason}]) of one plugin folder, read from its `<manifest_dir>/plugin.json` (`.claude-plugin`; an installed Codex copy has `.codex-plugin`)."""
    manifest = plugin / manifest_dir / "plugin.json"
    skipped: list = []
    budget = {"left": C.DOCTOR_MAX_DIRS, "cut": False} if budget is None else budget
    if fs.link_in_chain(manifest, plugin) is not None:
        return plugin.name, [], [{"path": _posix(manifest), "reason": "link"}]
    try:
        data = _read_json(manifest, C.MANIFEST_MAX, markers, plugin)
    except RootError as exc:
        return plugin.name, [], [{"path": _posix(manifest), "reason": exc.reason}]
    if not isinstance(data, dict):
        return plugin.name, [], [{"path": _posix(manifest), "reason": "unreadable"}]
    name = data.get("name") if isinstance(data.get("name"), str) and data["name"].strip() and len(data["name"]) <= 200 else plugin.name
    explicit = "skills" in data
    raw = data.get("skills", "skills/")
    if isinstance(raw, str):
        entries = [raw]
    elif isinstance(raw, list):
        entries = raw
        if len(entries) > C.MANIFEST_SKILLS_MAX:
            entries = entries[:C.MANIFEST_SKILLS_MAX]
            skipped.append({"path": _posix(manifest), "reason": "limit"})
    else:
        return name, [], [{"path": _posix(manifest), "reason": "unreadable"}]
    extra, skills, seen = _extra(markers), [], set()

    def add(folder: Path) -> None:
        key = os.path.normcase(os.fspath(folder))
        if key not in seen:
            seen.add(key)
            skills.append(folder)

    for entry in entries:
        target, reason = _declared_dir(plugin, entry, markers)
        if target is None:
            skipped.append({"path": _posix(manifest), "reason": reason})
            continue
        if target == plugin:  # `./`: the plugin folder is the skill itself; the tests, examples and templates around it are not scanned
            marker = plugin / "SKILL.md"
            if fs.is_link(marker) or fs.path_is_cloud(marker):
                skipped.append({"path": _posix(marker), "reason": "link" if fs.is_link(marker) else "cloud"})
            elif os.path.isfile(marker):
                add(plugin)
            continue
        if not fs._is_dir_quiet(target):
            if explicit and not os.path.lexists(target):
                skipped.append({"path": _posix(target), "reason": "unreadable"})  # a declared folder that is not there
            elif os.path.lexists(target):
                skipped.append({"path": _posix(target), "reason": "link" if fs.is_link(target) else "unreadable"})
            continue
        found, skp = doctor.iter_skill_dirs([target], False, extra)
        skipped.extend(_rule_names(skp, extra))
        for folder in found:
            add(folder)
            for inner in _nested_skills(folder, extra, skipped, budget):
                add(inner)
    return name, skills, skipped


def plugin_skill_dirs(plugin: Path, markers: tuple = C.CLOUD_MARKERS) -> tuple:
    """(skill folders, skipped[{path, reason}]) of a plugin folder: those under the folders its manifest key `skills` declares (a string or a list of up to
    MANIFEST_SKILLS_MAX strings; missing means `skills/`; `./` is the plugin folder itself). A declared path that is absolute, starts with ~, has `..`,
    leaves the plugin or passes through a link is dropped with reason manifest-escape and never listed; a manifest above MANIFEST_MAX or not JSON
    gives no skills and a `limit` or `unreadable` line. Skills inside skills are found too (05-forensics/05a-reading)."""
    _, skills, skipped = _plugin_scan(Path(os.path.abspath(os.fspath(plugin))), markers)
    return skills, skipped


def _plugin_children(root: dict, parent: Path, markers: tuple, skipped: list) -> list:
    """The plugin folders directly under a plugin-parent root: a folder with `.claude-plugin/plugin.json`. A name decides first (vendor-*, a cloud marker,
    a hidden or tooling folder), then links and cloud attributes; a file or a folder without a manifest is not a plugin and is not mentioned."""
    found = []
    try:
        with os.scandir(parent) as scan:
            entries = sorted(scan, key=lambda e: e.name)
    except OSError:
        note_skip(root, _posix(parent), "unreadable")
        skipped.append({"path": _posix(parent), "reason": "unreadable"})
        return found
    for entry in entries:
        child, low = parent / entry.name, entry.name.casefold()
        try:
            if not (entry.is_dir(follow_symlinks=False) or entry.is_symlink()):
                continue
        except OSError:
            continue
        reason = fs.zone_reason(child, markers)
        if reason == "cloud":
            reason = "cloud-name"
        elif not reason and low.startswith("vendor-"):
            reason = "vendor"
        elif not reason and (entry.name in _EXCLUDED_NAMES or entry.name.startswith(".")):
            if entry.name.lower() in C.DOCTOR_PRUNE_SILENT:
                continue
            reason = "excluded"
        elif not reason and fs.entry_is_cloud(entry):
            reason = "cloud"
        elif not reason and (entry.is_symlink() or fs.is_link(child)):
            reason = "link"
        if reason:
            note_skip(root, _posix(child), reason)
            skipped.append({"path": _posix(child), "reason": reason})
            continue
        try:
            os.lstat(child / ".claude-plugin" / "plugin.json")
        except OSError:
            continue
        found.append(child)
    return found


def collect_skills(roots: list, markers: tuple = C.CLOUD_MARKERS) -> tuple:
    """(skills, skipped) over the roots that are not `error`. A skill is {path, repo, plugin, root}: `repo` is the plugin folder's name, `plugin` the `name` of
    its manifest, `root` the root's path. `skipped` lists every path left out, as {path, reason}; each root is updated in place (reasons, skipped_by_rule,
    and `partial` when something was left out that no rule asked for). A `plugin` root without a manifest becomes an `error`."""
    skills, skipped, seen, limited = [], [], set(), False
    budget = {"left": C.DOCTOR_MAX_DIRS, "cut": False}  # one folder budget for the whole run
    for root in roots:
        if root["status"] == "error":
            continue
        base = Path(root["path"])
        if root["kind"] == "plugin":
            try:
                os.lstat(base / ".claude-plugin" / "plugin.json")
            except OSError:
                root["status"], root["reasons"] = "error", ["no-manifest"]
                continue
            plugins = [base]
        else:
            plugins = _plugin_children(root, base, markers, skipped)
        for plugin in plugins:
            name, folders, skp = _plugin_scan(plugin, markers, budget)
            for item in skp:
                note_skip(root, item["path"], item["reason"])
                skipped.append(item)
            for folder in folders:
                key = os.path.normcase(os.fspath(folder))
                if key in seen:
                    continue
                if len(skills) >= C.DOCTOR_MAX_SKILLS:
                    if not limited:
                        limited = True
                        note_skip(root, _posix(folder), "limit")
                        skipped.append({"path": _posix(folder), "reason": "limit"})
                    continue
                seen.add(key)
                skills.append({"path": folder, "repo": plugin.name, "plugin": name, "root": root["path"]})
    skills.sort(key=lambda s: os.path.normcase(os.fspath(s["path"])))
    return skills, skipped


def _file_sha256(path: Path, anchor: Path | None = None) -> str | None:
    """SHA-256 of the file's bytes (read in blocks through open_nofollow_read, no CRLF folding), None above TREE_FILE_MAX or when it cannot be opened safely."""
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > TREE_FILE_MAX:
            return None
        digest, total = hashlib.sha256(), 0
        with fs.open_nofollow_read(path, expect_stat=info, single_link=False, anchor=anchor) as handle:
            while True:
                block = handle.read(1 << 20)
                if not block:
                    return digest.hexdigest()
                total += len(block)
                if total > TREE_FILE_MAX:
                    return None
                digest.update(block)
    except OSError:  # UnsafeOpen is one
        return None


def _file_bytes(path: Path, anchor: Path | None = None) -> bytes | None:
    """The bytes of a regular file, read through open_nofollow_read; None above TREE_FILE_MAX or when it cannot be opened safely (the rules of _file_sha256)."""
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > TREE_FILE_MAX:
            return None
        with fs.open_nofollow_read(path, expect_stat=info, single_link=False, anchor=anchor) as handle:
            data = handle.read(TREE_FILE_MAX + 1)
        return data if len(data) <= TREE_FILE_MAX else None
    except OSError:  # UnsafeOpen is one
        return None


# Findings of parse_frontmatter that mean the line was NOT taken into the parsed dict (a scalar it cannot read keeps its raw value there, so it is not one of these).
_DROPPED_LINE = ("invalid YAML top-level", "unexpected indentation", "metadata must be", "duplicate frontmatter key")
_DUPLICATE_KEY = re.compile(r"duplicate frontmatter key '(.*)'$")


def _dropped_frontmatter_lines(head: list, findings: list) -> list:
    """The frontmatter lines (line end and trailing spaces stripped) that parse_frontmatter dropped, in file order: a list item, a bad key, a nested metadata
    line it does not read, and every line of a key given twice (the dict keeps only the last). A change in one of them must change the digest."""
    wanted: set = set()
    for item in findings:
        message = item.get("message", "")
        if message.startswith(_DROPPED_LINE):
            wanted.add(item["line"] - 1)
        twice = _DUPLICATE_KEY.match(message)
        if twice:
            key = twice.group(1)
            wanted.update(i for i, raw in enumerate(head) if i and raw.startswith(key) and raw[len(key):].lstrip(" \t").startswith(":"))
    return [head[i].rstrip() for i in sorted(wanted) if 0 < i < len(head)]


def _semantic_file_sha256(path: Path, rel: str, anchor: Path | None = None) -> str | None:
    """SHA-256 of a file as the semantic tree sees it: SKILL.md = its parsed frontmatter (sorted keys) + its body, CRLF folded to LF; another text file
    (SEMANTIC_TEXT_SUFFIXES) with CRLF folded to LF; any other file as its bytes. A SKILL.md that is not UTF-8 or has no parsable frontmatter counts as text."""
    data = _file_bytes(path, anchor)
    if data is None:
        return None
    if rel == "SKILL.md":
        try:
            text = data.decode("utf-8").replace("\r\n", "\n")
        except UnicodeDecodeError:
            return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
        parsed, findings, end = fs.parse_frontmatter(text, path)
        if not end:  # no frontmatter at all; findings alone (a scalar the offline parser warns about) leave a usable dict
            return hashlib.sha256(text.encode("utf-8")).hexdigest()
        lines = text.splitlines(keepends=True)
        kept = "\n".join(_dropped_frontmatter_lines(lines[:end], findings))
        return hashlib.sha256((json.dumps(parsed, sort_keys=True, ensure_ascii=True) + "\n" + kept + "\n" + "".join(lines[end:])).encode("utf-8")).hexdigest()
    if path.suffix.lower() in SEMANTIC_TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _tree_digest(skill: Path, markers: tuple, semantic: bool) -> str | None:
    """The walk behind tree_sha256 and tree_digest_semantic: one line per file, hashed byte for byte or by `_semantic_file_sha256`."""
    skill = Path(os.path.abspath(os.fspath(skill)))
    if fs.zone_reason(skill, markers) or fs.is_link(skill) or fs.path_is_cloud(skill) or not fs._is_dir_quiet(skill):
        return None
    try:  # walk_files skips a folder it cannot list: for the skill folder itself that would hash the empty tree
        with os.scandir(skill):
            pass
    except OSError:
        return None
    found, links, dirs, cloud, cut = fs.walk_files(skill, markers, skip_names=("__pycache__", ".git"))
    if links or cloud or cut:
        return None
    lines = []
    for path in found:
        if path in dirs:
            if fs.zone_named(path.name, markers):
                return None
            try:  # walk_files leaves a folder it cannot list out without a word: the tree would be hashed with a hole
                with os.scandir(path):
                    pass
            except OSError:
                return None
            continue
        if path.suffix.lower() == ".pyc" or (semantic and path.name == ".gitkeep"):
            continue
        if fs.secret_file_name(path.name):
            return None
        rel = path.relative_to(skill).as_posix()
        digest = _semantic_file_sha256(path, rel, skill) if semantic else _file_sha256(path, skill)
        if digest is None:
            return None
        lines.append((rel, digest))
    lines.sort()
    return hashlib.sha256("".join("%s\t%s\n" % item for item in lines).encode("utf-8", "surrogatepass")).hexdigest()


def tree_sha256(skill: Path, markers: tuple = C.CLOUD_MARKERS) -> str | None:
    """SHA-256 of the lines "<posix path below the skill>\\t<sha256 of the file>\\n", sorted by path, over every regular file of the skill folder (not
    __pycache__, not .git, not *.pyc), bytes as they are. None when the tree cannot be hashed whole: the folder is a link, in a zone or a cloud placeholder; it holds a
    link, a cloud placeholder, a folder named like a zone, a secret-looking file (never opened), more than DOCTOR_MAX_FILES_PER_SKILL entries or a file above
    TREE_FILE_MAX; or a file cannot be opened without following a link."""
    return _tree_digest(skill, markers, False)


def tree_digest_semantic(skill: Path, markers: tuple = C.CLOUD_MARKERS) -> str | None:
    """Like tree_sha256 (same walk, same limits, same None cases) over what a file says, not its bytes (FR3.2 `compare: semantic`): SKILL.md by its parsed
    frontmatter and its body, text files with CRLF folded to LF, other files by bytes; `.gitkeep` is left out too. A copy that a harness adapter rewrote (quoted
    description, LF for CRLF) digests like its source; a changed word, a missing file or an extra file still digests differently."""
    return _tree_digest(skill, markers, True)
