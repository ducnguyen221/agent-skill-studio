"""The `catalog` command: one row for every source skill, the state of every scan root, JSON schema 1 and CATALOG.md (SPR-04 TK9).

Internal module of `skill-curator` (`curator.py`) and of `studio.py catalog`; do not run it. It uses the engine modules `studio_*` that its loader has
already put in `sys.modules` from the engine folder (never from the path), so a loader must check the folder before it imports this file.
Read-only: it writes only the files named by --out and --md, after the same placement rules as `doctor --out`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import studio_const as C
import studio_doctor as doctor
import studio_evals as evals
import studio_fs as fs
import studio_roots as roots_mod
import curator_installed
import curator_overlap

SCHEMA = 1
HARNESSES = ("claude", "codex", "antigravity")
DESC_MAX = 160  # characters of description_short and of an opcos value (FR2.1, FR7.1)
HARNESS_DIRS = (".claude", ".codex", ".gemini")  # the harnesses' own folders under the home folder: a report is never written into them
_STATE_CELL = {"match": "khớp", "absent": "—"}


def _posix(path) -> str:
    return os.fspath(path).replace("\\", "/")


def home_path(path) -> str:
    """`path` in posix form, with the home folder written as `~` (no user name in a catalog that is shared). Anything outside home stays as it is."""
    text = _posix(path)
    plain = _home_tail(text, _posix(os.path.expanduser("~")).rstrip("/"))
    if plain is not None:
        return plain
    if os.path.isabs(text):  # another spelling of home (an 8.3 name such as DUCNGU~1, a link): compare the real paths of both (RF-A12)
        try:
            real_text, real_home = _posix(os.path.realpath(text)), _posix(os.path.realpath(os.path.expanduser("~"))).rstrip("/")
        except (OSError, ValueError, RuntimeError):
            return text
        return _home_tail(real_text, real_home) or text
    return text


def _home_tail(text: str, home: str) -> str | None:
    if home and home != "~" and len(text) > len(home) and text[:len(home) + 1].lower() == (home + "/").lower():
        return "~" + text[len(home):]
    return None


def short_description(text: str, limit: int = DESC_MAX) -> str:
    """`text` on one line, at most `limit` characters, cut at a word boundary with an ellipsis."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "…"


def _read_skill_meta(skill: Path, anchor: Path | None = None) -> tuple:
    """(name, description, opcos keys, notes) from SKILL.md. A key `metadata.opcos_<k>` becomes {k: value cut to DESC_MAX}; a value that is a list or a
    mapping is left out with a note (FR7.1). An unreadable or refused SKILL.md gives the folder name, no description and no keys."""
    manifest = skill / "SKILL.md"
    name, desc, keys, notes = skill.name, "", {}, []
    if fs.is_link(manifest) or fs.path_is_cloud(manifest):
        return name, desc, keys, notes
    try:
        text, too_big = fs.read_capped(manifest, C.DOCTOR_MAX_FILE_BYTES, single_link=True, anchor=skill.parent if anchor is None else anchor)
    except (OSError, UnicodeError):
        return name, desc, keys, notes
    if too_big:
        return name, desc, keys, notes
    meta, _, end = fs.parse_frontmatter(text, manifest)
    if isinstance(meta.get("name"), str) and meta["name"]:
        name = meta["name"]
    if isinstance(meta.get("description"), str):
        desc = meta["description"]
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    for key, value in metadata.items():
        if key.startswith("opcos_") and len(key) > 6 and isinstance(value, str):
            keys[key[6:]] = short_description(value)
    in_meta = False  # the parser drops a list value with FM1; the raw lines say it was there
    for raw in text.splitlines()[1:max(end - 1, 1)]:
        if raw and not raw[0].isspace():
            in_meta = raw.rstrip() == "metadata:"
            continue
        found = re.match(r"^\s{2,}opcos_([\w.-]+):\s*([\[{].*)$", raw) if in_meta else None
        if found and found.group(1) not in keys:
            notes.append("%s: metadata.opcos_%s is a list or a mapping; not recorded" % (home_path(skill), found.group(1)))
    return name, desc, keys, notes


def _plugin_dir(skill: Path, repo: str) -> Path | None:
    """The folder named `repo` above the skill that holds .claude-plugin/plugin.json (names only; nothing is read), else None."""
    for parent in skill.parents:
        if parent.name == repo and os.path.lexists(parent / ".claude-plugin" / "plugin.json"):
            return parent
    return None


