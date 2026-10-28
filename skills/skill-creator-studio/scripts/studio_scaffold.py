"""The `new` command: create a skill folder from the templates in `assets/` (SPR-02 TK4c).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
"""

from __future__ import annotations

import json
import os
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
    return path.parent == path


def write_new(path: Path, text: str) -> bool:
    """Write `text` to a file that is not there yet; a file or link that is there is kept and named on stdout (FR12.1). False (after an ERROR line) when it cannot be written."""
    try:
        handle = fs.create_exclusive(path)
    except FileExistsError:
        print("kept existing %s" % path)
        return True
    except OSError as exc:  # UnsafeOpen (a link raced in), PermissionError, a full disk: say which file, never a traceback
        print("ERROR: cannot write %s: %s" % (path, exc), file=sys.stderr)
        return False
    with handle:
        handle.write(text.encode("utf-8"))
    return True


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
    root = fs.repo_root(Path(__file__))
    if args.output:
        output = Path(args.output).expanduser().absolute()  # not resolved: a link on the way must stay visible to the checks below (FR12.2)
        if is_drive_root(output):
            print("ERROR: --output must not be a drive root: %s" % output, file=sys.stderr)
            return 2
    else:
        output = root / "skills" if root else Path.cwd() / "skills"
    if args.eval_root:
        external_eval = Path(args.eval_root).expanduser()
    elif args.output:
        external_eval = output.parent / "evals" if output.name == "skills" else output / "evals"
        if is_drive_root(external_eval.parent):
            print("ERROR: the evals would be written directly under a drive root (%s); give --eval-root or an --output below it" % external_eval, file=sys.stderr)
            return 2
    else:
        external_eval = (root / "evals") if root else (Path.cwd() / "evals")
    ef = external_eval / name
    linked = fs.link_in_chain(output, output.anchor) if args.output else None
    if args.output and not args.eval_root:  # the eval folder was derived from --output: every part of its path is checked
        linked = linked or fs.link_in_chain(ef, ef.anchor)
    linked = linked or next((p for p in (ef, ef / "baselines", ef / "fixtures") if fs.is_link(p)), None)  # the folders written below, a given --eval-root included
    if linked:
        print("ERROR: %s is a symlink or junction (or cannot be probed); nothing was written. Name a path without links" % linked, file=sys.stderr)
        return 2
    target = output / name if args.output else (output / name).resolve()
    if os.path.lexists(target):
        print("ERROR: refusing to overwrite existing %s" % target, file=sys.stderr)
        return 1
    template = get_template(args.full, args.lang)
    wanted = (template / ("SKILL.vi.md" if args.lang == "vi" else "SKILL.md")) if args.full else template
    if not wanted.is_file():
        print("ERROR: bundled template missing at %s" % wanted, file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.full:
        shutil.copytree(template, target, ignore=shutil.ignore_patterns("SKILL.vi.md"))  # the Vietnamese body is a source for SKILL.md, never a file of the new skill
        if args.lang == "vi":
            shutil.copyfile(wanted, target / "SKILL.md")
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
    written = [
        write_new(ef / "cases.json", json.dumps({"skill_name": name, "status": "draft", "cases": cases}, ensure_ascii=False, indent=2) + "\n"),
        write_new(ef / "rubric.md", "# %s — evaluation rubric (draft)\n\nDefine actual success criteria, trigger expectations, and failure cases before release.\n" % name),
        write_new(ef / "baselines" / "BASELINE.md", "# Baseline: NOT RUN\n\nRecord fresh-session model/runtime, prompt, outputs, score and evidence after real execution.\n"),
    ]
    if not all(written):
        return 2
    print("Created draft Skill: %s\nExternal evals: %s\nNext: replace STUDIO-DRAFT in the 3 sample eval cases, write real references, then validate." % (target, ef))
    return 0
