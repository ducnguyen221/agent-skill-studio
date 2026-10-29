"""The `new` command: create a skill folder from the templates in `assets/` (SPR-02 TK4c).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import sys
from pathlib import Path

import studio_const as C
import studio_fs as fs


def get_template(full: bool = False, lang: str = "en") -> Path:
    """Minimal template: the SKILL.md / SKILL.vi.md file. Full template: the skill-template-full directory (its SKILL.vi.md is chosen by cmd_new)."""
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


def is_drive_root(path: Path) -> bool:
    """True for a drive root, also when a `..` leads there: the test runs on the normalised path, the caller keeps the raw one for the link probe."""
    path = Path(os.path.normpath(path))
    return path.parent == path


def write_new(path: Path, text: str, created: list | None = None, anchor: Path | None = None) -> bool:
    """Write `text` to a file that is not there yet; a file or link that is there is kept and named on stdout (FR12.1). False (after an ERROR line) when it cannot be written.
    A file this call makes is appended to `created` (when given), so the caller can take back what its own run made (FR12.4).
    With `anchor` the folders from the anchor down to the file are pinned while it is made, so a folder swapped for a link since the checks is not written through."""
    try:
        handle = fs.create_exclusive(path, anchor=anchor)
    except FileExistsError:
        print("kept existing %s" % path)
        return True
    except OSError as exc:  # UnsafeOpen (a link raced in), PermissionError, a full disk: say which file, never a traceback
        print("ERROR: cannot write %s: %s" % (path, exc), file=sys.stderr)
        return False
    if created is not None:
        created.append(path)
    with handle:
        handle.write(text.encode("utf-8"))
    return True


SYSTEM_LINKS = ("/tmp", "/var", "/etc")  # macOS: each is a link to /private/<same name>; they lie on the way to every temporary folder there
_WINDOWS_BAD_CHARS = frozenset('<>"|?*')


def _system_link_ok(path) -> bool:
    """True only for one of the fixed macOS system links (`/tmp`, `/var`, `/etc`) that points at `/private/<the same name>` (FR13.2).
    A link the user made (`/tmp/ln`) or one of these three pointed somewhere else is not: the answer is by exact spelling and target."""
    text = Path(path).as_posix()
    if text not in SYSTEM_LINKS:
        return False
    try:
        target = os.readlink(text)
    except (OSError, ValueError):
        return False
    return posixpath.normpath(posixpath.join(posixpath.dirname(text), target)) == "/private" + text


def link_in_chain(path, stop):
    """`fs.link_in_chain`, except that a macOS system link (`_system_link_ok`) on the way is not counted."""
    current, stop = Path(path), Path(stop)
    while True:
        if fs.is_link(current) and not _system_link_ok(current):
            return current
        if current == stop or current.parent == current:
            return None
        current = current.parent


def output_problem(text: str, windows: bool | None = None) -> str | None:
    """Why a path given as `--output` / `--eval-root` cannot be a path here, else None (FR12.2). Decided on the spelling alone, so nothing is touched.
    `windows` defaults to this system; tests give it to try both."""
    windows = (os.name == "nt") if windows is None else windows
    if "\0" in text:
        return "contains a NUL character"
    if not windows:
        if re.match(r"[A-Za-z]:[\\/]", text) or text.startswith("\\\\"):
            return "is a Windows path (drive letter or UNC), not valid on this system"
        return None
    rest = text[4:] if text.startswith(("\\\\?\\", "\\\\.\\")) else text
    rest = rest[2:] if re.match(r"[A-Za-z]:", rest) else rest  # the drive colon is the one colon allowed
    if any(c in _WINDOWS_BAD_CHARS or ord(c) < 32 for c in rest):
        return "contains a character Windows does not allow in a name"
    if any(part[-1] in ". " for part in re.split(r"[\\/]+", rest) if part not in ("", ".", "..")):
        return "has a name that ends in a dot or a space"
    return None


def zone_problem(path: Path) -> str | None:
    """Why `path`, or a folder above it, is a cloud or secret zone, else None: the spelling first (no stat), then one lstat per level for the placeholder bits (FR12.1)."""
    reason = fs.zone_reason(path)
    if reason:
        return "is inside a %s zone" % reason
    current = Path(path)
    while True:
        if fs.path_is_cloud(current):
            return "lies in a cloud placeholder (%s)" % current
        if current.parent == current:
            return None
        current = current.parent


def _input_error(message: str) -> int:
    print("ERROR INPUT: %s; nothing was written" % message, file=sys.stderr)
    return 1


def _make_dirs(path: Path, made: list) -> None:
    """`mkdir -p`, remembering (in `made`, outermost first) each level this call creates, so a failed run can take back its own folders."""
    missing, current = [], path
    while not os.path.lexists(current) and current.parent != current:
        missing.append(current)
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    made.extend(reversed(missing))


def _undo(target: Path, files: list, folders: list) -> None:
    """Take back what this run made (FR12.4): its files, the new skill folder, then the folders it created that are empty again. Nothing else is touched."""
    for path in reversed(files):
        try:
            os.unlink(path)
        except OSError:
            pass
    if os.path.isdir(target) and not fs.is_link(target):  # made by this run: `target` did not exist when it began
        shutil.rmtree(target, ignore_errors=True)
    for path in reversed(folders):
        try:
            os.rmdir(path)
        except OSError:  # not empty (something of the user's is in it) or already gone
            pass


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
    for flag, given in (("--output", args.output), ("--eval-root", args.eval_root)):
        problem = output_problem(os.fspath(given)) if given else None
        if problem:
            return _input_error("%s %s" % (flag, problem))
    root = fs.repo_root(Path(__file__))
    norm = None
    try:
        if args.output:
            output = Path(args.output).expanduser().absolute()  # not resolved: a link on the way must stay visible to the checks below (FR12.2)
            if is_drive_root(output):
                print("ERROR: --output must not be a drive root: %s" % output, file=sys.stderr)
                return 2
            norm = Path(os.path.normpath(output))  # `x/skills/sub/..` is `x/skills`: the name rule and the folders written use this spelling (FR12.3)
            zone = zone_problem(norm)
            if zone:
                return _input_error("--output %s %s" % (norm, zone))
        else:
            output = root / "skills" if root else Path.cwd() / "skills"
        if args.eval_root:
            external_eval = Path(args.eval_root).expanduser()
            ev_raw = external_eval.absolute()  # not abspath: a `..` behind a link must stay visible  # the same steps as --output: spelling, placeholder bits per level, links on the raw and the normalised chain
            ev_norm = Path(os.path.normpath(ev_raw))
            zone = zone_problem(ev_raw) or zone_problem(ev_norm)
            if zone:
                return _input_error("--eval-root %s %s" % (external_eval, zone))
            ev_link = link_in_chain(ev_raw, ev_raw.anchor) or link_in_chain(ev_norm, ev_norm.anchor)
            if ev_link:
                return _input_error("--eval-root: %s is a symlink or junction (or cannot be probed)" % ev_link)
        elif args.output:
            external_eval = norm.parent / "evals" if norm.name == "skills" else norm / "evals"
            if is_drive_root(external_eval.parent):
                print("ERROR: the evals would be written directly under a drive root (%s); give --eval-root or an --output below it" % external_eval, file=sys.stderr)
                return 2
        else:
            external_eval = (root / "evals") if root else (Path.cwd() / "evals")
    except (ValueError, OSError, RuntimeError) as exc:  # an odd spelling that got past the text test (no home for `~user`, a name the system rejects)
        return _input_error("the path cannot be used (%s)" % exc)
    ef = external_eval / name
    linked = (link_in_chain(output, output.anchor) or link_in_chain(norm, norm.anchor)) if args.output else None
    if args.output and not args.eval_root:  # the eval folder was derived from --output: every part of its path is checked
        linked = linked or link_in_chain(ef, ef.anchor)
    linked = linked or next((p for p in (ef, ef / "baselines", ef / "fixtures") if fs.is_link(p)), None)  # the folders written below, a given --eval-root included
    if linked:
        print("ERROR: %s is a symlink or junction (or cannot be probed); nothing was written. Name a path without links" % linked, file=sys.stderr)
        return 2
    target = norm / name if args.output else (output / name).resolve()
    if os.path.lexists(target):
        print("ERROR: refusing to overwrite existing %s" % target, file=sys.stderr)
        return 1
    template = get_template(args.full, args.lang)
    wanted = (template / ("SKILL.vi.md" if args.lang == "vi" else "SKILL.md")) if args.full else template
    if not wanted.is_file():
        print("ERROR: bundled template missing at %s" % wanted, file=sys.stderr)
        return 2
    files, folders = [], []  # what this run makes; a failure takes exactly these back (FR12.4)
    try:
        _make_dirs(target.parent, folders)
        if args.full:
            shutil.copytree(template, target, ignore=shutil.ignore_patterns("SKILL.vi.md", "SKILL.md"))  # SKILL.md is written below from the chosen language, never copied over a link
        else:
            target.mkdir()
        p = target / "SKILL.md"
        content = wanted.read_text(encoding="utf-8")
        content = re.sub(r"^name: skill-template(-full)?$", lambda _m: "name: " + name, content, count=1, flags=re.MULTILINE)
        escaped = json.dumps(args.description, ensure_ascii=False)
        content = re.sub(r'^description: .*$', "description: " + escaped, content, count=1, flags=re.MULTILINE)
        content = content.replace("# Skill Template", "# " + name.replace("-", " ").title(), 1)
        skill_ok = write_new(p, content, files, anchor=target.parent)  # the folders from the output folder down are pinned: a folder swapped for a link since the checks is not written through
        # Evals are outside runtime; do not invent test prompts or scores.
        _make_dirs(ef, folders)
        _make_dirs(ef / "fixtures", folders)
        _make_dirs(ef / "baselines", folders)
        sample = [
            {"id": "%s-typical" % name, "kind": "typical", "should_trigger": True},
            {"id": "%s-edge" % name, "kind": "edge", "should_trigger": True},
            {"id": "%s-negative" % name, "kind": "near-miss", "should_trigger": False},
        ]
        cases = [{**c, "prompt": "STUDIO-DRAFT: replace with a realistic %s prompt" % c["kind"],
                  "expected_behaviors": ["STUDIO-DRAFT: replace with observable behavior"], "fixtures": []} for c in sample]
        written = [
            skill_ok,
            write_new(ef / "cases.json", json.dumps({"skill_name": name, "status": "draft", "cases": cases}, ensure_ascii=False, indent=2) + "\n", files, anchor=ef.parent),
            write_new(ef / "rubric.md", "# %s — evaluation rubric (draft)\n\nDefine actual success criteria, trigger expectations, and failure cases before release.\n" % name, files, anchor=ef.parent),
            write_new(ef / "baselines" / "BASELINE.md", "# Baseline: NOT RUN\n\nRecord fresh-session model/runtime, prompt, outputs, score and evidence after real execution.\n", files, anchor=ef.parent),
        ]
    except OSError as exc:  # shutil.Error is one too: say it, then take back what was made
        print("ERROR: cannot create %s: %s" % (getattr(exc, "filename", None) or target, exc), file=sys.stderr)
        written = [False]
    if not all(written):
        _undo(target, files, folders)
        return 2
    print("Created draft Skill: %s\nExternal evals: %s\nNext: replace STUDIO-DRAFT in the 3 sample eval cases, write real references, then validate." % (target, ef))
    return 0