def _plugin_version(plugin: Path | None, markers: tuple, cache: dict) -> str | None:
    if plugin is None:
        return None
    key = os.path.normcase(os.fspath(plugin))
    if key not in cache:
        version = None
        try:
            data = roots_mod._read_json(plugin / ".claude-plugin" / "plugin.json", C.MANIFEST_MAX, markers, plugin)
            if isinstance(data, dict) and isinstance(data.get("version"), str):
                version = data["version"][:200]
        except roots_mod.RootError:
            pass
        cache[key] = version
    return cache[key]


def _real_zone(path: Path) -> str | None:
    """The zone ('cloud' or 'secret-zone') of the real path of `path`, else None; a path that cannot be resolved counts as a zone, so it is not read."""
    try:
        return fs.zone_reason(path.resolve())
    except (OSError, RuntimeError):
        return "unreadable"


def _evals_entries(plugin: Path | None, cache: dict, notes: list | None = None) -> dict:
    """{skill path relative to the plugin: model_evaluated} from the plugin's evals/catalog.json, when it is a plain file of the Studio schema; else {}.
    A file nested so deep that parsing it overflows is not data: {} and one note (RF-9.1)."""
    if plugin is None:
        return {}
    key = os.path.normcase(os.fspath(plugin))
    if key not in cache:
        found: dict = {}
        path = plugin / evals.CATALOG_REL
        if fs.link_in_chain(path, plugin) and notes is not None:  # not read, and not silent either (RF-R1)
            notes.append("%s: evals/catalog.json is behind a link (not read); model_evaluated is null" % home_path(path))
        if not (fs.zone_reason(path) or fs.link_in_chain(path, plugin) or fs.path_is_cloud(path) or _real_zone(path)) and os.path.isfile(path):
            try:
                data = evals._load_json(path)
            except (ValueError, OSError):
                data = None
            except (RecursionError, MemoryError):  # not a ValueError: a few hundred KB of `[` is enough
                data = None
                if notes is not None:
                    notes.append("%s: evals/catalog.json is too deeply nested to read; model_evaluated is null" % home_path(path))
            if isinstance(data, dict) and isinstance(data.get("schema_version"), str) and isinstance(data.get("skills"), list):
                for item in data["skills"]:
                    if isinstance(item, dict) and isinstance(item.get("path"), str):
                        found[item["path"].replace("\\", "/").strip("/")] = item.get("model_evaluated") if isinstance(item.get("model_evaluated"), bool) else None
        cache[key] = found
    return cache[key]


def _display_root(root: dict) -> dict:
    out = dict(root)
    out["path"] = home_path(root["path"]) if root["path"] else ""
    out["skipped_by_rule"] = [{"path": home_path(x["path"]), "reason": x["reason"]} for x in root["skipped_by_rule"]]
    return out


class TreeCache:
    """Digests of skill folders for one run: a folder is walked once for `tree_sha256` and once for `tree_digest_semantic`, however many pairs or columns
    ask. Keyed by the folder's path as the OS compares it, with its own mtime and size so that a folder changed during the run is read again."""

    def __init__(self, markers: tuple = C.CLOUD_MARKERS):
        self.markers = markers
        self._byte: dict = {}
        self._semantic: dict = {}

    @staticmethod
    def _key(path, anchor=None) -> tuple:
        folder = os.path.abspath(os.fspath(path))
        try:
            st = os.lstat(folder)
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = None
        return os.path.normcase(folder), stamp, os.path.normcase(os.path.abspath(os.fspath(anchor))) if anchor else None  # the answer depends on the anchor it was read under

    def sha(self, path, anchor=None):
        key = self._key(path, anchor)
        if key not in self._byte:
            self._byte[key] = roots_mod.tree_sha256(Path(path), self.markers, anchor)
        return self._byte[key]

    def semantic(self, path, anchor=None):
        key = self._key(path, anchor)
        if key not in self._semantic:
            self._semantic[key] = roots_mod.tree_digest_semantic(Path(path), self.markers, anchor)
        return self._semantic[key]


_UNSET = object()


def same_content(a_item: dict, b_item: dict, markers: tuple = C.CLOUD_MARKERS, cache: TreeCache | None = None) -> tuple:
    """(equal, how) for two skill folders given as records with a `path` (a source skill, an Installed copy): (True, "byte") when the trees hash the same byte
    for byte, (True, "semantic") when they only agree after folding what an adapter rewrites (tree_digest_semantic), else (False, None); also (False, None) when
    either tree cannot be hashed whole. The one comparison of `match` (FR3.2) and of the pairs (FR4). A record that carries `sha` is not hashed again; `cache`
    (a TreeCache) shares digests between calls."""
    cache = cache or TreeCache(markers)
    a, b = Path(a_item["path"]), Path(b_item["path"])
    a_digest = a_item["sha"] if "sha" in a_item else cache.sha(a, a_item.get("anchor"))
    return _same_trees(a, a_digest, b, markers, cache, b_item["sha"] if "sha" in b_item else _UNSET, a_item.get("anchor"), b_item.get("anchor"))


