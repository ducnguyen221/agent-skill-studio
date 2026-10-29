"""The `doctor` command: find skill folders under some roots, validate each one, and report or diff against a baseline (SPR-02 TK4c).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

import studio_const as C
import studio_doctypes as doctypes
import studio_fs as fs
import studio_lint as lint
import studio_roots as roots_mod
import studio_validate as validate


def _posix(path) -> str:
    return os.fspath(path).replace("\\", "/")


def _is_excluded(parts: tuple, include_cache: bool) -> bool:
    """True when the newest folder name in `parts` (relative to the root) completes a DOCTOR_EXCLUDE_PARTS entry or looks like a cache."""
    low = [x.lower() for x in parts]
    for pattern in C.DOCTOR_EXCLUDE_PARTS:
        want = pattern.lower().split("/")
        if low[-len(want):] == want:
            return True
    return not include_cache and "cache" in low[-1]


def _real_link(path: Path) -> bool:
    """True for a link that can be read (a symlink or junction): the only kind of root that is resolved. A path that cannot be probed (`fs.is_link`
    says True for it, FR13.1) is not: nothing is asked about where it leads, it ends as «root not found» like any root that is not a folder."""
    if not fs.is_link(path):
        return False
    try:
        os.lstat(path)
    except OSError:
        return False
    return True


def parse_roots(roots: str | None, roots_file: str | None, repo: Path | None, skip_markers: tuple = ()) -> list[Path]:
    """Absolute root paths from --roots (`;` separated) and --roots-file (one per line; `#` starts a comment, also after a path).
    Without either, the repo's skills/ is the root; outside the repo that is an error. A path in a cloud or secret zone is
    returned without being looked at (doctor reports it as skipped); any other root must be an existing directory and not too
    broad (a drive root, the home folder or a folder above it). A --roots-file with a secret-looking name is refused unread, and
    an error about one of its lines names the line number, never the line."""
    markers = C.CLOUD_MARKERS + tuple(skip_markers)
    items = [(x.strip(), x.strip()) for x in (roots or "").split(";") if x.strip()]
    if roots_file:
        listing = Path(os.path.abspath(os.path.expanduser(roots_file)))
        problem = fs.input_file_problem(listing, markers)
        if problem:
            raise ValueError("--roots-file %s" % problem)
        try:
            lines = fs.read_capped(listing, None, anchor=fs.anchor_for(listing))[0].splitlines()
        except UnicodeError:
            raise ValueError("cannot read --roots-file %s: not UTF-8 text" % roots_file)
        except OSError as exc:
            raise ValueError("cannot read --roots-file %s: %s" % (roots_file, str(exc) if isinstance(exc, fs.UnsafeOpen) else exc.strerror or type(exc).__name__))
        for number, raw in enumerate(lines, 1):
            line = raw.strip()
            comment = re.search(r"(?<=\s)#", line)  # a comment starts at '#' at the line start or after whitespace; 'a#b' stays a path (one linear scan)
            if comment:
                line = line[:comment.start()].rstrip()
            if line and not line.startswith("#"):
                items.append((line, "--roots-file line %d" % number))
    if not items:
        if repo is None:
            raise ValueError("outside the Studio repository doctor needs --roots or --roots-file")
        items = [(str(repo / "skills"),) * 2]
    found = []
    for item, label in items:
        path = Path(os.path.abspath(os.path.expanduser(item)))
        if fs.root_too_broad(path, markers):
            raise ValueError("root too broad; pass narrower roots (not a drive root, the home folder or a folder above it): %s" % label)
        if not fs.zone_reason(path, markers):  # decided from the name, before anything touches the path
            probe = Path(os.path.realpath(path)) if _real_link(path) else path  # a root given as a link is the user's explicit choice: judged by what it resolves to, as iter_skill_dirs does
            if not (fs.path_is_cloud(probe) or fs._is_dir_quiet(probe)):  # a cloud placeholder root exists: iter_skill_dirs skips it with reason cloud
                raise ValueError("root not found or not a directory: %s" % label)
        found.append(path)
    return found


def iter_skill_dirs(roots: list, include_cache: bool = False, skip_markers: tuple = ()) -> tuple[list, list]:
    """(skill folders, skipped[{path, reason}]). A skill is a folder holding SKILL.md; the scan never goes below one, never
    follows a symlink or junction, and de-duplicates by real path. Reasons: cloud (a name with a marker, or Windows cloud
    attributes on the folder or its SKILL.md), secret-zone (both decided without listing or opening anything there),
    link, excluded, limit, unreadable."""
    markers = C.CLOUD_MARKERS + tuple(skip_markers)
    skills, skipped, seen_skills, seen_skips, seen_roots, listed = [], [], set(), set(), set(), 0

    def skip(path, reason):
        key = (os.path.normcase(os.fspath(path)), reason)
        if key not in seen_skips:
            seen_skips.add(key)
            skipped.append({"path": _posix(path), "reason": reason})

    for given in roots:
        given = Path(os.path.abspath(os.fspath(given)))
        reason = fs.zone_reason(given, markers) or ("cloud" if fs.path_is_cloud(given) else None)
        if reason:
            skip(given, reason)
            continue
        try:
            real = given.resolve()
        except (OSError, RuntimeError):
            skip(given, "unreadable")
            continue
        reason = fs.zone_reason(real, markers) or ("cloud" if fs.path_is_cloud(real) else None)
        if reason:
            skip(given, reason)
            continue
        if os.path.normcase(str(real)) in seen_roots:
            continue
        seen_roots.add(os.path.normcase(str(real)))
        stack = [(real, ())]
        while stack:
            current, rel = stack.pop()
            listed += 1
            if listed > C.DOCTOR_MAX_DIRS:
                skip(current, "limit")
                break
            try:
                with os.scandir(current) as scan:
                    entries = sorted(scan, key=lambda e: e.name)
            except OSError:
                skip(current, "unreadable")
                continue
            manifest = next((e for e in entries if e.name == "SKILL.md"), None)
            if manifest is not None:
                if manifest.is_symlink():
                    skip(current / "SKILL.md", "link")
                elif fs.entry_is_cloud(manifest):
                    skip(current, "cloud")
                elif len(skills) >= C.DOCTOR_MAX_SKILLS:
                    skip(current, "limit")
                elif os.path.normcase(str(current)) not in seen_skills:
                    seen_skills.add(os.path.normcase(str(current)))
                    skills.append(current)
                continue
            for entry in reversed(entries):
                child = current / entry.name
                try:
                    if not (entry.is_dir(follow_symlinks=False) or entry.is_symlink()):
                        continue
                except OSError:
                    continue
                reason = fs.zone_reason(child, markers)
                if reason:
                    skip(child, reason)
                elif fs.entry_is_cloud(entry):
                    skip(child, "cloud")
                elif entry.is_symlink() or fs.is_link(child):
                    skip(child, "link")
                elif entry.name.lower() in C.DOCTOR_PRUNE_SILENT:
                    continue
                elif _is_excluded(rel + (entry.name,), include_cache):
                    skip(child, "excluded")
                elif len(rel) + 1 > C.DOCTOR_MAX_DEPTH:
                    skip(child, "limit")
                else:
                    stack.append((child, rel + (entry.name,)))
    return sorted(skills, key=lambda p: os.path.normcase(str(p))), skipped


def _skill_identity(skill: Path, target: str, max_bytes: int | None = None, skip_read: bool = False, anchor: Path | None = None) -> tuple[str, str]:
    """(name, 'en'|'vi') from SKILL.md: frontmatter name (folder name when unreadable or above `max_bytes`) and the body language.
    `skip_read` (validate refused the file with INPUT): SKILL.md is not opened again and the folder name stands."""
    if skip_read:
        return skill.name, "en"
    manifest = skill / "SKILL.md"
    try:
        text, too_big = fs.read_capped(manifest, max_bytes, single_link=True, anchor=skill if anchor is None else anchor)
    except (OSError, UnicodeError):
        return skill.name, "en"
    if too_big:
        return skill.name, "en"
    meta, _, body_start = fs.parse_frontmatter(text, manifest, C.CLAUDE_CODE_KEYS if target == "claude-code" else frozenset())
    name = meta.get("name") if isinstance(meta.get("name"), str) and meta["name"] else skill.name
    return name, lint.detect_lang("\n".join(text.splitlines()[body_start:]))


def _budget_desc_bytes(skill: Path, max_bytes: int | None, skip_read: bool, anchor: Path | None = None) -> int:
    """UTF-8 bytes of the description as measure-skill-budget.py counts them (0 when SKILL.md is unreadable, refused, too big or has no description)."""
    if skip_read:
        return 0
    manifest = skill / "SKILL.md"
    try:
        text, too_big = fs.read_capped(manifest, max_bytes, single_link=True, anchor=skill if anchor is None else anchor)
    except (OSError, UnicodeError):
        return 0
    if too_big:
        return 0
    meta, _, _ = fs.parse_frontmatter(text, manifest)
    return len(validate.budget_desc(meta).encode("utf-8"))


def _under_roots(path, roots) -> str:
    """`path` relative to the first of the report's `roots` that holds it (posix, case-folded on Windows), else `path` as written:
    a baseline taken in another checkout of the same tree still matches."""
    text = path if isinstance(path, str) else ""
    for root in roots if isinstance(roots, list) else []:
        spellings = [str(root).rstrip("/")]
        try:
            spellings.append(Path(str(root)).resolve().as_posix().rstrip("/"))  # a root given by an 8.3 or linked name; skills are listed by real path
        except (OSError, RuntimeError):
            pass
        for base in spellings:
            head, same = text[:len(base) + 1], base + "/"
            if base and (head.lower() == same.lower() if os.name == "nt" else head == same):
                return text[len(base) + 1:]
    return text


def _code_counts(report: dict) -> dict:
    """{(skill path under its root, code): times} over ERROR and WARN findings (a NOTE is information, never "new")."""
    counts: dict = {}
    for skill in report.get("skills", []):
        for item in skill.get("codes", []):
            if item.get("level") in ("ERROR", "WARN"):
                key = (_under_roots(skill.get("path"), report.get("roots")), item.get("code"))
                counts[key] = counts.get(key, 0) + 1
    return counts


def diff_baseline(current: dict, baseline: dict) -> list[dict]:
    """The (skill, code) pairs that occur more often in `current` than in `baseline`; skills are matched by their path under the report roots."""
    before = _code_counts(baseline)
    shown = {_under_roots(skill.get("path"), current.get("roots")): skill.get("path") for skill in current.get("skills", [])}
    return [{"path": shown.get(path, path), "code": code, "before": before.get((path, code), 0), "after": after}
            for (path, code), after in sorted(_code_counts(current).items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))
            if after > before.get((path, code), 0)]


def _key(path) -> str:
    return os.path.normcase(os.fspath(path))


def _pack_name(skill: Path, roots: list, cache: dict, markers: tuple) -> str:
    """The pack of a skill outside --roots-from: `name` of the nearest `.claude-plugin/plugin.json` at or above it (up to the folder above its root), else the first
    folder under its root. The manifest is read by studio_roots (size cap, no links, cloud and secret zones refused); an unreadable one counts as absent."""
    try:
        skill = Path(skill).resolve()
    except OSError:
        return Path(skill).name
    root = next((r for r in roots if _key(skill).startswith(_key(r) + os.sep)), None)  # `roots` are resolved already (real_roots of doctor_run)
    if root is None:
        return skill.name
    folder = skill.parent
    stop = _key(root.parent)  # a root such as <plugin>/skills sits one level below its manifest, so the folder above the root is looked at too
    while _key(folder).startswith(stop):
        if folder not in cache:
            name = None
            try:
                data = roots_mod._read_json(folder / ".claude-plugin" / "plugin.json", C.MANIFEST_MAX, markers, Path(root).parent) if (folder / ".claude-plugin").is_dir() else None
                if isinstance(data, dict) and isinstance(data.get("name"), str) and data["name"].strip():
                    name = data["name"].strip()[:200]
            except roots_mod.RootError:
                pass
            cache[folder] = name
        if cache[folder]:
            return cache[folder]
        if _key(folder) == stop:
            break
        folder = folder.parent
    try:
        return skill.relative_to(root).parts[0]
    except (ValueError, IndexError):
        return skill.name


def _manifest_dir(skill: Path, roots: list, cache: dict) -> Path | None:
    """The plugin folder of a skill: the nearest folder at or above it, up to the one above its root, that holds `.claude-plugin/plugin.json`; None outside the roots.
    Same walk as `_pack_name`, but only the manifest's presence is asked (a stat), the manifest is not read."""
    try:
        skill = Path(skill).resolve()
    except OSError:
        return None
    root = next((r for r in roots if _key(skill).startswith(_key(r) + os.sep)), None)
    if root is None:
        return None
    folder, stop = skill.parent, _key(root.parent)
    while _key(folder).startswith(stop):
        if folder not in cache:
            try:
                os.lstat(folder / ".claude-plugin" / "plugin.json")
                cache[folder] = True
            except OSError:
                cache[folder] = False
        if cache[folder]:
            return folder
        if _key(folder) == stop:
            break
        folder = folder.parent
    return None


