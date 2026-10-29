"""The `package` and `install` commands: check a skill is distributable, zip it, copy it into an agent's skill folder (SPR-02 TK4c).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import stat
import sys
import zipfile
from pathlib import Path

import studio_const as C
import studio_fs as fs
import studio_scaffold as scaffold
import studio_validate as validate


ENGINE_DEPS_REL = Path("scripts") / "ENGINE_DEPS"
ENGINE_DEP_NAME = re.compile(r"^studio_[a-z_]+\.py$")
ENGINE_DIR = Path(__file__).resolve().parent


def engine_extras(folder: Path) -> tuple[list[tuple[Path, Path]], list[dict]]:
    """The shared engine files a skill that lists them in `scripts/ENGINE_DEPS` takes along (SPR-04 FR9.3): ([(source, path inside the skill)], findings).
    One `studio_*.py` name per line ('#' comments and blank lines are skipped); each must be one of this running engine's own modules, never a link. The entry
    point `studio.py` always goes with them, because `doctor` of the packaged skill runs through it. A skill without the file takes nothing."""
    deps = folder / ENGINE_DEPS_REL
    if not os.path.lexists(deps):
        return [], []
    if os.path.lexists(folder / "scripts" / "_engine"):
        return [], [fs.emit("ERROR", "PACK", folder / "scripts" / "_engine", 0, "scripts/_engine is made at package time; remove it from the source skill")]
    problem = "is a symlink or junction; not read" if fs.is_link(deps) else fs.input_file_problem(deps)
    if problem:
        return [], [fs.emit("ERROR", "PACK", deps, 0, "ENGINE_DEPS %s; nothing is packaged" % problem)]
    try:
        with fs.open_nofollow_read(deps, os.lstat(deps)) as handle:
            text = handle.read(65536).decode("utf-8")
    except (fs.UnsafeOpen, OSError, UnicodeError) as exc:
        return [], [fs.emit("ERROR", "PACK", deps, 0, "ENGINE_DEPS cannot be read: %s" % exc)]
    names = []
    for number, line in enumerate(text.splitlines(), 1):
        name = line.strip()
        if name and not name.startswith("#") and name not in names:
            names.append(name)
    findings, extras = [], []
    for name in names + ([] if "studio.py" in names else ["studio.py"]):  # a `studio.py` line of its own must not make a second copy
        source = ENGINE_DIR / name
        if name != "studio.py" and not ENGINE_DEP_NAME.match(name):
            findings.append(fs.emit("ERROR", "PACK", deps, 0, "ENGINE_DEPS name %r is not a studio_*.py file name" % name[:80]))
        elif fs.is_link(source) or not source.is_file():
            findings.append(fs.emit("ERROR", "PACK", deps, 0, "ENGINE_DEPS names %s, which the running engine does not have" % name))
        elif fs.input_file_problem(source):  # the same rule as a skill file: a cloud placeholder or a cloud/secret zone is refused before it is opened
            findings.append(fs.emit("ERROR", "PACK", source, 0, "engine file %s; nothing is packaged" % fs.input_file_problem(source)))
        elif os.lstat(source).st_size > 25 * 1024 * 1024:
            findings.append(fs.emit("ERROR", "PACK", source, 0, "file exceeds 25 MB; review before shipping"))
        else:
            try:
                with fs.open_nofollow_read(source, os.lstat(source)) as handle:
                    raw = handle.read().decode("utf-8")
            except (fs.UnsafeOpen, OSError, UnicodeError) as exc:
                findings.append(fs.emit("ERROR", "PACK", source, 0, "engine file cannot be read: %s" % exc))
                continue
            if fs.secret_in_text(raw):
                findings.append(fs.emit("ERROR", "SEC", source, 0, "possible hardcoded secret in package"))
            extras.append((source, Path("scripts") / "_engine" / name))
    return extras, findings


def ensure_distributable(folder: Path) -> tuple[list[Path], list[dict]]:
    manifest = folder / "SKILL.md"
    # Decided before anything reads SKILL.md (validate_skill and the draft-marker test both do): a link, a cloud placeholder or a file in a
    # cloud/secret zone is refused and not opened (SPR-02 FR7.2).
    if fs.is_link(manifest):
        problem = "is a symlink or junction; not read"
    elif fs.path_is_cloud(manifest):
        problem = "is a cloud placeholder; not read"
    else:
        problem = fs.input_file_problem(manifest)
    if problem:
        return [], [fs.emit("ERROR", "PACK", manifest, 0, "SKILL.md %s; nothing is packaged" % problem)]
    findings = validate.validate_skill(folder)
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
            if fs.secret_in_text(raw):
                findings.append(fs.emit("ERROR", "SEC", p, 0, "possible hardcoded secret in package"))
        kept.append(p)
    findings.extend(engine_extras(folder)[1])
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
            for source, inside in engine_extras(folder)[0]:
                with fs.open_nofollow_read(source, os.lstat(source)) as handle:
                    zf.writestr(zipfile.ZipInfo.from_file(source, str(Path(folder.name) / inside)), handle.read(), compress_type=zipfile.ZIP_DEFLATED)
    except fs.UnsafeOpen as exc:
        fs._remove_quietly(target)
        print("ERROR: PACK: %s; nothing was packaged" % exc, file=sys.stderr)
        return 1
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    count = len(engine_extras(folder)[0])
    shared = " (+%d shared engine files)" % count if count else ""  # the line is unchanged for a skill without ENGINE_DEPS
    print("Packaged %d runtime files%s -> %s\nSHA256: %s\nExcluded: evals/, tests/ and cache folders (any letter case); a secret-named file stops the package instead. Model evaluation status is unchanged." % (len(files), shared, target, digest))
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


class MoveAsideLinkError(OSError):
    """The folder `src` holds a symlink, junction or cloud placeholder (or is too big to check) and was not copied; `src` is untouched."""


def move_aside(src: Path, dst: Path) -> None:
    """Move the folder `src` to `dst` (same device: rename). Only when the rename fails because `dst` is on another device (EXDEV, Windows error 17) is the
    folder copied first and `src` deleted after; any other rename failure (a locked file, a permission) is raised at once with `src` untouched. A failed copy
    removes the half-made `dst` and re-raises, so `src` stays whole; a failed delete after a good copy raises MoveAsideError. Before that copy `src` is listed
    without following links; a link or cloud placeholder inside it raises MoveAsideLinkError and nothing is copied."""
    try:
        os.rename(src, dst)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
            raise
    paths, links, _dirs, cloud, cut = fs.walk_files(src)  # lists links and cloud placeholders, never enters or opens them (SPR-02 FR7.3)
    if cut:
        raise MoveAsideLinkError(0, "the old Skill folder %s is over the scan limit (%d entries or %d folder levels), so it cannot be checked for links before it is copied"
                                 % (src, C.DOCTOR_MAX_FILES_PER_SKILL, C.DOCTOR_MAX_SKILL_DEPTH))
    unsafe = sorted(links | cloud)
    if unsafe:
        raise MoveAsideLinkError(0, "the old Skill folder holds a link or cloud placeholder (%s); it is not copied, so the old Skill was left in place" % unsafe[0])
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
            skill_root = scaffold.user_skill_root(args.agent)
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
    if fs.is_link(dest):  # before exists(): a dangling link is not "there" for exists() and would crash mkdir; one that cannot be probed counts as a link (lexists would say False for it)
        print("ERROR: symlink destination refused: %s" % dest, file=sys.stderr)
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
        if fs.is_link(backups_dir):
            print("ERROR: backup folder %s is a link; nothing was changed" % backups_dir, file=sys.stderr)
            return 1
        backup = backups_dir / (dest.name + "-" + stamp)
        if os.path.lexists(backup):
            print("ERROR: backup collision", file=sys.stderr)
            return 1
        made_backups_dir = not os.path.lexists(backups_dir)
        try:
            backups_dir.mkdir(exist_ok=True)
            move_aside(dest, backup)
        except MoveAsideLinkError as exc:
            if made_backups_dir:
                try:
                    backups_dir.rmdir()
                except OSError:
                    pass
            print("ERROR: %s. Nothing was changed; remove the link from the old Skill folder (or the folder itself) and run install again." % (exc.strerror or "the old Skill holds a link"), file=sys.stderr)
            return 1
        except MoveAsideError as exc:
            print("ERROR: %s. Nothing new was installed; restore from the backup if the Skill folder is incomplete." % exc.strerror, file=sys.stderr)
            return 1
        except OSError as exc:
            print("ERROR: could not back up the existing installation (%s); the old Skill was left in place" % (exc.strerror or type(exc).__name__), file=sys.stderr)
            return 1
        print("Existing installation backed up to %s" % backup)
    dest.mkdir(parents=True, exist_ok=False)  # creates skill_root itself, never the agent's config parent
    try:
        for source, destination in [(p, dest / p.relative_to(folder)) for p in files] + [(src, dest / inside) for src, inside in engine_extras(folder)[0]]:
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
