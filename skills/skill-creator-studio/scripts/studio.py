#!/usr/bin/env python3
"""Agent Skill Studio: portable skill factory and static auditor.

Python 3.9+, standard library only. Supports a documented YAML frontmatter
subset (single-line string scalars, folded block strings, metadata string map).
This is a static validator, not a Claude/Codex/Antigravity evaluation runner.

Use `python3 studio.py --help` and per-subcommand --help.
"""

from __future__ import annotations

import argparse
import ast
import bisect
import errno
import functools
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Sibling modules (SPR-02 TK4) resolve from this folder only, whatever the cwd or how the engine was started.
_HERE = str(Path(__file__).resolve().parent)
if not sys.path or sys.path[0] != _HERE:
    sys.path.insert(0, _HERE)

import studio_const as C  # noqa: E402
import studio_evals as evals  # noqa: E402
import studio_fs as fs  # noqa: E402
import studio_lint as lint  # noqa: E402
import studio_validate as validate  # noqa: E402

# One engine, one folder: a sibling module already loaded from another folder (a stale or copied engine in this process) would
# mix two code bases, so refuse to run (FR4.5).
for _mod in [m for name, m in sorted(sys.modules.items()) if name.startswith("studio_") and getattr(m, "__file__", None)]:
    if Path(_mod.__file__).resolve().parent != Path(__file__).resolve().parent:
        sys.stderr.write("ERROR: engine module %s loaded from %s, expected %s\n"
                         % (_mod.__name__, Path(_mod.__file__).resolve().parent, Path(__file__).resolve().parent))
        sys.exit(2)


def get_template(full: bool = False, lang: str = "en") -> Path:
    """Minimal template: the SKILL.md / SKILL.vi.md file. Full template: the skill-template-full directory."""
    base = Path(__file__).resolve().parent.parent / "assets"
    if full:
        return base / "skill-template-full"
    return base / "skill-template" / ("SKILL.vi.md" if lang == "vi" else "SKILL.md")


def user_skill_root(agent: str) -> Path:
    """Per-user skill directory of an agent (FR19.1). Claude Code has none here: use --workspace."""
    if agent == "antigravity":
        return Path.home() / ".gemini" / "config" / "skills"
    if agent == "codex":
        return Path.home() / ".agents" / "skills"
    raise ValueError("--user is not supported for %s; use --workspace" % agent)