def _same_trees(a: Path, a_digest, b: Path, markers: tuple, cache: TreeCache | None = None, b_digest=_UNSET, a_anchor=None, b_anchor=None) -> tuple:
    """`same_content` with the byte digest of `a` (and, when known, of `b`) already in hand; the semantic digests are taken only when the bytes differ.
    `a_anchor` and `b_anchor` are the scan roots the two trees are read under (the chain of folders from there down is pinned)."""
    cache = cache or TreeCache(markers)
    if b_digest is _UNSET:
        b_digest = cache.sha(b, b_anchor)
    if a_digest is not None and a_digest == b_digest:
        return True, "byte"
    left, right = cache.semantic(a, a_anchor), cache.semantic(b, b_anchor)
    return (True, "semantic") if left is not None and left == right else (False, None)


def _scan_anchor(folder, *candidates) -> Path | None:
    """The first of the scan roots `candidates` (as written, then resolved) that holds `folder` by spelling, else None: the chain of folders from there down to a file
    of the skill is pinned while the file is read, so a folder swapped for a link between the root and the skill is not read through."""
    for candidate in candidates:
        if not candidate:
            continue
        for option in (Path(candidate), Path(os.path.realpath(candidate))):
            if fs.lexically_inside(folder, option):
                return option
    return None


def _installed_items(installed: list, markers: tuple, cache: TreeCache | None = None, harness_roots: dict | None = None) -> list:
    """The Installed records as items for `curator_overlap`: key "<harness>/<plugin>:<skill>", the description from the copy's SKILL.md and its tree hash."""
    cache = cache or TreeCache(markers)
    out = []
    for item in installed:
        folder = Path(item["path"])
        anchor = _scan_anchor(folder, (harness_roots or {}).get(item["harness"]))
        name, desc, _, _ = _read_skill_meta(folder, anchor)
        out.append({"key": "%s/%s:%s" % (item["harness"], item["plugin"], item["skill"]), "plugin": item["plugin"], "skill": item["skill"], "name": name,
                    "desc": desc, "path": os.fspath(folder), "harness": item["harness"], "sha": cache.sha(folder, anchor), "anchor": os.fspath(anchor) if anchor else None})
    return out