def _has_evals_dir(skill: Path) -> bool:
    """True when the skill holds an `evals/` folder (a link does not count): the ST8 that a tightened rule would add (FR6.2)."""
    try:
        info = os.lstat(skill / "evals")
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode)


def pack_line(pack: dict) -> str:
    """One text line of the pack table (PLAN TK7). ST8 is the real ST8 count; when skills hold an evals/ folder, a tightened rule would add them, shown as `<real>+<n> evals` (RF-7.1)."""
    by_code = pack["by_code"]
    st8 = "%d+%d evals" % (by_code.get("ST8", 0), pack["st8_evals"]) if pack["st8_evals"] > 0 else "%d" % by_code.get("ST8", 0)
    return "%s: %d skills, %d errors (ST5 %d), %d warnings (ST8 %s); check exits %d" % (
        pack["pack"], pack["skills"], pack["errors"], by_code.get("ST5", 0), pack["warnings"], st8, pack["check_exit"])


def doctor_run(roots: list, profile: str, target: str, include_cache: bool, baseline: dict | None,
               skip_markers: tuple = (), scanned: tuple | None = None, by_pack: bool = False, pack_of: dict | None = None, docs: bool = False) -> dict:
    """The doctor report (SPEC 9.11, schema 1). Reads skills, writes nothing. `scanned` = a finished iter_skill_dirs result to reuse.
    `by_pack` adds `packs`; `pack_of` = {skill path: pack name} when the caller knows it (--roots-from opcos).
    `docs` adds `docs`: the rules files at the root of each plugin that holds a scanned skill, and its workflows/ files, checked as `check` does (FR8.4); the totals stay skills only.
    A file above DOCTOR_MAX_FILE_BYTES or a cloud placeholder inside a skill is not read; it is listed in skipped as well as flagged in the skill."""
    skills, skipped = scanned if scanned is not None else iter_skill_dirs(roots, include_cache, skip_markers)
    skipped = list(skipped)
    seen_skips = {(os.path.normcase(x["path"]), x["reason"]) for x in skipped}
    real_roots = []
    for root in roots:
        if not fs.zone_reason(root, C.CLOUD_MARKERS + tuple(skip_markers)):
            try:
                real_roots.append(Path(root).resolve())
            except OSError:
                continue
    entries = []
    totals = {"skills": 0, "errors": 0, "warnings": 0, "notes": 0}
    desc_bytes = 0
    packs: dict = {}
    manifests: dict = {}
    plugin_dirs: dict = {}
    manifest_seen: dict = {}
    for skill in skills:
        under = next((r for r in real_roots if fs.valid_resolved_under(skill, r)), None)
        pin_root = next((r for r in real_roots if fs.lexically_inside(skill, r)), None)  # by spelling: a folder swapped for a link since the scan is no longer under it once resolved
        findings = validate.validate_skill(skill, require_evals=False, target=target, profile=profile, allow_links_under=under,
                                  max_file_bytes=C.DOCTOR_MAX_FILE_BYTES, skip_markers=skip_markers, anchor=pin_root)
        codes = []
        for f in findings:
            if f["code"] in ("SZ1", "SZ2"):
                note = {"path": _posix(f["path"]), "reason": "limit" if f["code"] == "SZ1" else "cloud"}
                if (os.path.normcase(note["path"]), note["reason"]) not in seen_skips:
                    seen_skips.add((os.path.normcase(note["path"]), note["reason"]))
                    skipped.append(note)
            path = Path(f["path"])
            try:
                shown = path.relative_to(skill).as_posix()
            except ValueError:
                shown = _posix(path)
            codes.append({"code": f["code"], "level": f["level"], "file": shown, "line": f["line"], "message": f["message"]})
        refused = any(c["code"] == "INPUT" for c in codes)
        name, lang = _skill_identity(skill, target, C.DOCTOR_MAX_FILE_BYTES, skip_read=refused, anchor=pin_root)
        desc_bytes += _budget_desc_bytes(skill, C.DOCTOR_MAX_FILE_BYTES, refused, pin_root) if profile == "opcos" else 0
        errors, warnings = sum(c["level"] == "ERROR" for c in codes), sum(c["level"] == "WARN" for c in codes)
        entries.append({"path": _posix(skill), "name": name, "lang": lang, "errors": errors, "warnings": warnings, "codes": codes})
        totals["skills"] += 1
        totals["errors"] += errors
        totals["warnings"] += warnings
        totals["notes"] += sum(c["level"] == "NOTE" for c in codes)
        if docs:
            plugin = _manifest_dir(skill, real_roots, manifest_seen)
            if plugin is not None:
                plugin_dirs[_key(plugin)] = plugin
        if by_pack:
            pack_name = (pack_of or {}).get(_key(skill)) or _pack_name(skill, real_roots, manifests, C.CLOUD_MARKERS + tuple(skip_markers))
            pack = packs.setdefault(pack_name, {"pack": pack_name, "skills": 0, "errors": 0, "warnings": 0, "by_code": {}, "check_exit": 0, "st8_evals": 0})
            pack["skills"] += 1
            pack["errors"] += errors
            pack["warnings"] += warnings
            pack["st8_evals"] += _has_evals_dir(skill)
            for item in codes:
                if item["level"] in ("ERROR", "WARN"):
                    pack["by_code"][item["code"]] = pack["by_code"].get(item["code"], 0) + 1
    report = {"schema": C.DOCTOR_SCHEMA, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "studio_version": C.VERSION, "roots": [_posix(r) for r in roots], "skills": entries, "skipped": skipped,
              "totals": totals, "new_vs_baseline": []}
    if profile == "opcos":  # the same verdict as measure-skill-budget.py on the total (SPEC FR5.2)
        report["budget"] = {"desc_bytes_total": desc_bytes, "limit": C.OPCOS_DESC_TOTAL_BYTES, "over": desc_bytes > C.OPCOS_DESC_TOTAL_BYTES}
    if by_pack:  # `check` exits 1 for a pack with an ERROR, the same rule as the default fail level (FR6.1)
        for pack in packs.values():
            pack["check_exit"] = 1 if pack["errors"] else 0
        report["packs"] = sorted(packs.values(), key=lambda p: p["pack"].casefold())
    if docs:
        report["docs"] = doctypes.docs_report([plugin_dirs[k] for k in sorted(plugin_dirs)], C.CLOUD_MARKERS + tuple(skip_markers))
    if baseline is not None:
        report["new_vs_baseline"] = diff_baseline(report, baseline)
    return report


