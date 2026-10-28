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
    home = _posix(os.path.expanduser("~")).rstrip("/")
    if home and home != "~" and len(text) > len(home) and text[:len(home) + 1].lower() == (home + "/").lower():
        return "~" + text[len(home):]
    return text


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


def _read_skill_meta(skill: Path) -> tuple:
    """(name, description, opcos keys, notes) from SKILL.md. A key `metadata.opcos_<k>` becomes {k: value cut to DESC_MAX}; a value that is a list or a
    mapping is left out with a note (FR7.1). An unreadable or refused SKILL.md gives the folder name, no description and no keys."""
    manifest = skill / "SKILL.md"
    name, desc, keys, notes = skill.name, "", {}, []
    if fs.is_link(manifest) or fs.path_is_cloud(manifest):
        return name, desc, keys, notes
    try:
        text, too_big = fs.read_capped(manifest, C.DOCTOR_MAX_FILE_BYTES)
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
            data = roots_mod._read_json(plugin / ".claude-plugin" / "plugin.json", C.MANIFEST_MAX, markers)
            if isinstance(data, dict) and isinstance(data.get("version"), str):
                version = data["version"]
        except roots_mod.RootError:
            pass
        cache[key] = version
    return cache[key]


def _evals_entries(plugin: Path | None, cache: dict, notes: list | None = None) -> dict:
    """{skill path relative to the plugin: model_evaluated} from the plugin's evals/catalog.json, when it is a plain file of the Studio schema; else {}.
    A file nested so deep that parsing it overflows is not data: {} and one note (RF-9.1)."""
    if plugin is None:
        return {}
    key = os.path.normcase(os.fspath(plugin))
    if key not in cache:
        found: dict = {}
        path = plugin / evals.CATALOG_REL
        if not (fs.zone_reason(path) or fs.is_link(path) or fs.path_is_cloud(path)) and os.path.isfile(path):
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


def build(roots: list, installed: list, overlap: bool, profile: str, scanned: tuple | None = None, skip_markers: tuple = (),
          notes: list | None = None) -> dict:
    """The catalog report, schema 1. `roots` are Root records (collect_skills updates them in place) and `installed` the Installed records of the
    harnesses asked for. `scanned` = (skills[{path, repo, plugin, root}], skipped) when the caller has already walked the roots; else the roots are walked
    here as `--roots-from opcos` does. `overlap` is accepted and `pairs` stays null (the pair labels come with TK11). Notes about what was dropped are
    appended to `notes` when a list is given."""
    markers = C.CLOUD_MARKERS + tuple(skip_markers)
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
    rows, used = [], set()
    for skill in skills:
        folder = Path(skill["path"])
        name, desc, keys, found = _read_skill_meta(folder)
        if notes is not None:
            notes.extend(found)
        plugin = _plugin_dir(folder, skill["repo"])
        digest = roots_mod.tree_sha256(folder, markers)
        entry = by_path.get(os.path.normcase(doctor._posix(folder)), {})
        rel = folder.relative_to(plugin).as_posix() if plugin is not None else ""
        flag = _evals_entries(plugin, catalogs, notes).get(rel)
        state = {h: {"state": "absent", "version": None} for h in HARNESSES}
        for item in by_key.get((skill["plugin"], folder.name), []):  # one harness may hold several copies (two scopes): `match` wins over `differ`
            if item["harness"] in state and state[item["harness"]]["state"] != "match":
                theirs = roots_mod.tree_sha256(Path(item["path"]), markers)
                state[item["harness"]] = {"state": "match" if digest is not None and theirs == digest else "differ", "version": item.get("version")}
                used.add((item["harness"], item["plugin"], item["skill"]))
        rows.append({"name": name, "description_short": short_description(desc), "repo": skill["repo"], "path": home_path(folder),
                     "plugin_version": _plugin_version(plugin, markers, versions), "tree_sha256": digest, "installed": state,
                     "doctor": {"errors": entry.get("errors", 0), "warnings": entry.get("warnings", 0)},
                     "model_evaluated": flag, "opcos": keys})
    rows.sort(key=lambda r: (r["repo"].casefold(), r["name"].casefold(), r["path"]))
    only = [dict(i, path=home_path(i["path"])) for i in installed if (i["harness"], i["plugin"], i["skill"]) not in used
            and (i["plugin"], i["skill"]) not in {(s["plugin"], Path(s["path"]).name) for s in skills}]
    return {"schema": SCHEMA, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "studio_version": C.VERSION,
            "roots": [_display_root(r) for r in roots], "skills": rows, "installed_only": only, "pairs": None,
            "totals": {"skills": len(rows), "repos": len({r["repo"] for r in rows}), "roots_not_ok": sum(r["status"] != "ok" for r in roots), "pairs": 0}}


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _harness_cell(item: dict) -> str:
    if item["state"] == "differ":
        return "khác (%s)" % item["version"] if item["version"] else "khác"
    return _STATE_CELL.get(item["state"], "—")