def build(roots: list, installed: list, overlap: bool, profile: str, scanned: tuple | None = None, skip_markers: tuple = (),
          notes: list | None = None) -> dict:
    """The catalog report, schema 1. `roots` are Root records (collect_skills updates them in place) and `installed` the Installed records of the
    harnesses asked for. `scanned` = (skills[{path, repo, plugin, root}], skipped) when the caller has already walked the roots; else the roots are walked
    here as `--roots-from opcos` does. With `overlap` the pairs are labelled (curator_overlap, FR4); without it `pairs` is null. Notes about what was dropped are
    appended to `notes` when a list is given."""
    markers = C.CLOUD_MARKERS + tuple(skip_markers)
    cache = TreeCache(markers)
    sources = [r for r in roots if r["kind"] != "harness"]  # a harness root is only reported: it holds copies, not source skills
    skills, _ = scanned if scanned is not None else roots_mod.collect_skills(sources, markers)
    paths = [s["path"] for s in skills]
    usable = [Path(r["path"]) for r in sources if r["status"] != "error" and r["path"]]
    report = doctor.doctor_run(usable, profile, "portable", False, None, tuple(skip_markers), scanned=(paths, []))
    by_path = {os.path.normcase(e["path"]): e for e in report["skills"]}
    by_key: dict = {}
    for item in installed:
        by_key.setdefault((item["plugin"], item["skill"]), []).append(item)
    versions: dict = {}
    catalogs: dict = {}
    rows, used, items = [], set(), []
    differ_ids: set = set()
    harness_roots = {r["area"]: r["path"] for r in roots if r["kind"] == "harness"}
    for skill in skills:
        folder = Path(skill["path"])
        anchor = _scan_anchor(folder, skill.get("root"))
        name, desc, keys, found = _read_skill_meta(folder, anchor)
        if notes is not None:
            notes.extend(found)
        plugin = _plugin_dir(folder, skill["repo"])
        digest = cache.sha(folder, anchor)
        entry = by_path.get(os.path.normcase(doctor._posix(folder)), {})
        rel = folder.relative_to(plugin).as_posix() if plugin is not None else ""
        flag = _evals_entries(plugin, catalogs, notes).get(rel)
        state = {h: {"state": "absent", "version": None, "compare": None} for h in HARNESSES}
        for item in by_key.get((skill["plugin"], folder.name), []):  # one harness may hold several copies (two scopes): `match` wins over `differ`
            if item["harness"] in state and state[item["harness"]]["state"] != "match":
                copy_anchor = _scan_anchor(Path(item["path"]), harness_roots.get(item["harness"]))
                same, how = _same_trees(folder, digest, Path(item["path"]), markers, cache, _UNSET, anchor, copy_anchor)
                if not same and (digest is None or cache.sha(Path(item["path"]), copy_anchor) is None):  # a tree that cannot be hashed whole: not a claimed difference (RF-A2)
                    how = "unhashable"
                state[item["harness"]] = {"state": "match" if same else "differ", "version": item.get("version"), "compare": how}
                if not same and how != "unhashable":
                    differ_ids.add((skill["plugin"], folder.name))
                used.add((item["harness"], item["plugin"], item["skill"]))
        rows.append({"name": name, "description_short": short_description(desc), "repo": skill["repo"], "path": home_path(folder),
                     "plugin_version": _plugin_version(plugin, markers, versions), "tree_sha256": digest, "installed": state,
                     "doctor": {"errors": entry.get("errors", 0), "warnings": entry.get("warnings", 0)},
                     "model_evaluated": flag, "opcos": keys})
        items.append({"key": "%s:%s" % (skill["plugin"], folder.name), "plugin": skill["plugin"], "skill": folder.name, "name": name, "desc": desc,
                      "path": os.fspath(folder), "harness": None, "sha": digest, "anchor": os.fspath(anchor) if anchor else None})
    rows.sort(key=lambda r: (r["repo"].casefold(), r["name"].casefold(), r["path"]))
    only = [dict(i, path=home_path(i["path"])) for i in installed if (i["harness"], i["plugin"], i["skill"]) not in used
            and (i["plugin"], i["skill"]) not in {(s["plugin"], Path(s["path"]).name) for s in skills}]
    cut: list = []
    pairs = curator_overlap.find_pairs(items, _installed_items(installed, markers, cache, harness_roots), markers, cache, notes, cut) if overlap else None
    return {"schema": SCHEMA, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "studio_version": C.VERSION,
            "roots": [_display_root(r) for r in roots], "skills": rows, "installed_only": only, "pairs": pairs,
            "totals": {"skills": len(rows), "repos": len({r["repo"] for r in rows}), "roots_not_ok": sum(r["status"] != "ok" for r in roots),
                       "pairs": len(pairs or []), "pairs_to_review": sum(p["label"] in TO_REVIEW for p in pairs or []),
                       "installed_differ_skills": _differ_skills(differ_ids, pairs or []), "pairs_truncated": bool(cut)}}


TO_REVIEW = ("same_name_other_role", "same_function")  # the labels of a suspected duplicate; version_drift is an installed copy that differs, counted per skill (RF-A10)
NEED_ERRORS, NEED_DIFFER, NEED_PAIRS = 4, 3, 10  # lines per list of «Cần xem trước»: the section stays within 25 lines


def _skill_id(key: str) -> tuple:
    """(plugin, skill) of a pair key: "plugin:skill" for a source skill, "harness/plugin:skill" for an installed copy."""
    for harness in HARNESSES:
        if key.startswith(harness + "/"):
            key = key[len(harness) + 1:]
            break
    plugin, _, skill = key.rpartition(":")
    return plugin, skill


def _differ_skills(differ_ids: set, pairs: list) -> int:
    """Skills with an installed copy that differs: the source skills whose copy differs (`differ_ids`) joined with the skills named by a version_drift pair, each once."""
    ids = set(differ_ids)
    for pair in pairs:
        if pair["label"] == "version_drift":
            ids.add(_skill_id(pair["a"]))
            ids.add(_skill_id(pair["b"]))
    return len(ids)


def _differ_rows(report: dict) -> list:
    return [r for r in report["skills"] if any(r["installed"][h]["state"] == "differ" and r["installed"][h]["compare"] != "unhashable" for h in HARNESSES)]


def _differ_total(report: dict) -> int:
    return report["totals"].get("installed_differ_skills", len(_differ_rows(report)))


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _harness_cell(item: dict) -> str:
    if item["state"] == "differ" and item.get("compare") == "unhashable":
        return "không so được"
    if item["state"] == "differ":
        return "khác (%s)" % item["version"] if item["version"] else "khác"
    return _STATE_CELL.get(item["state"], "—")