def _baseline_problem(obj) -> str | None:
    if not isinstance(obj, dict) or obj.get("schema") != C.DOCTOR_SCHEMA or not isinstance(obj.get("skills"), list):
        return "is not a doctor report (expected JSON with schema %d and a skills list)" % C.DOCTOR_SCHEMA
    for skill in obj["skills"]:
        if not isinstance(skill, dict) or not isinstance(skill.get("codes", []), list) or any(not isinstance(c, dict) for c in skill.get("codes", [])):
            return "has skills[] entries that are not objects with a codes list"
    return None


OUT_KINDS = ("doctor", "catalog-json", "catalog-md")


def out_problem(out: Path, roots: list, repo: Path | None, skills: list = (), include_cache: bool = False, skip_markers: tuple = (), kind: str = "doctor") -> str | None:
    """Why `out` may not be written, else None. The report may not land in what the scan reads: not in a zone, not under skills/, not in a
    scanned skill, and not in a scanned root unless the folder in between (.tmp, .worktrees, a cache...) is one the scan leaves out.
    It may not carry a secret-looking name or an NTFS stream, and an existing file is overwritten only when it is empty or already what `kind` writes:
    `doctor` and `catalog-json` a .json file that starts with {"schema"; `catalog-md` a .md file whose first line is <!-- studio catalog --> (its messages
    say --md, the others --out). Order matters: every decision by name, zone or cloud attributes on the spelling given
    and on the real folder comes first; the file itself is stat-ed and its first bytes read last, only once it is known to be a plain
    local path (so a link into ~/.secret or a cloud folder is refused without one call on the file, and with the same message whatever it holds)."""
    if kind not in OUT_KINDS:
        raise ValueError("unknown out kind: %s" % kind)
    flag = "--md" if kind == "catalog-md" else "--out"
    markers = C.CLOUD_MARKERS + tuple(skip_markers)
    reason = fs.zone_reason(out, markers)
    if reason:
        return "%s is inside a %s zone" % (flag, reason)
    if os.name == "nt" and ":" in os.path.splitdrive(os.fspath(out))[1]:
        return "%s names an NTFS data stream: %s" % (flag, out.name)
    if fs.secret_file_name(out.name):
        return "%s has a secret-looking file name: %s" % (flag, out.name)
    try:
        real_parent = out.parent.resolve()
    except (OSError, RuntimeError):
        return "%s cannot be resolved: %s" % (flag, out)
    real = real_parent / out.name
    reason = fs.zone_reason(real, markers)
    if reason:
        return "%s is inside a %s zone (through a link)" % (flag, reason)
    if fs.path_is_cloud(real_parent) or fs.path_is_cloud(out.parent):
        return "%s is inside a cloud placeholder folder: %s" % (flag, out.parent)
    if fs.path_is_cloud(real) or fs.path_is_cloud(out):
        return "%s is a cloud placeholder: %s" % (flag, out)
    if any(part.lower() == "skills" for part in out.parts[:-1]) or (repo is not None and fs.valid_resolved_under(real, repo / "skills")):
        return "%s must not be under a skills/ folder: %s" % (flag, out)
    if any(fs.valid_resolved_under(real, skill) for skill in skills):
        return "%s must not be inside a scanned skill folder: %s" % (flag, out)
    for root in roots:
        if fs.zone_reason(root, markers):
            continue
        try:
            below = real.parent.relative_to(Path(root).resolve()).parts
        except (ValueError, OSError, RuntimeError):
            continue
        if not any(_is_excluded(below[:n], include_cache) for n in range(1, len(below) + 1)):
            return "%s must not be inside a scanned root (a folder the scan skips, such as .tmp, is fine): %s" % (flag, out)
    if not real_parent.is_dir():
        return "folder of %s does not exist: %s (doctor never creates folders)" % (flag, out.parent)
    if out.is_dir() or fs.is_link(out):
        return "%s must be a plain file path: %s" % (flag, out)
    if out.exists():
        if out.suffix.lower() != (".md" if kind == "catalog-md" else ".json"):
            return "%s would overwrite an existing file that is not a %s: %s" % (flag, ".md catalog" if kind == "catalog-md" else ".json report", out)
        try:
            with open(out, "rb") as handle:
                head = handle.read(64)
        except OSError:
            return "%s exists and cannot be checked: %s" % (flag, out)
        if kind == "catalog-md":
            if head.strip() and not C.CATALOG_MD_HEAD.match(head):
                return "%s would overwrite an existing file that is not a catalog (its first line must be <!-- studio catalog -->): %s" % (flag, out)
        elif head.strip() and not C.DOCTOR_REPORT_HEAD.match(head):
            return "%s would overwrite an existing file that is not a %s (it must start with {\"schema\"): %s" % (flag, "doctor report" if kind == "doctor" else "catalog report", out)
    return None