def cmd_new(args) -> int:
    name = args.name
    if not C.NAME_RE.fullmatch(name) or len(name) > 64:
        print("ERROR: name must be lowercase kebab-case <=64 chars", file=sys.stderr)
        return 2
    word = next((w for w in C.RESERVED_NAME_WORDS if w in name), None)
    if word:
        print("ERROR: name must not contain the reserved word '%s' (FM5)" % word, file=sys.stderr)
        return 2
    if not args.description or len(args.description) > 1024 or "\n" in args.description:
        print("ERROR: --description is required, single line and <=1024 characters", file=sys.stderr)
        return 2
    if args.full and args.lang != "en":
        print("ERROR: full template is English-only; drop --full or use --lang en", file=sys.stderr)
        return 2
    root = fs.repo_root(Path(__file__))
    output = Path(args.output).expanduser() if args.output else (root / "skills" if root else Path.cwd() / "skills")
    target = (output / name).resolve()
    if target.exists():
        print("ERROR: refusing to overwrite existing %s" % target, file=sys.stderr)
        return 1
    template = get_template(args.full, args.lang)
    if not ((template / "SKILL.md") if args.full else template).is_file():
        print("ERROR: bundled template missing at %s" % template, file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.full:
        shutil.copytree(template, target)
    else:
        target.mkdir()
        shutil.copyfile(template, target / "SKILL.md")
    p = target / "SKILL.md"
    content = p.read_text(encoding="utf-8")
    content = re.sub(r"^name: skill-template(-full)?$", lambda _m: "name: " + name, content, count=1, flags=re.MULTILINE)
    escaped = json.dumps(args.description, ensure_ascii=False)
    content = re.sub(r'^description: .*$', "description: " + escaped, content, count=1, flags=re.MULTILINE)
    content = content.replace("# Skill Template", "# " + name.replace("-", " ").title(), 1)
    p.write_text(content, encoding="utf-8")
    # Evals are outside runtime; do not invent test prompts or scores.
    external_eval = Path(args.eval_root).expanduser() if args.eval_root else ((root / "evals") if root else (Path.cwd() / "evals"))
    ef = external_eval / name
    ef.mkdir(parents=True, exist_ok=True)
    (ef / "fixtures").mkdir(exist_ok=True)
    (ef / "baselines").mkdir(exist_ok=True)
    sample = [
        {"id": "%s-typical" % name, "kind": "typical", "should_trigger": True},
        {"id": "%s-edge" % name, "kind": "edge", "should_trigger": True},
        {"id": "%s-negative" % name, "kind": "near-miss", "should_trigger": False},
    ]
    cases = [{**c, "prompt": "STUDIO-DRAFT: replace with a realistic %s prompt" % c["kind"],
              "expected_behaviors": ["STUDIO-DRAFT: replace with observable behavior"], "fixtures": []} for c in sample]
    (ef / "cases.json").write_text(json.dumps({"skill_name": name, "status": "draft", "cases": cases}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ef / "rubric.md").write_text("# %s — evaluation rubric (draft)\n\nDefine actual success criteria, trigger expectations, and failure cases before release.\n" % name, encoding="utf-8")
    (ef / "baselines" / "BASELINE.md").write_text("# Baseline: NOT RUN\n\nRecord fresh-session model/runtime, prompt, outputs, score and evidence after real execution.\n", encoding="utf-8")
    print("Created draft Skill: %s\nExternal evals: %s\nNext: replace STUDIO-DRAFT in the 3 sample eval cases, write real references, then validate." % (target, ef))
    return 0


def find_skills(args):
    root = fs.repo_root(Path(__file__)) or fs.repo_root(Path.cwd())
    if args.all:
        if root is None:
            raise ValueError("--all requires Studio repository; use an explicit Skill path")
        return fs.skill_dirs(root)
    if not args.skill:
        raise ValueError("provide a skill path or --all")
    return [Path(args.skill).expanduser()]


def cmd_check(args, audit: bool = False) -> int:
    try:
        folders = find_skills(args)
    except ValueError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    reports = []
    root = fs.repo_root(Path(__file__))
    external = Path(args.eval_root) if args.eval_root else (root / "evals" if root else None)
    for folder in folders:
        findings = validate.validate_skill(folder, eval_root=external, require_evals=args.require_evals, target=getattr(args, "target", "portable"))
        reports.append({"skill": str(folder), "findings": findings})
    if args.json:
        print(json.dumps({"audit": audit, "reports": reports}, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            validate.print_findings(Path(report["skill"]), report["findings"])
        if audit:
            print("\nAUDIT IS READ-ONLY. Semantic review is required for SK-03/04/06/07/08/10/12/14 (SK-14 is only partly machine-checked by CT10); model tests were not run.")
    return 1 if any(f["level"] == "ERROR" for x in reports for f in x["findings"]) else 0


def cmd_evals_export(args, paths: list[Path]) -> int:
    out_root = Path(args.out or C.EXPORT_DEFAULT_OUT).expanduser()
    reports, worst = [], 0
    for path in paths:
        code, findings, stats = evals.export_agentskills(path, path.name, out_root, force=args.force)
        worst = 2 if code == 2 or worst == 2 else max(worst, code)
        reports.append({"skill": path.name, "exit": code, "findings": findings, "stats": stats})
    if args.json:
        print(json.dumps({"reports": reports, "model_runs_performed": 0}, ensure_ascii=False, indent=2))
        return worst
    for item in reports:
        for f in item["findings"]:
            print("ERROR: %s %s: %s" % (item["skill"], f["code"], f["message"]), file=sys.stderr)
        if item["exit"] == 0:
            stats = item["stats"]
            print("exported %d, excluded %d" % (stats["exported"], stats["excluded_negative"]))
            print("  excluded cases are should_trigger: false; agentskills evals have no negative-case field")
            print("  wrote %s" % stats["path"])
    return worst


def cmd_evals(args) -> int:
    root = fs.repo_root(Path(__file__)) or fs.repo_root(Path.cwd())
    eval_root = Path(args.eval_root) if args.eval_root else (root / "evals" if root else None)
    if eval_root is None:
        print("ERROR: provide --eval-root for non-Studio repository", file=sys.stderr)
        return 2
    if not args.export and (args.out is not None or args.force):
        print("ERROR: --out and --force only apply together with --export agentskills", file=sys.stderr)
        return 2
    if args.all:
        paths = sorted(p for p in eval_root.iterdir() if p.is_dir() and any((p / m).exists() for m in ("cases.json", "rubric.md", "fixtures", "baselines", "expected"))) if eval_root.is_dir() else []
    elif args.skill:
        paths = [eval_root / Path(args.skill).name]
    else:
        print("ERROR: specify --all or skill name", file=sys.stderr)
        return 2
    if args.export:
        return cmd_evals_export(args, paths)
    reports = []
    for path in paths:
        findings = evals.check_evals(path)
        reports.append({"skill": path.name, "findings": findings})
    if args.json:
        print(json.dumps({"reports": reports, "model_runs_performed": 0}, ensure_ascii=False, indent=2))
    else:
        for item in reports:
            validate.print_findings(eval_root / item["skill"], item["findings"])
        print("Schema-only evaluation: NO model sessions were executed.")
    return 1 if any(f["level"] == "ERROR" for x in reports for f in x["findings"]) else 0


def ensure_distributable(folder: Path) -> tuple[list[Path], list[dict]]:
    findings = validate.validate_skill(folder)
    manifest = folder / "SKILL.md"
    if manifest.is_file() and re.search(r"<!--\s*STUDIO-DRAFT", manifest.read_text(encoding="utf-8")):
        findings.append(fs.emit("ERROR", "PACK", manifest, 0, "cannot package an unfinished template: remove draft marker after authoring"))
    files = []
    paths, links, dirs, cloud, cut = fs.walk_files(folder, skip_names=C.SKIP_DIRS)  # no rglob: links and cloud placeholders are listed, never entered or opened
    if cut:
        findings.append(fs.emit("ERROR", "PACK", folder, 0, "skill tree is over the scan limit (%d entries or %d folder levels); nothing is packaged short, trim the tree"
                             % (C.DOCTOR_MAX_FILES_PER_SKILL, C.DOCTOR_MAX_SKILL_DEPTH)))
    for p in paths:
        if p in cloud:
            findings.append(fs.emit("ERROR", "PACK", p, 0, "cloud placeholder; not read, not packaged"))
        elif p in links:
            findings.append(fs.emit("ERROR", "PACK", p, 0, "symlink or junction; not followed, not packaged"))
        elif p in dirs:
            if fs.zone_named(p.name):
                findings.append(fs.emit("ERROR", "PACK", p, 0, "folder named like a cloud/secret zone; not entered, not packaged"))
        else:
            files.append(p)
    kept = []
    for p in files:
        if fs.secret_file_name(p.name) or p.suffix.lower() in C.REJECT_SUFFIXES:  # the same name rule as --export, any letter case
            findings.append(fs.emit("ERROR", "SEC", p, 0, "secret/credential-like file must not be shipped; remove it from the Skill (nothing is packaged or installed)"))
            continue
        try:
            info = os.lstat(p)
        except OSError as exc:
            findings.append(fs.emit("ERROR", "PACK", p, 0, "cannot stat: %s" % (exc.strerror or type(exc).__name__)))
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        if info.st_size > 25 * 1024 * 1024:
            findings.append(fs.emit("ERROR", "PACK", p, 0, "file exceeds 25 MB; review before shipping"))
            continue
        if p.suffix.lower() in {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".sh"}:
            try:
                with fs.open_nofollow_read(p, info) as handle:
                    raw = handle.read().decode("utf-8")
            except fs.UnsafeOpen as exc:
                findings.append(fs.emit("ERROR", "PACK", p, 0, "not packaged: %s" % exc))
                continue
            except (OSError, UnicodeError):
                raw = ""
            if ("-----BEGIN " + "PRIVATE KEY-----") in raw or re.search(r"\b(?:sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})\b", raw):
                findings.append(fs.emit("ERROR", "SEC", p, 0, "possible hardcoded secret in package"))
        kept.append(p)
    return kept, findings


def cmd_package(args) -> int:
    folder = Path(args.skill).expanduser().resolve()
    if not folder.is_dir():
        print("ERROR: skill folder not found: %s" % folder, file=sys.stderr)
        return 2
    files, findings = ensure_distributable(folder)
    if any(f["level"] == "ERROR" for f in findings):
        validate.print_findings(folder, findings)
        print("Package blocked; correct errors before trying again.", file=sys.stderr)
        return 1
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / (folder.name + ".zip")
    if target.exists() and not args.force:
        print("ERROR: package exists: %s; choose another --out or explicitly --force" % target, file=sys.stderr)
        return 1
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                arcname = str(Path(folder.name) / p.relative_to(folder))
                with fs.open_nofollow_read(p, os.lstat(p)) as handle:  # the file that was checked, never a link put there since
                    data = handle.read()
                zf.writestr(zipfile.ZipInfo.from_file(p, arcname), data, compress_type=zipfile.ZIP_DEFLATED)
    except fs.UnsafeOpen as exc:
        fs._remove_quietly(target)
        print("ERROR: PACK: %s; nothing was packaged" % exc, file=sys.stderr)
        return 1
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print("Packaged %d runtime files -> %s\nSHA256: %s\nExcluded: evals/, tests/ and cache folders (any letter case); a secret-named file stops the package instead. Model evaluation status is unchanged." % (len(files), target, digest))
    return 0


def root_link_in_chain(skill_root: Path, stop: Path):
    """First link/junction among `skill_root` and its parents strictly below `stop` (HOME or the workspace itself is not checked), else None."""
    current, stop_norm = Path(skill_root), os.path.normcase(os.path.abspath(stop))
    while os.path.normcase(os.path.abspath(current)) != stop_norm and current.parent != current:
        if fs.is_link(current):
            return current
        current = current.parent
    return None


class MoveAsideError(OSError):
    """The copy at `dst` is complete but the old folder could not be fully removed: it may be partly gone. The message names the copy."""


def move_aside(src: Path, dst: Path) -> None:
    """Move the folder `src` to `dst` (same device: rename). Only when the rename fails because `dst` is on another device (EXDEV, Windows error 17) is the
    folder copied first and `src` deleted after; any other rename failure (a locked file, a permission) is raised at once with `src` untouched. A failed copy
    removes the half-made `dst` and re-raises, so `src` stays whole; a failed delete after a good copy raises MoveAsideError."""
    try:
        os.rename(src, dst)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
            raise
    try:
        shutil.copytree(src, dst, symlinks=True)
    except BaseException:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    try:
        shutil.rmtree(src)
    except OSError as exc:
        raise MoveAsideError(exc.errno, "the backup is complete at %s but the old Skill could not be fully removed (%s); it may be partly deleted" % (dst, exc.strerror or type(exc).__name__)) from exc


def cmd_install(args) -> int:
    folder = Path(args.skill).expanduser().resolve()
    if not folder.is_dir():
        print("ERROR: skill folder not found", file=sys.stderr)
        return 2
    if args.user:
        try:
            skill_root = user_skill_root(args.agent)
        except ValueError as exc:
            print("ERROR: %s" % exc, file=sys.stderr)
            return 2
        if not skill_root.parent.is_dir():
            print("ERROR: parent directory not found: %s; nothing was created" % skill_root.parent, file=sys.stderr)
            return 2
        boundary = Path.home()
    files, findings = ensure_distributable(folder)
    if any(f["level"] == "ERROR" for f in findings):
        validate.print_findings(folder, findings)
        return 1
    if not args.user:
        rel = Path(".claude") / "skills" if args.agent == "claude" else Path(".agents") / "skills"
        workspace = Path(args.workspace or ".").expanduser().resolve()
        if not workspace.is_dir():
            print("ERROR: workspace directory not found: %s" % workspace, file=sys.stderr)
            return 2
        skill_root = workspace / rel
        boundary = workspace
    linked = root_link_in_chain(skill_root, boundary)
    if linked is not None:
        real = os.path.realpath(skill_root)
        if not args.allow_root_link:
            print("ERROR: skill folder %s is behind a link (%s); its real location is %s. Nothing was installed. Re-run with --allow-root-link if that is intended."
                  % (skill_root, linked, real), file=sys.stderr)
            return 2
        print("Note: skill folder %s is behind a link (%s); installing into its real location %s" % (skill_root, linked, real))
    dest = skill_root / folder.name
    if dest.resolve() == folder or fs.valid_resolved_under(dest, folder):
        print("ERROR: destination is the source Skill or nested under it; refusing self-overwrite", file=sys.stderr)
        return 1
    if os.path.lexists(dest) and fs.is_link(dest):  # before exists(): a dangling link is not "there" for exists() and would crash mkdir
        print("ERROR: symlink destination refused", file=sys.stderr)
        return 1
    if dest.exists() and not args.force:
        print("ERROR: %s exists; no changes made. Use --force only if you intend replacement." % dest, file=sys.stderr)
        return 1
    backup = None
    if dest.exists() and args.force:
        # Back up rather than silently erase; the backup lives next to the skill root, not in it, so the agent never loads it.
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backups_dir = skill_root.parent / ".skill-studio-backups"
        if os.path.lexists(backups_dir) and fs.is_link(backups_dir):
            print("ERROR: backup folder %s is a link; nothing was changed" % backups_dir, file=sys.stderr)
            return 1
        backup = backups_dir / (dest.name + "-" + stamp)
        if os.path.lexists(backup):
            print("ERROR: backup collision", file=sys.stderr)
            return 1
        try:
            backups_dir.mkdir(exist_ok=True)
            move_aside(dest, backup)
        except MoveAsideError as exc:
            print("ERROR: %s. Nothing new was installed; restore from the backup if the Skill folder is incomplete." % exc.strerror, file=sys.stderr)
            return 1
        except OSError as exc:
            print("ERROR: could not back up the existing installation (%s); the old Skill was left in place" % (exc.strerror or type(exc).__name__), file=sys.stderr)
            return 1
        print("Existing installation backed up to %s" % backup)
    dest.mkdir(parents=True, exist_ok=False)  # creates skill_root itself, never the agent's config parent
    try:
        for source in files:
            destination = dest / source.relative_to(folder)
            destination.parent.mkdir(parents=True, exist_ok=True)
            inner = fs.link_in_chain(destination.parent, dest)
            if inner is not None:
                raise fs.UnsafeOpen("link inside the destination: %s" % inner)
            info = os.lstat(source)
            with fs.open_nofollow_read(source, info) as src_handle, fs.create_exclusive(destination) as dst_handle:
                shutil.copyfileobj(src_handle, dst_handle)
            os.chmod(destination, stat.S_IMODE(info.st_mode))
    except (fs.UnsafeOpen, OSError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        if backup is not None:
            try:
                os.rename(backup, dest)
            except OSError:
                print("ERROR: the old Skill is kept at %s" % backup, file=sys.stderr)
        print("ERROR: install stopped: %s; no partial Skill was left" % exc, file=sys.stderr)
        return 1
    print("Installed %s for %s at %s. This copies files; it does not run the agent or its scripts." % (folder.name, args.agent, dest))
    return 0


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
            lines = listing.read_text(encoding="utf-8").splitlines()
        except UnicodeError:
            raise ValueError("cannot read --roots-file %s: not UTF-8 text" % roots_file)
        except OSError as exc:
            raise ValueError("cannot read --roots-file %s: %s" % (roots_file, exc.strerror or type(exc).__name__))
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
        if not fs.zone_reason(path, markers) and not fs._is_dir_quiet(path):
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


def _skill_identity(skill: Path, target: str, max_bytes: int | None = None) -> tuple[str, str]:
    """(name, 'en'|'vi') from SKILL.md: frontmatter name (folder name when unreadable or above `max_bytes`) and the body language."""
    manifest = skill / "SKILL.md"
    try:
        text, too_big = fs.read_capped(manifest, max_bytes)
    except (OSError, UnicodeError):
        return skill.name, "en"
    if too_big:
        return skill.name, "en"
    meta, _, body_start = fs.parse_frontmatter(text, manifest, C.CLAUDE_CODE_KEYS if target == "claude-code" else frozenset())
    name = meta.get("name") if isinstance(meta.get("name"), str) and meta["name"] else skill.name
    return name, lint.detect_lang("\n".join(text.splitlines()[body_start:]))


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


def doctor_run(roots: list, profile: str, target: str, include_cache: bool, baseline: dict | None,
               skip_markers: tuple = (), scanned: tuple | None = None) -> dict:
    """The doctor report (SPEC 9.11, schema 1). Reads skills, writes nothing. `scanned` = a finished iter_skill_dirs result to reuse.
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
    for skill in skills:
        under = next((r for r in real_roots if fs.valid_resolved_under(skill, r)), None)
        findings = validate.validate_skill(skill, require_evals=False, target=target, profile=profile, allow_links_under=under,
                                  max_file_bytes=C.DOCTOR_MAX_FILE_BYTES, skip_markers=skip_markers)
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
        name, lang = _skill_identity(skill, target, C.DOCTOR_MAX_FILE_BYTES)
        errors, warnings = sum(c["level"] == "ERROR" for c in codes), sum(c["level"] == "WARN" for c in codes)
        entries.append({"path": _posix(skill), "name": name, "lang": lang, "errors": errors, "warnings": warnings, "codes": codes})
        totals["skills"] += 1
        totals["errors"] += errors
        totals["warnings"] += warnings
        totals["notes"] += sum(c["level"] == "NOTE" for c in codes)
    report = {"schema": C.DOCTOR_SCHEMA, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "studio_version": C.VERSION, "roots": [_posix(r) for r in roots], "skills": entries, "skipped": skipped,
              "totals": totals, "new_vs_baseline": []}
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


def _out_problem(out: Path, roots: list, repo: Path | None, skills: list = (), include_cache: bool = False, skip_markers: tuple = ()) -> str | None:
    """Why `out` may not be written, else None. The report may not land in what the scan reads: not in a zone, not under skills/, not in a
    scanned skill, and not in a scanned root unless the folder in between (.tmp, .worktrees, a cache...) is one the scan leaves out.
    It may not carry a secret-looking name or an NTFS stream, and an existing file is overwritten only when it is empty or already a doctor
    report (a .json file that starts with {"schema"). Order matters: every decision by name, zone or cloud attributes on the spelling given
    and on the real folder comes first; the file itself is stat-ed and its first bytes read last, only once it is known to be a plain
    local path (so a link into ~/.secret or a cloud folder is refused without one call on the file, and with the same message whatever it holds)."""
    markers = C.CLOUD_MARKERS + tuple(skip_markers)
    reason = fs.zone_reason(out, markers)
    if reason:
        return "--out is inside a %s zone" % reason
    if os.name == "nt" and ":" in os.path.splitdrive(os.fspath(out))[1]:
        return "--out names an NTFS data stream: %s" % out.name
    if fs.secret_file_name(out.name):
        return "--out has a secret-looking file name: %s" % out.name
    try:
        real_parent = out.parent.resolve()
    except (OSError, RuntimeError):
        return "--out cannot be resolved: %s" % out
    real = real_parent / out.name
    reason = fs.zone_reason(real, markers)
    if reason:
        return "--out is inside a %s zone (through a link)" % reason
    if fs.path_is_cloud(real_parent) or fs.path_is_cloud(out.parent):
        return "--out is inside a cloud placeholder folder: %s" % out.parent
    if fs.path_is_cloud(real) or fs.path_is_cloud(out):
        return "--out is a cloud placeholder: %s" % out
    if any(part.lower() == "skills" for part in out.parts[:-1]) or (repo is not None and fs.valid_resolved_under(real, repo / "skills")):
        return "--out must not be under a skills/ folder: %s" % out
    if any(fs.valid_resolved_under(real, skill) for skill in skills):
        return "--out must not be inside a scanned skill folder: %s" % out
    for root in roots:
        if fs.zone_reason(root, markers):
            continue
        try:
            below = real.parent.relative_to(Path(root).resolve()).parts
        except (ValueError, OSError, RuntimeError):
            continue
        if not any(_is_excluded(below[:n], include_cache) for n in range(1, len(below) + 1)):
            return "--out must not be inside a scanned root (a folder the scan skips, such as .tmp, is fine): %s" % out
    if not real_parent.is_dir():
        return "folder of --out does not exist: %s (doctor never creates folders)" % out.parent
    if out.is_dir() or fs.is_link(out):
        return "--out must be a plain file path: %s" % out
    if out.exists():
        if out.suffix.lower() != ".json":
            return "--out would overwrite an existing file that is not a .json report: %s" % out
        try:
            with open(out, "rb") as handle:
                head = handle.read(64)
        except OSError:
            return "--out exists and cannot be checked: %s" % out
        if head.strip() and not C.DOCTOR_REPORT_HEAD.match(head):
            return "--out would overwrite an existing file that is not a doctor report (it must start with {\"schema\"): %s" % out
    return None


def cmd_doctor(args) -> int:
    """Report-only scan of many skill roots. Exit 0 nothing at the --fail-on level, 1 findings, 2 could not scan."""
    repo = fs.repo_root(Path(__file__)) or fs.repo_root(Path.cwd())
    skip_markers = tuple(x.strip() for x in (args.skip_marker or []))
    if any(not x for x in skip_markers):
        print("ERROR: --skip-marker needs non-empty text", file=sys.stderr)
        return 2
    markers = C.CLOUD_MARKERS + skip_markers
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
        problem = _out_problem(out, roots, repo, [], args.include_cache, skip_markers)
        if problem:
            print("ERROR: %s" % problem, file=sys.stderr)
            return 2
    scanned = iter_skill_dirs(roots, args.include_cache, skip_markers)
    if out is not None:
        problem = _out_problem(out, roots, repo, scanned[0], args.include_cache, skip_markers)
        if problem:
            print("ERROR: %s" % problem, file=sys.stderr)
            return 2
    report = doctor_run(roots, args.profile, args.target, args.include_cache, baseline, skip_markers, scanned)
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


def _fm_bounds(lines: list) -> tuple | None:
    """(0, closing index) when line 0 is '---' and a closing '---' follows, else None. Both lines are '---' in column 0 (blanks after them
    are allowed): an indented '---' neither opens the frontmatter nor, inside a block scalar, closes it."""
    if not lines or lines[0].rstrip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            return 0, index
    return None


def _fm_blocks(block_lines: list) -> tuple[list, list]:
    """(lines before the first key, [(key, [the key line and every line after it up to the next top-level key])])."""
    pre, blocks = [], []
    for line in block_lines:
        match = None if line[:1].isspace() else C.FRONT_KEY_RE.fullmatch(line)
        if match:
            blocks.append((match.group(1), [line]))
        else:
            (blocks[-1][1] if blocks else pre).append(line)
    return pre, blocks


def _looks_like_front(lines: list) -> bool:
    """lines[0] is '---', a closing '---' follows, and between them every plain line is `key: value` (at least one key)."""
    bounds = _fm_bounds(lines)
    if not bounds:
        return False
    keys = 0
    for line in lines[1:bounds[1]]:
        if not line.strip() or line[:1].isspace() or line.lstrip().startswith("#"):
            continue
        if not C.FRONT_KEY_RE.fullmatch(line):
            return False
        keys += 1
    return keys > 0


def _quote_meta(line: str) -> tuple[str, str]:
    """(the line, status) for one line of a metadata block. `fixed`: the value is now in double quotes. `stuck`: the value is not a plain
    string fmt can quote safely (a comment, a block or flow marker, an unmatched quote) and the line stays as it is. `ok`: nothing to do."""
    match = C.FMT_META_LINE_RE.match(line.rstrip(" \t"))  # only the blanks FT1 removes: a no-break space belongs to the value
    if not match:
        return line, "ok"
    value = match.group(2)
    if value[0] == '"':
        return line, "ok"
    if value[0] == "'" and len(value) >= 2 and value[-1] == "'":
        value = value[1:-1].replace("''", "'")
    elif value[0] in "[{>|&*!%@`'" or " #" in value or "\t#" in value or ": " in value:
        return line, "stuck"
    return "%s %s" % (match.group(1), json.dumps(value, ensure_ascii=False)), "fixed"


def fmt_text(text: str, kind: str, profile: str = "portable") -> tuple[str, list]:
    """Pure (no I/O): (the text in house style, findings FT1-FT5). `kind` is skill, process, studio-doc or other. A finding is
    {level, code, line, message, fixable}; the returned text has every fixable one applied and the words of the body unchanged.
    `profile` is accepted for symmetry with doctor: fmt adds no opcos metadata, so it changes nothing here."""
    if profile not in C.PROFILES:
        raise ValueError("unknown profile %r" % profile)
    found: list[dict] = []

    def add(code: str, line: int, message: str, fixable: bool) -> None:
        found.append({"level": "ERROR", "code": code, "line": line, "message": message, "fixable": fixable})

    new = text
    if new.startswith("﻿"):
        add("FT1", 1, "byte order mark", True)
        new = new.lstrip("﻿")
    if "\r" in new:
        add("FT1", len(re.findall(r"\r\n|\r|\n", new[:new.index("\r")])) + 1, "CR or CRLF line ending; use LF", True)
        new = new.replace("\r\n", "\n").replace("\r", "\n")
    lines = new.split("\n")
    trailing = [i + 1 for i, line in enumerate(lines) if line != line.rstrip(" \t")]
    if trailing:
        add("FT1", trailing[0], "trailing whitespace on %d line(s)" % len(trailing), True)
        lines = [line.rstrip(" \t") for line in lines]
    joined = "\n".join(lines)
    core = joined.rstrip("\n")
    wanted = core + "\n" if core else ""
    if joined != wanted:
        add("FT1", len(lines), "no final newline" if not joined.endswith("\n") else "more than one final newline", True)
    lines = wanted.split("\n")[:-1] if wanted else []

    lead = next((i for i, line in enumerate(lines) if line.strip()), 0)
    if kind != "other" and lines and lines[lead].strip() == "---" and lines[lead] != "---" and _looks_like_front(["---"] + lines[lead + 1:]):
        add("FT5", lead + 1, "the opening '---' of the frontmatter must be in column 0 (line %d is indented)" % (lead + 1), False)
    elif lead and _looks_like_front(lines[lead:]):
        add("FT5", 1, "%d blank line(s) before the frontmatter; it must start on line 1" % lead, True)
        lines = lines[lead:]
    elif kind != "other" and not (lines and lines[0] == "---"):
        fences = 0
        for index in range(1, min(len(lines), C.FMT_FRONT_SEARCH_LINES)):
            if C.FENCE_OPEN_RE.match(lines[index]):
                fences += 1
            elif lines[index] == "---" and fences % 2 == 0 and _looks_like_front(lines[index:]):
                block = lines[index + 1:index + _fm_bounds(lines[index:])[1]]
                if any(C.FRONT_KEY_RE.fullmatch(x) and C.FRONT_KEY_RE.fullmatch(x).group(1) in ("name", "description", "title", "status", "updated") for x in block):
                    add("FT5", index + 1, "frontmatter starts on line %d; it must start on line 1" % (index + 1), False)
                break

    bounds = _fm_bounds(lines)
    if kind == "skill" and bounds:
        pre, blocks = _fm_blocks(lines[1:bounds[1]])
        offset = 2 + len(pre)
        rebuilt = []
        for key, block in blocks:
            head = C.FRONT_KEY_RE.fullmatch(block[0])
            if key == "metadata" and head and not (head.group(2) or "").strip():
                quoted = [block[0]]
                for number, line in enumerate(block[1:], start=offset + 1):
                    changed, status = _quote_meta(line)
                    if status == "fixed":
                        add("FT3", number, "metadata value must be a double-quoted string", True)
                    elif status == "stuck":
                        add("FT3", number, "metadata value is not a plain string (comment, block or flow marker, unmatched quote): quote it by hand", False)
                    quoted.append(changed)
                block = quoted
            rebuilt.append((key, block))
            offset += len(block)
        rank = lambda key: C.FM_ORDER.index(key) if key in C.FM_ORDER else len(C.FM_ORDER)
        ordered = sorted(rebuilt, key=lambda item: rank(item[0]))
        if [k for k, _ in ordered] != [k for k, _ in rebuilt]:
            line = 2 + len(pre)
            for (have, block), (want, _) in zip(rebuilt, ordered):
                if have != want:
                    break
                line += len(block)
            add("FT2", line, "frontmatter keys out of order; expected %s, then any other keys in their own order" % ", ".join(C.FM_ORDER), True)
        lines = ["---"] + pre + [x for _, block in ordered for x in block] + lines[bounds[1]:]
    if kind == "studio-doc":
        keys = {key for key, _ in _fm_blocks(lines[1:bounds[1]])[1]} if bounds else set()
        missing = [key for key in C.DOC_MIN_KEYS if key not in keys]
        if missing:
            add("FT4", 1, "missing minimum frontmatter key(s): %s" % ", ".join(missing), False)
    found.sort(key=lambda item: item["line"])
    return ("\n".join(lines) + "\n" if lines else ""), found


def check_process_shape(text: str) -> list:
    """PR1 (WARN) for each part of the process-file shape (SPEC 9.13) that is missing. English or Vietnamese labels."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    bounds = _fm_bounds(lines)
    start = bounds[1] + 1 if bounds else 0
    body = lines[start:]
    heads: list[tuple] = []  # (index in body, level, title)
    plain: list[tuple] = []  # (index in body, line) outside code fences
    fence = None
    for index, line in enumerate(body):
        match = C.FENCE_OPEN_RE.match(line)
        if match:
            fence = None if fence == match.group(1)[0] else (fence or match.group(1)[0])
            continue
        if fence:
            continue
        plain.append((index, line))
        head = C.FMT_HEADING_RE.match(line.rstrip())
        if head:
            heads.append((index, len(head.group(1)), head.group(2)))
    found: list[dict] = []

    def warn(index: int, message: str) -> None:
        found.append({"level": "WARN", "code": "PR1", "line": start + index + 1, "message": message})

    if not any(level == 1 for _, level, _ in heads):
        warn(0, "process file has no '# <Name>' title")
    if not any(C.FMT_CONCLUSION_RE.match(line) for _, line in plain):
        warn(0, "process file has no '> **Conclusion:**' (VI '> **Kết luận:**') line")
    if len(body) > 100 and not any(C.CONTENTS_RE.match("## " + title) for _, level, title in heads if level == 2):
        warn(0, "process file is over 100 lines and has no '## Contents'")
    for pattern, label in C.FMT_PROCESS_SECTIONS:
        if not any(level == 2 and pattern.match(title) for _, level, title in heads):
            warn(0, "process file has no '## %s' section" % label)
    steps = [(i, title) for i, level, title in heads if level == 3 and C.FMT_STEP_RE.match(title)]
    if not steps:
        warn(0, "process file has no '### Step N — <verb>' (VI '### Bước N — <động từ>') section")
    ends = [i for i, level, _ in heads if level <= 3]  # ascending: a step's section stops at the next heading of level 3 or above
    plain_at = [i for i, _ in plain]
    for index, title in steps:
        at = bisect.bisect_right(ends, index)
        stop = ends[at] if at < len(ends) else len(body)
        section = [line for _, line in plain[bisect.bisect_right(plain_at, index):bisect.bisect_left(plain_at, stop)]]
        for pattern, label in C.FMT_STEP_LABELS:
            if not any(pattern.match(line) for line in section):
                warn(index, "step '%s' has no '%s'" % (title, label))
    return found


def classify_md(path: Path, root: Path | None) -> str:
    """skill (SKILL.md, SKILL.vi.md), process (*PROCESS*.md, *_WORKFLOW.md), studio-doc (standards/*.md, content/*.md, templates/README.md
    of the repo `root`) or other."""
    name = path.name
    if name in ("SKILL.md", "SKILL.vi.md"):
        return "skill"
    upper = name.upper()
    if upper.endswith(".MD") and ("PROCESS" in upper or upper.endswith("_WORKFLOW.MD")):
        return "process"
    if root is not None:
        try:
            parts = tuple(x.casefold() for x in Path(os.path.abspath(path)).relative_to(os.path.abspath(root)).parts)
        except ValueError:
            return "other"
        if len(parts) == 2 and parts[0] in ("standards", "content") and parts[1].endswith(".md"):
            return "studio-doc"
        if parts == ("templates", "readme.md"):
            return "studio-doc"
    return "other"


def _crosses_link(path) -> bool:
    """True when `path` itself or any folder on the way to it is a symlink or junction. The top-level folder of the volume is not looked at
    (/tmp and /var are links on macOS); every folder below it is, whether or not it lies under the repo."""
    parts = Path(os.path.abspath(path)).parts
    base = Path(parts[0])
    for depth, part in enumerate(parts[1:], start=1):
        base = base / part
        if (depth > 1 or depth == len(parts) - 1) and fs.is_link(base):
            return True
    return False


def iter_md(paths: list, all_repo: bool, root: Path | None, skipped: list | None = None) -> list[Path]:
    """The Markdown files to format: each given file, plus every *.md under each given folder (and under `root` with all_repo). Never
    entered or opened: links, cloud placeholders, cloud/secret zones, .git, .tmp, .worktrees, dist, node_modules, evals/**/runs. A file or
    folder left out is appended to `skipped` as {path, reason}."""
    skipped = skipped if skipped is not None else []
    files: list[Path] = []
    seen: set = set()

    def skip(path, reason: str) -> None:
        skipped.append({"path": str(path), "reason": reason})

    def take(path: Path) -> None:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            return
        seen.add(key)
        if not path.name.lower().endswith(".md"):
            skip(path, "not-markdown")
        elif fs.secret_file_name(path.name):
            skip(path, "secret-name")
        else:
            try:
                size = os.lstat(path).st_size
            except OSError:
                skip(path, "unreadable")
                return
            if size > C.DOCTOR_MAX_FILE_BYTES:
                skip(path, "limit")
            else:
                files.append(path)

    starts = [Path(os.path.abspath(os.path.expanduser(os.fspath(p)))) for p in paths]
    if all_repo and root is not None:
        starts.append(Path(os.path.abspath(root)))
    for start in starts:
        reason = fs.zone_reason(start)
        if reason:
            skip(start, reason)
        elif _crosses_link(start):
            skip(start, "link")
        elif fs.path_is_cloud(start):
            skip(start, "cloud")
        elif fs.zone_reason(os.path.realpath(start)):  # the resolved spelling (8.3 short names, case): checked last, after the lstat above
            skip(start, fs.zone_reason(os.path.realpath(start)))
        elif start.is_file():
            take(start)
        elif start.is_dir():
            stack, visited = [start], 0
            while stack:
                current = stack.pop()
                visited += 1
                if visited > C.DOCTOR_MAX_DIRS:
                    skip(current, "too-many-folders")
                    break
                try:
                    with os.scandir(current) as scan:
                        entries = sorted(scan, key=lambda e: e.name)
                except OSError:
                    skip(current, "unreadable")
                    continue
                for entry in entries:
                    child = Path(entry.path)
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        is_file = entry.is_file(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir or is_file:
                        if fs.entry_is_cloud(entry):
                            skip(child, "cloud")
                            continue
                    if entry.is_symlink() or (is_dir and fs.is_link(child)):
                        try:
                            to_dir = is_dir or entry.is_dir()  # a POSIX symlink to a folder is not is_dir(follow_symlinks=False): ask what it points at
                        except OSError:
                            to_dir = False
                        if to_dir or entry.name.lower().endswith(".md"):
                            skip(child, "link")
                    elif is_dir:
                        if entry.name in C.FMT_PRUNE_DIRS or (entry.name == "runs" and "evals" in (x.casefold() for x in child.parts)):
                            continue
                        if fs.zone_named(entry.name):
                            skip(child, "cloud-or-secret-zone")
                        else:
                            stack.append(child)
                    elif is_file and entry.name.lower().endswith(".md"):
                        take(child)
    return sorted(files)


def _body_words(text: str) -> list:
    """Words of what follows the frontmatter (the whole text without one), ignoring a BOM: the thing fmt --fix must not change."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines = lines[1:]
    bounds = _fm_bounds(lines)
    return ("\n".join(lines[bounds[1] + 1:]) if bounds else "\n".join(lines)).split()


def _write_fixed(path: Path, data: bytes, backup: bool) -> str | None:
    """Replace `path` with `data`: a copy `<name>.bak-<ISO>` first when `backup`, then a new temp file next to it (a name chosen by the system
    and created exclusively, so a link planted at a guessable name is never followed) and an atomic replace. A read-only file is refused
    before anything is made. Whatever this call made is removed again when it fails; the original file stays as it was. Returns the path of
    the backup, or None when none was asked for."""
    if not os.access(path, os.W_OK):
        raise PermissionError(13, "file is read-only", os.fspath(path))
    checked = os.lstat(path)  # the identity every read of `path` below must match (Windows has no O_NOFOLLOW)
    made_backup, temp, handle, done = None, None, None, False
    try:
        if backup:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            target, count = path.with_name("%s.bak-%s" % (path.name, stamp)), 1
            while True:
                try:
                    sink = fs.create_exclusive(target)  # O_EXCL: a name already there (a link included) is never written through
                    break
                except FileExistsError:
                    target = path.with_name("%s.bak-%s-%d" % (path.name, stamp, count))
                    count += 1
            made_backup = target  # set only once the exclusive create has succeeded, so a failure never removes a file we did not make
            with sink, fs.open_nofollow_read(path, checked, single_link=False) as source:
                shutil.copyfileobj(source, sink)
            try:
                shutil.copystat(path, target)
            except OSError:
                pass
        handle, name = tempfile.mkstemp(dir=os.fspath(path.parent), prefix=".%s." % path.name, suffix=".fmt-tmp")
        temp = Path(name)
        out, handle = os.fdopen(handle, "wb"), None
        with out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            shutil.copymode(path, temp)
        except OSError:
            pass
        os.replace(temp, path)
        done = True
        return os.fspath(made_backup) if made_backup is not None else None
    finally:
        if not done:
            if handle is not None:
                try:
                    os.close(handle)
                except OSError:
                    pass
            if temp is not None:
                fs._remove_quietly(temp)
            if made_backup is not None:
                fs._remove_quietly(made_backup)


def cmd_fmt(args) -> int:
    """`fmt --check` (default) lists FT*/PR1 findings and never writes; `fmt --fix` applies the fixable ones to the files named.
    Exit 0 nothing left at ERROR level, 1 an ERROR (FT*) remains, 2 a path does not exist or the request is refused."""
    fixing = bool(args.fix)
    repo = fs.repo_root(Path(__file__)) or fs.repo_root(Path.cwd())
    if args.profile not in C.PROFILES:
        print("ERROR: unknown profile %s" % args.profile, file=sys.stderr)
        return 2
    if args.no_backup and not fixing:
        print("ERROR: --no-backup needs --fix (check mode writes nothing)", file=sys.stderr)
        return 2
    if args.all and fixing:
        print("ERROR: --all only reports; give the files or folders to --fix", file=sys.stderr)
        return 2
    if not args.paths and not args.all:
        print("ERROR: give at least one file or folder, or --all", file=sys.stderr)
        return 2
    if args.all and repo is None:
        print("ERROR: --all needs to run inside the Studio repo", file=sys.stderr)
        return 2
    for given in args.paths:
        spelled = Path(os.path.abspath(os.path.expanduser(given)))
        if not fs.zone_reason(spelled) and not os.path.lexists(spelled):
            print("ERROR: path does not exist: %s" % given, file=sys.stderr)
            return 2
    skipped: list[dict] = []
    files = iter_md(args.paths, args.all, repo, skipped)
    named = {os.path.normcase(os.path.abspath(os.path.expanduser(given))) for given in args.paths}
    if args.all and repo is not None:
        named.add(os.path.normcase(os.path.abspath(repo)))
    results, errors, warnings, changed, backups = [], 0, 0, 0, 0
    for path in files:
        try:
            with fs.open_nofollow_read(path, os.lstat(path), single_link=False) as handle:  # lstat now, so Windows compares the opened handle with the listed file
                raw = handle.read()
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append({"path": str(path), "reason": "not-utf8"})
            continue
        except OSError:
            skipped.append({"path": str(path), "reason": "unreadable"})
            continue
        kind = classify_md(path, repo)
        new, found = fmt_text(text, kind, args.profile)
        wrote, backup = False, None
        if fixing and new != text:
            if _body_words(new) != _body_words(text):  # fmt_text is meant never to do this; refuse to write if it ever does
                skipped.append({"path": str(path), "reason": "would-change-text"})
                continue
            try:
                backup = _write_fixed(path, new.encode("utf-8"), backup=not args.no_backup)
            except OSError as exc:
                print("ERROR: cannot write %s: %s" % (path, exc.strerror or type(exc).__name__), file=sys.stderr)
                return 2
            wrote, changed = True, changed + 1
            backups += 1 if backup else 0
            found = fmt_text(new, kind, args.profile)[1]
        if kind == "process":
            found = found + check_process_shape(new if fixing else text)
        errors += sum(1 for f in found if f["level"] == "ERROR")
        warnings += sum(1 for f in found if f["level"] == "WARN")
        results.append({"path": str(path), "kind": kind, "changed": wrote, "backup": backup,
                        "findings": [dict(f, fixable=f.get("fixable", False)) for f in found]})
    # A file or folder that was asked for (or could not be read, was refused, or is over the size limit) and so was not checked keeps "exit 0 =
    # everything is in house style" true: it makes the exit code 1. A file left out while walking a folder because it is cloud, a link, a
    # secret name or in a secret zone is left out on purpose and does not.
    blocked = {id(item) for item in skipped if item["reason"] in C.FMT_BLOCKING_REASONS or os.path.normcase(os.path.abspath(item["path"])) in named}
    report = {"schema": 1, "mode": "fix" if fixing else "check", "files": results, "skipped": skipped,
              "totals": {"files": len(results), "changed": changed, "errors": errors, "warnings": warnings, "blocked": len(blocked)}}
    if args.json:
        try:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        except UnicodeEncodeError:
            print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        for item in results:
            for f in item["findings"]:
                print("%s:%d: %s %s %s%s" % (item["path"], f["line"], f["level"], f["code"], f["message"],
                                             " (fixable with --fix)" if f["fixable"] and not fixing else ""))
            if item["changed"]:
                print("fixed: %s" % item["path"])
        for item in skipped:
            print("skipped (%s): %s%s" % (item["reason"], item["path"], "  [blocks the exit]" if id(item) in blocked else ""))
        print("fmt --%s: %d files, %d changed, %d backups, %d errors, %d warnings, %d skipped, %d of them block the exit"
              % (report["mode"], len(results), changed, backups, errors, warnings, len(skipped), len(blocked)))
    return 1 if errors or blocked else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Skill Studio: create, audit, lint, package and install portable skills")
    parser.add_argument("--version", action="version", version=C.VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("new", help="scaffold a new Skill and an external, empty eval suite")
    p.add_argument("name")
    p.add_argument("--description", required=True)
    p.add_argument("--output", help="parent directory (default repo skills/)")
    p.add_argument("--eval-root", help="external evals directory (default repo evals/)")
    p.add_argument("--lang", choices=C.TEMPLATE_LANGS, default="en", help="language of the template body (default en); frontmatter stays English")
    p.add_argument("--full", action="store_true", help="scaffold the full English-only template (references/, scripts/, assets/, agents/)")
    p.set_defaults(func=cmd_new)
    for action in ("validate", "audit"):
        p = sub.add_parser(action, help="static %s, never edits files" % action)
        p.add_argument("skill", nargs="?", help="Skill folder")
        p.add_argument("--all", action="store_true", help="all canonical repo skills")
        p.add_argument("--require-evals", action="store_true", help="require matching external eval manifest")
        p.add_argument("--eval-root", help="where external evals are stored")
        p.add_argument("--target", choices=C.TARGETS, default="portable", help="portable (default) or claude-code (also accepts Claude Code only keys as FM6 warnings)")
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=lambda args, audit=(action == "audit"): cmd_check(args, audit))
    p = sub.add_parser("evals", help="validate eval manifest schemas (no model calls); with --export agentskills also write evals.json")
    p.add_argument("skill", nargs="?", help="Skill name")
    p.add_argument("--all", action="store_true")
    p.add_argument("--eval-root")
    p.add_argument("--export", choices=C.EXPORT_FORMATS, help="write the positive cases as <out>/<skill>/evals/evals.json in this format")
    p.add_argument("--out", help="export destination (default %s); must not be under skills/ or evals/" % C.EXPORT_DEFAULT_OUT)
    p.add_argument("--force", action="store_true", help="overwrite existing exported files")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_evals)
    p = sub.add_parser("package", help="produce portable runtime-only Skill ZIP")
    p.add_argument("skill")
    p.add_argument("--out", default="dist")
    p.add_argument("--force", action="store_true", help="replace existing ZIP explicitly")
    p.set_defaults(func=cmd_package)
    p = sub.add_parser("install", help="copy a Skill into a project's runtime discovery folder")
    p.add_argument("skill")
    p.add_argument("--agent", choices=("claude", "codex", "antigravity"), required=True)
    where = p.add_mutually_exclusive_group()
    where.add_argument("--workspace", help="project directory (default .)")
    where.add_argument("--user", action="store_true", help="install into the per-user skill folder (antigravity, codex; not claude); the agent's config folder must already exist")
    p.add_argument("--force", action="store_true", help="back up (to <skill root parent>/.skill-studio-backups/) and replace existing install")
    p.add_argument("--allow-root-link", action="store_true", help="install even when the skill folder (or a parent below HOME/the workspace) is a symlink or junction; the real target is printed")
    p.set_defaults(func=cmd_install)
    p = sub.add_parser("doctor", help="report-only scan of many skill roots (not Claude Code's /skill-doctor); exit 0 clean, 1 findings, 2 cannot scan")
    p.add_argument("--roots", help="skill roots separated by ';' (default: the repo's skills/; outside the repo --roots or --roots-file is required)")
    p.add_argument("--roots-file", help="file with one root per line, '#' starts a comment (at the line start or after whitespace)")
    p.add_argument("--profile", choices=C.PROFILES, default="portable", help="opcos: a link inside the scanned root is a WARN, provenance keys are WARN, missing metadata.opcos_* is a NOTE")
    p.add_argument("--target", choices=C.TARGETS, default="portable")
    p.add_argument("--include-cache", action="store_true", help="also scan folders whose name contains 'cache'")
    p.add_argument("--skip-marker", action="append", metavar="TEXT", help="skip any path containing TEXT (case-insensitive); repeatable. A synced SharePoint folder need not say 'SharePoint' (for example 'KPIM Joint Stock Company')")
    p.add_argument("--baseline", help="an earlier doctor JSON report; new_vs_baseline lists the (skill, code) pairs that grew")
    p.add_argument("--json", action="store_true", help="print the JSON report (with --out it goes to the file only)")
    p.add_argument("--out", help="write the JSON report here; the folder must exist; not under skills/, a scanned skill or a scanned root (a folder the scan skips, such as .tmp, is fine); not a secret-looking name")
    p.add_argument("--fail-on", choices=C.DOCTOR_FAIL_ON, default="error", help="what makes the exit code 1 (default error; new needs --baseline)")
    p.set_defaults(func=cmd_doctor)
    p = sub.add_parser("fmt", help="check (default) or fix the house style of Markdown files: line endings, key order, quoted metadata (never edits the words of the body)")
    p.add_argument("paths", nargs="*", help="files or folders (*.md); --fix only touches what is named")
    p.add_argument("--all", action="store_true", help="every *.md of the repo, report only (not with --fix)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="list findings, write nothing (default)")
    mode.add_argument("--fix", action="store_true", help="apply the fixable findings; every changed file is first copied to <file>.bak-<ISO> (see --no-backup)")
    p.add_argument("--no-backup", action="store_true", help="skip the <file>.bak-<ISO> copy; use when git or another backup already holds the files")
    p.add_argument("--profile", choices=C.PROFILES, default="portable")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fmt)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