def _need_to_see(report: dict) -> list:
    """The lines of «Cần xem trước»: skills with ERROR, installed copies that differ, pairs a person has to look at; at most 25 lines with the heading."""
    erred = sorted((r for r in report["skills"] if r["doctor"]["errors"]), key=lambda r: (-r["doctor"]["errors"], r["name"].casefold(), r["repo"].casefold()))
    differ = _differ_rows(report)
    pairs = [p for p in report["pairs"] or [] if p["label"] in TO_REVIEW]
    out = ["## Cần xem trước", ""]
    if erred:
        out.append("**Skill có ERROR** (%d):" % len(erred))
        out += ["- %s · %s · %d ERROR" % (_cell(r["name"]), _cell(r["repo"]), r["doctor"]["errors"]) for r in erred[:NEED_ERRORS]]
        if len(erred) > NEED_ERRORS:
            out.append("- … và %d skill nữa: xem cột Lỗi ở mục Skill theo repo." % (len(erred) - NEED_ERRORS))
    total = _differ_total(report)
    if total:
        out.append("**Skill có bản cài lệch so với nguồn** (%d):" % total)
        for r in differ[:NEED_DIFFER]:
            where = ", ".join(h + ((" (%s)" % _cell(r["installed"][h]["version"])) if r["installed"][h]["version"] else "")
                              for h in HARNESSES if r["installed"][h]["state"] == "differ" and r["installed"][h]["compare"] != "unhashable")
            out.append("- %s · %s" % (_cell(r["name"]), where))
        shown = min(len(differ), NEED_DIFFER)
        if total > shown:
            out.append("- … và %d skill nữa: xem cột Claude, Codex, Antigravity ở mục Skill theo repo và mục Cặp trùng." % (total - shown))
    if pairs and len(pairs) <= NEED_PAIRS:
        out.append("**Cặp nghi trùng** (%d):" % len(pairs))
        out += ["- %s ↔ %s · %s" % (_cell(p["a"]), _cell(p["b"]), p["label"]) for p in pairs]
    elif pairs:
        out.append("**Cặp nghi trùng**: %d cặp, xem mục Cặp trùng." % len(pairs))
    if len(out) == 2:
        out.append("Không có gì cần xem.")
    return out + [""]


def _summary(report: dict) -> str:
    """The one sentence under the title, written as work to do: how many skills have an ERROR, how many skills have an installed copy that differs, and (with --overlap) how many pairs are suspected duplicates."""
    totals = report["totals"]
    erred = sum(bool(r["doctor"]["errors"]) for r in report["skills"])
    text = "%d skill nguồn ở %d repo; %d gốc không ok. Cần xem: %d skill có ERROR, %d skill có bản cài lệch" % (
        totals["skills"], totals["repos"], totals["roots_not_ok"], erred, _differ_total(report))
    if report["pairs"] is not None:
        count = {label: sum(p["label"] == label for p in report["pairs"]) for label in TO_REVIEW}
        text += ", %d cặp nghi trùng (cùng tên khác vai %d, trùng chức năng %d)" % (sum(count.values()), count["same_name_other_role"], count["same_function"])
    return text + "."