_out_problem = out_problem  # the name this function had before it was public (SPR-04 TK5)


def _opcos_roots(markers: tuple) -> list:
    """The Root records of `--roots-from opcos`: paths.json from OPCOS_ROOT or up from the working folder, its areas turned into roots. ValueError (the
    message is printed, exit 2) when there is no paths.json, it cannot be used, or no root is usable (FR1.3)."""
    try:
        found = roots_mod.find_paths_json(Path.cwd(), os.environ, markers)
        if found is None:
            raise ValueError("paths.json not found (looked in $OPCOS_ROOT and up to %d folders above %s)" % (C.PATHS_JSON_UP, Path.cwd()))
        listed = roots_mod.opcos_roots(found, True, markers)
    except roots_mod.RootError as exc:
        raise ValueError("paths.json cannot be used: %s" % exc)
    if all(r["status"] == "error" for r in listed):
        raise ValueError("no usable root in %s: %s" % (found, "; ".join("%s %s" % (r["area"], "/".join(r["reasons"])) for r in listed)))
    return listed


def cmd_doctor(args) -> int:
    """Report-only scan of many skill roots. Exit 0 nothing at the --fail-on level, 1 findings, 2 could not scan."""
    repo = fs.repo_root(Path(__file__)) or fs.repo_root(Path.cwd())
    skip_markers = tuple(x.strip() for x in (args.skip_marker or []))
    if any(not x for x in skip_markers):
        print("ERROR: --skip-marker needs non-empty text", file=sys.stderr)
        return 2
    markers = C.CLOUD_MARKERS + skip_markers
    opcos = None  # --roots-from opcos: the Root records of paths.json (SPR-04 FR1); the scan itself is below, after the checks that need no scan
    if getattr(args, "roots_from", None):
        if args.roots or args.roots_file:
            print("ERROR: --roots-from cannot be combined with --roots or --roots-file", file=sys.stderr)
            return 2
        try:
            opcos = _opcos_roots(markers)
        except ValueError as exc:
            print("ERROR: %s" % exc, file=sys.stderr)
            return 2
        roots = [Path(r["path"]) for r in opcos if r["status"] != "error"]
    else:
        try:
            roots = parse_roots(args.roots, args.roots_file, repo, skip_markers)
        except ValueError as exc:
            print("ERROR: %s" % exc, file=sys.stderr)
            return 2
    baseline = None
    if args.fail_on == "new" and not args.baseline:
        print("ERROR: --fail-on new needs --baseline <earlier doctor --json report>", file=sys.stderr)
        return 2
    if args.baseline:
        source = Path(os.path.abspath(os.path.expanduser(args.baseline)))
        problem = fs.input_file_problem(source, markers)
        if problem is None:
            try:
                baseline = json.loads(source.read_text(encoding="utf-8"))
            except UnicodeError:
                problem = "cannot be read: not UTF-8 text"
            except OSError as exc:
                problem = "cannot be read (%s)" % (exc.strerror or type(exc).__name__)
            except ValueError as exc:
                problem = "cannot be read as JSON (line %s column %s)" % (getattr(exc, "lineno", "?"), getattr(exc, "colno", "?"))
            else:
                problem = _baseline_problem(baseline)
        if problem:
            print("ERROR: baseline %s %s" % (args.baseline, problem), file=sys.stderr)
            return 2
    out = None
    if args.out:  # decided by name and by what the file holds before any root is walked; the scanned skills are added after the scan
        out = Path(os.path.abspath(os.path.expanduser(args.out)))
        problem = out_problem(out, roots, repo, [], args.include_cache, skip_markers)
        if problem:
            print("ERROR: %s" % problem, file=sys.stderr)
            return 2
    if opcos is not None:
        found, listed = roots_mod.collect_skills(opcos, markers)
        scanned = ([s["path"] for s in found], listed)
    else:
        scanned = iter_skill_dirs(roots, args.include_cache, skip_markers)
    if out is not None:
        problem = out_problem(out, roots, repo, scanned[0], args.include_cache, skip_markers)
        if problem:
            print("ERROR: %s" % problem, file=sys.stderr)
            return 2
    pack_of = {_key(s["path"]): s["plugin"] for s in found} if opcos is not None else None
    report = doctor_run(roots, args.profile, args.target, args.include_cache, baseline, skip_markers, scanned,
                        by_pack=bool(getattr(args, "by_pack", False)), pack_of=pack_of, docs=bool(getattr(args, "docs", False)))
    if opcos is not None:
        report["roots_status"] = opcos
    if out is not None:
        try:
            with open(out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        except OSError as exc:
            print("ERROR: cannot write --out: %s" % exc, file=sys.stderr)
            return 2
    totals = report["totals"]
    if args.json and out is None:
        try:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        except UnicodeEncodeError:  # a console that cannot show every character
            print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print("doctor (profile %s, target %s): %d skills, %d errors, %d warnings, %d notes; %d skipped"
              % (args.profile, args.target, totals["skills"], totals["errors"], totals["warnings"], totals["notes"], len(report["skipped"])))
        for skill in report["skills"]:
            if skill["errors"] or skill["warnings"]:
                print("  %s: %d errors, %d warnings" % (skill["path"], skill["errors"], skill["warnings"]))
        for pack in report.get("packs", []):
            print("  " + pack_line(pack))
        for doc in report.get("docs", []):
            found = [c for c in doc["codes"] if c["level"] in ("ERROR", "WARN")]
            if found:
                print("  doc %s (%s): %d errors, %d warnings (%s)" % (doc["path"], doc["type"], sum(c["level"] == "ERROR" for c in found),
                                                                  sum(c["level"] == "WARN" for c in found), ", ".join(sorted({c["code"] for c in found}))))
        if "docs" in report:
            print("  docs: %d files checked" % len(report["docs"]))
        for item in report.get("roots_status", []):
            if item["status"] != "ok":
                print("  root %s: %s (%s)" % (item["area"], item["status"], ", ".join(item["reasons"])))
        for item in report["skipped"]:
            print("  skipped (%s): %s" % (item["reason"], item["path"]))
        for item in report["new_vs_baseline"]:
            print("  new vs baseline: %s %s %d -> %d" % (item["path"], item["code"], item["before"], item["after"]))
        if out is not None:
            print("report written to %s" % out)
    if args.fail_on == "new":
        found = bool(report["new_vs_baseline"])
    elif args.fail_on == "warn":
        found = bool(totals["errors"] or totals["warnings"])
    else:
        found = bool(totals["errors"])
    return 1 if found else 0