def render_md(report: dict) -> str:
    """CATALOG.md: the marker line, a one-sentence summary, a table per repo, then the roots that are not ok, the installed-only copies and the pairs."""
    totals = report["totals"]
    out = ["<!-- studio catalog -->", "", "# Danh mục skill", "",
           "%d skill nguồn ở %d repo; %d gốc không ok; %d cặp cần xem." % (totals["skills"], totals["repos"], totals["roots_not_ok"], totals["pairs"]), "",
           "## Skill theo repo", "", "Lỗi = số ERROR / số WARN của `doctor`. Đã đo = `model_evaluated` trong `evals/catalog.json` (— khi repo không có).", ""]
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
    out += ["", "## Chỉ có bản cài", ""]
    if report["installed_only"]:
        out += ["| Harness | Plugin | Skill | Bản | Đường |", "|---|---|---|---|---|"]
        out += ["| %s | %s | %s | %s | %s |" % (i["harness"], _cell(i["plugin"]), _cell(i["skill"]), _cell(i["version"] or "—"), _cell(i["path"])) for i in report["installed_only"]]
    else:
        out.append("Không có.")
    out += ["", "## Cặp trùng", ""]
    pairs = report["pairs"]
    if pairs is None:
        out.append("Chưa tìm: chạy lại với `--overlap`.")
    else:
        copies = sum(p["label"] == "distribution_copy" for p in pairs)
        shown = [p for p in pairs if p["label"] != "distribution_copy"]
        out.append("%d cặp là bản sao phân phối (đã thể hiện ở cột harness, không liệt kê)." % copies)
        if shown:
            out += ["", "| Cặp | Loại | Bằng chứng | Đề xuất |", "|---|---|---|---|"]
            out += ["| %s ↔ %s | %s | %s | %s (cần người duyệt) |" % (_cell(p["a"]), _cell(p["b"]), p["label"], _cell("; ".join(p["evidence"])), p["suggestion"]) for p in shown]
    return "\n".join(out) + "\n"


def build_parser(prog: str = "catalog") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="Read-only catalog of the source skills of a library: one row per skill, the state of every root, JSON schema 1 and CATALOG.md. "
                                "Exit 0 every root ok, 1 a root is partial or error, 2 nothing scanned or a bad flag.")
    p.add_argument("--roots-from", choices=("opcos",), help="take the roots from an OpcOS tree (paths.json and the plugin manifests), as `doctor --roots-from opcos`; not with --roots or --roots-file")
    p.add_argument("--roots", help="skill roots separated by ';' (default: the repo's skills/; outside the repo --roots or --roots-file is required)")
    p.add_argument("--roots-file", help="file with one root per line, '#' starts a comment")
    p.add_argument("--installed", metavar="HARNESSES", help="comma list of claude,codex,antigravity: read the copies installed there and show khớp/khác/— beside every skill; a harness whose locator fails is a root that is not ok")
    p.add_argument("--overlap", action="store_true", help="find skills that overlap (not available yet: `pairs` stays null)")
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


def _plain_roots(paths: list, skip_markers: tuple) -> tuple:
    """For --roots / --roots-file: (Root records, skills, skipped) from `iter_skill_dirs`. The repo of a skill is the root's folder name (its parent's when
    the root is called skills); a skipped path attaches to the root that holds it, and a root that is itself skipped is an `error`."""
    folders, skipped = doctor.iter_skill_dirs(paths, False, skip_markers)
    roots = [roots_mod._new_root(p, "plugin", "roots") for p in paths]
    for item in skipped:
        low = item["path"].lower().rstrip("/")
        owner = next((r for r in roots if low == r["path"].lower().rstrip("/")), None)
        if owner is not None:
            owner["status"], owner["reasons"] = "error", [item["reason"]]
            continue
        owner = next((r for r in roots if low.startswith(r["path"].lower().rstrip("/") + "/")), roots[0])
        roots_mod.note_skip(owner, item["path"], item["reason"])
    skills = []
    for folder in folders:
        text = _posix(folder).lower()
        owner = next((r for r in roots if text.startswith(r["path"].lower().rstrip("/") + "/")), roots[0])
        base = Path(owner["path"])
        repo = base.parent.name if base.name.lower() == "skills" else base.name
        skills.append({"path": folder, "repo": repo, "plugin": repo, "root": owner["path"]})
    return roots, skills, skipped


def _harness_problem(out: Path, flag: str) -> str | None:
    """Why `out` may not be written under a harness's own folder (~/.claude, ~/.codex, ~/.gemini): the files there belong to the harness."""
    try:
        real = out.parent.resolve() / out.name
    except (OSError, RuntimeError):
        return None
    home = Path(os.path.expanduser("~"))
    for name in HARNESS_DIRS:
        if fs.valid_resolved_under(real, home / name):
            return "%s must not be inside a harness folder (%s): %s" % (flag, name, out)
    return None


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
            problem = doctor.out_problem(target, roots, repo, [], False, skip_markers, kind=kind) or _harness_problem(target, flag)
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
    if args.overlap:
        _say("NOTE: --overlap is not available yet; pairs stays null", sys.stderr)
    report = build(records, installed, bool(args.overlap), "opcos" if opcos is not None else "portable", scanned, skip_markers, notes)
    for line in notes:
        _say("NOTE: %s" % line, sys.stderr)
    for target, kind, flag in targets:
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if kind == "catalog-json" else render_md(report)
        try:
            with open(target, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError as exc:
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