def render_md(report: dict, command: str | None = None) -> str:
    """CATALOG.md: the marker line, a one-sentence summary, when and how it was made, what to look at first, a table per repo, then the roots that are not ok,
    the pairs and, last, the installed-only copies (a lookup table, not work to do)."""
    out = ["<!-- studio catalog -->", "", "# Danh mục skill", "", _summary(report),
           "Sinh lúc %s (UTC)%s." % (report["generated_at"], (" bằng `%s`" % command) if command else ""), "",
           *_need_to_see(report),
           "## Skill theo repo", "", "Lỗi = số ERROR / số WARN của `doctor`. Đã đo = `model_evaluated` trong `evals/catalog.json` (— khi repo không có). Bản cài «không so được» = một trong hai cây có file không băm được.", ""]
    repos: dict = {}
    for row in report["skills"]:
        repos.setdefault(row["repo"], []).append(row)
    for repo in sorted(repos, key=str.casefold):
        out += ["### %s" % _cell(repo), "", "| Skill | Việc | Bản | Claude | Codex | Antigravity | Lỗi | Đã đo |", "|---|---|---|---|---|---|---|---|"]
        for row in repos[repo]:
            measured = {True: "có", False: "chưa", None: "—"}[row["model_evaluated"]]
            out.append("| %s | %s | %s | %s | %s | %s | %d / %d | %s |" % (
                _cell(row["name"]), _cell(row["description_short"]), _cell(row["plugin_version"] or "—"),
                *(_harness_cell(row["installed"][h]) for h in HARNESSES), row["doctor"]["errors"], row["doctor"]["warnings"], measured))
        out.append("")
    out += ["## Gốc không ok", ""]
    bad = [r for r in report["roots"] if r["status"] != "ok"]
    if bad:
        out += ["| Gốc | Trạng thái | Lý do |", "|---|---|---|"]
        out += ["| %s | %s | %s |" % (_cell(r["path"] or r["area"]), r["status"], _cell(", ".join(r["reasons"]) or "—")) for r in bad]
    else:
        out.append("Không có: mọi gốc đã quét đều ok.")
    out += ["", "## Cặp trùng", ""]
    pairs = report["pairs"]
    if pairs is None:
        out.append("Chưa tìm: chạy lại với `--overlap`.")
    else:
        copies = sum(p["label"] == "distribution_copy" for p in pairs)
        shown = [p for p in pairs if p["label"] != "distribution_copy"]
        out.append("%d cặp là bản sao phân phối (đã thể hiện ở cột harness, không liệt kê)." % copies)
        if report["totals"].get("pairs_truncated"):
            out.append("Danh sách cặp đã cắt ở %s." % "{:,}".format(curator_overlap.OVERLAP_MAX_PAIRS).replace(",", " "))
        if shown:
            out += ["", "| Cặp | Loại | Bằng chứng | Đề xuất |", "|---|---|---|---|"]
            out += ["| %s ↔ %s | %s | %s | %s (cần người duyệt) |" % (_cell(p["a"]), _cell(p["b"]), p["label"], _cell("; ".join(p["evidence"])), p["suggestion"]) for p in shown]
    out += ["", "## Chỉ có bản cài", ""]
    if report["installed_only"]:
        out += ["| Harness | Plugin | Skill | Bản | Đường |", "|---|---|---|---|---|"]
        out += ["| %s | %s | %s | %s | %s |" % (i["harness"], _cell(i["plugin"]), _cell(i["skill"]), _cell(i["version"] or "—"), _cell(i["path"])) for i in report["installed_only"]]
    else:
        out.append("Không có.")
    return "\n".join(out) + "\n"


def build_parser(prog: str = "catalog") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="Read-only catalog of the source skills of a library: one row per skill, the state of every root, JSON schema 1 and CATALOG.md. "
                                "Exit 0 every root ok, 1 a root is partial or error, 2 nothing scanned or a bad flag.")
    p.add_argument("--roots-from", choices=("opcos",), help="take the roots from an OpcOS tree (paths.json and the plugin manifests), as `doctor --roots-from opcos`; not with --roots or --roots-file")
    p.add_argument("--roots", help="skill roots separated by ';' (default: the repo's skills/; outside the repo --roots or --roots-file is required)")
    p.add_argument("--roots-file", help="file with one root per line, '#' starts a comment")
    p.add_argument("--installed", metavar="HARNESSES", help="comma list of claude,codex,antigravity: read the copies installed there and show match / differ / absent beside every skill; a harness whose locator fails is a root that is not ok")
    p.add_argument("--overlap", action="store_true", help="name pairs of skills that may overlap and give each one of five labels with its evidence and a fixed suggestion (only a suggestion: every pair needs a person); without it `pairs` is null")
    p.add_argument("--json", action="store_true", help="print the JSON report (with --out it goes to the file only)")
    p.add_argument("--out", help="write the JSON report here; the folder must exist; not under skills/, a scanned root or a harness folder; not a secret-looking name")
    p.add_argument("--md", help="write CATALOG.md here, same placement rules; an existing file is replaced only when its first line is <!-- studio catalog -->")
    p.add_argument("--home", help=argparse.SUPPRESS)  # tests only: stands for the home folder when the harness folders are read
    p.add_argument("--skip-marker", action="append", metavar="TEXT", help="skip any path containing TEXT (case-insensitive); repeatable")
    return p


def _say(text: str, stream=None) -> None:
    """print() that never dies on a console that cannot show a character."""
    stream = stream or sys.stdout
    try:
        print(text, file=stream)
    except UnicodeEncodeError:
        print(text.encode("ascii", "backslashreplace").decode("ascii"), file=stream)


def _manifest_plugin(folder: Path, top: Path, markers: tuple, cache: dict) -> str | None:
    """The `name` of the nearest plugin manifest (.claude-plugin/plugin.json) at or above `folder`, climbing no higher than `top` (its parent when `top` is called
    skills), else None; the manifest is one bounded read through the same reader as the manifests of an OpcOS tree. A manifest that cannot be read gives None."""
    limit = top.parent if top.name.lower() == "skills" else top
    for parent in folder.parents:
        manifest = parent / ".claude-plugin" / "plugin.json"
        if os.path.lexists(manifest):
            key = os.path.normcase(os.fspath(parent))
            if key not in cache:
                try:
                    data = roots_mod._read_json(manifest, C.MANIFEST_MAX, markers, limit)
                    cache[key] = data["name"] if isinstance(data, dict) and isinstance(data.get("name"), str) and data["name"] else None
                except roots_mod.RootError:
                    cache[key] = None
            return cache[key]
        if parent == limit:
            break
    return None


def _plain_roots(paths: list, skip_markers: tuple) -> tuple:
    """For --roots / --roots-file: (Root records, skills, skipped) from `iter_skill_dirs`. The repo of a skill is the root's folder name (its parent's when
    the root is called skills); its plugin is the `name` of the plugin manifest around it when there is one (so a root that holds several plugins keeps
    them apart, and a pair or an installed copy is keyed as in an OpcOS tree), else the repo. A skipped path attaches to the root that holds it, and a root
    that is itself skipped is an `error`."""
    folders, skipped = doctor.iter_skill_dirs(paths, False, skip_markers)
    skipped = roots_mod._rule_names(skipped, roots_mod._extra(C.CLOUD_MARKERS + tuple(skip_markers)))  # a folder named like a cloud zone is a rule here too (RF-A3)
    roots = [roots_mod._new_root(p, "plugin", "roots") for p in paths]
    for item in skipped:
        low = item["path"].lower().rstrip("/")
        owner = next((r for r in roots if low == r["path"].lower().rstrip("/")), None)
        if owner is not None:
            owner["status"], owner["reasons"] = "error", ["cloud" if item["reason"] == "cloud-name" else item["reason"]]  # the root itself is named like a cloud: not «a rule, root ok» (RF-A11)
            continue
        owner = next((r for r in roots if low.startswith(r["path"].lower().rstrip("/") + "/")), roots[0])
        roots_mod.note_skip(owner, item["path"], item["reason"])
    skills, manifests = [], {}
    for folder in folders:
        text = _posix(folder).lower()
        owner = next((r for r in roots if text.startswith(r["path"].lower().rstrip("/") + "/")), roots[0])
        base = Path(owner["path"])
        repo = base.parent.name if base.name.lower() == "skills" else base.name
        skills.append({"path": folder, "repo": repo, "plugin": _manifest_plugin(Path(folder), base, C.CLOUD_MARKERS + tuple(skip_markers), manifests) or repo, "root": owner["path"]})
    return roots, skills, skipped


def _harness_problem(out: Path, flag: str, home: Path | None = None) -> str | None:
    """Why `out` may not be written under a harness's own folder (~/.claude, ~/.codex, ~/.gemini): the files there belong to the harness. `home` is the folder
    given with --home: its harness folders are guarded like the real home's."""
    try:
        real = out.parent.resolve() / out.name
    except (OSError, RuntimeError):
        return None
    for owner in (Path(os.path.expanduser("~")), home):
        for name in HARNESS_DIRS:
            if owner is not None and fs.valid_resolved_under(real, owner / name):
                return "%s must not be inside a harness folder (%s): %s" % (flag, name, out)
    return None


def _command_text(args) -> str:
    """The command as it was given, for the line under the summary of CATALOG.md: paths with the home folder written as `~`, in the same order as the flags."""
    def path_of(value: str) -> str:
        return ";".join(home_path(os.path.abspath(os.path.expanduser(x))) if x else x for x in value.split(";"))

    def word(text: str) -> str:
        return '"%s"' % text if re.search(r"[\s;]", text) else text

    parts = ["studio.py", "catalog"]
    if args.roots_from:
        parts += ["--roots-from", args.roots_from]
    if args.roots:
        parts += ["--roots", word(path_of(args.roots))]
    if args.roots_file:
        parts += ["--roots-file", word(path_of(args.roots_file))]
    if args.installed:
        parts += ["--installed", args.installed]
    if args.overlap:
        parts.append("--overlap")
    if args.json:
        parts.append("--json")
    for marker in args.skip_marker or []:
        parts += ["--skip-marker", word(marker)]
    if args.out:
        parts += ["--out", word(path_of(args.out))]
    if args.md:
        parts += ["--md", word(path_of(args.md))]
    return " ".join(parts)


def run(args) -> int:
    """`catalog`: exit 0 every root ok, 1 a root is partial or error, 2 nothing scanned or a flag that cannot be used."""
    repo = fs.repo_root(Path(__file__)) or fs.repo_root(Path.cwd())
    skip_markers = tuple(x.strip() for x in (args.skip_marker or []))
    if any(not x for x in skip_markers):
        _say("ERROR: --skip-marker needs non-empty text", sys.stderr)
        return 2
    markers = C.CLOUD_MARKERS + skip_markers
    wanted = [x.strip() for x in (args.installed or "").split(",") if x.strip()] if args.installed else []
    bad = [x for x in wanted if x not in HARNESSES]
    if args.installed is not None and (bad or not wanted):
        _say("ERROR: --installed takes a comma list of %s" % ", ".join(HARNESSES), sys.stderr)
        return 2
    if args.roots_from and (args.roots or args.roots_file):
        _say("ERROR: --roots-from cannot be combined with --roots or --roots-file", sys.stderr)
        return 2
    opcos = None
    try:
        if args.roots_from:
            opcos = doctor._opcos_roots(markers)
            roots = [Path(r["path"]) for r in opcos if r["status"] != "error"]
        else:
            roots = doctor.parse_roots(args.roots, args.roots_file, repo, skip_markers)
    except ValueError as exc:
        _say("ERROR: %s" % exc, sys.stderr)
        return 2
    targets = []
    if args.out and args.md and Path(os.path.abspath(os.path.expanduser(args.out))) == Path(os.path.abspath(os.path.expanduser(args.md))):
        _say("ERROR: --out and --md name the same file", sys.stderr)
        return 2
    for value, kind, flag in ((args.out, "catalog-json", "--out"), (args.md, "catalog-md", "--md")):
        if value:
            target = Path(os.path.abspath(os.path.expanduser(value)))
            problem = doctor.out_problem(target, roots, repo, [], False, skip_markers, kind=kind) or _harness_problem(target, flag, Path(os.path.abspath(os.path.expanduser(args.home))) if args.home else None)
            if problem:
                _say("ERROR: %s" % problem, sys.stderr)
                return 2
            targets.append((target, kind, flag))
    if opcos is not None:
        records = opcos
        skills, skipped = roots_mod.collect_skills(opcos, markers)
        scanned = (skills, skipped)
    else:
        records, skills, skipped = _plain_roots(roots, skip_markers)
        scanned = (skills, skipped)
    for target, kind, flag in targets:  # the scanned skills are known now: the file may not sit inside one
        problem = doctor.out_problem(target, roots, repo, [s["path"] for s in skills], False, skip_markers, kind=kind)
        if problem:
            _say("ERROR: %s" % problem, sys.stderr)
            return 2
    if not skills:
        _say("ERROR: no skill found in %s" % (", ".join(home_path(r) for r in roots) or "any root"), sys.stderr)
        return 2
    notes: list = []
    installed: list = []
    if wanted:
        home = Path(os.path.abspath(os.path.expanduser(args.home))) if args.home else Path.home()
        records = list(records)
        for harness in HARNESSES:
            if harness in wanted:
                found, harness_root = curator_installed.locate(harness, home, markers)
                installed.extend(found)
                records.append(harness_root)
    report = build(records, installed, bool(args.overlap), "opcos" if opcos is not None else "portable", scanned, skip_markers, notes)
    for line in notes:
        _say("NOTE: %s" % line, sys.stderr)
    for target, kind, flag in targets:
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if kind == "catalog-json" else render_md(report, _command_text(args))
        try:
            fs.write_replace(target, text.encode("utf-8"))
        except OSError as exc:  # UnsafeOpen is one
            _say("ERROR: cannot write %s: %s" % (flag, exc), sys.stderr)
            return 2
    totals = report["totals"]
    if args.json and not args.out:
        try:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        except UnicodeEncodeError:  # a console that cannot show every character
            print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        _say("catalog: %d skills in %d repos; %d roots not ok" % (totals["skills"], totals["repos"], totals["roots_not_ok"]))
        if not targets:
            for row in report["skills"]:
                _say("  %-22s %-34s %-9s %d/%d" % (row["repo"][:22], row["name"][:34], row["plugin_version"] or "-", row["doctor"]["errors"], row["doctor"]["warnings"]))
        for item in report["roots"]:
            if item["status"] != "ok":
                _say("  root %s: %s (%s)" % (item["path"] or item["area"], item["status"], ", ".join(item["reasons"])))
        for target, kind, flag in targets:
            _say("%s written to %s" % ("report" if kind == "catalog-json" else "CATALOG.md", target))
    return 0 if totals["roots_not_ok"] == 0 else 1
