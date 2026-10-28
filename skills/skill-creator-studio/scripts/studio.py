#!/usr/bin/env python3
"""Agent Skill Studio: portable skill factory and static auditor.

Python 3.9+, standard library only. Supports a documented YAML frontmatter
subset (single-line string scalars, folded block strings, metadata string map).
This is a static validator, not a Claude/Codex/Antigravity evaluation runner.

Use `python3 studio.py --help` and per-subcommand --help.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Sibling modules (SPR-02 TK4) resolve from this folder only, whatever the cwd or how the engine was started.
_HERE = str(Path(__file__).resolve().parent)
if not sys.path or sys.path[0] != _HERE:
    sys.path.insert(0, _HERE)

import studio_const as C  # noqa: E402
import studio_dist as dist  # noqa: E402
import studio_doctor as doctor  # noqa: E402
import studio_evals as evals  # noqa: E402
import studio_fmt as fmt  # noqa: E402
import studio_fs as fs  # noqa: E402
import studio_scaffold as scaffold  # noqa: E402
import studio_validate as validate  # noqa: E402

# One engine, one folder: a sibling module already loaded from another folder (a stale or copied engine in this process) would
# mix two code bases, so refuse to run (FR4.5).
for _mod in [m for name, m in sorted(sys.modules.items()) if name.startswith("studio_") and getattr(m, "__file__", None)]:
    if Path(_mod.__file__).resolve().parent != Path(__file__).resolve().parent:
        sys.stderr.write("ERROR: engine module %s loaded from %s, expected %s\n"
                         % (_mod.__name__, Path(_mod.__file__).resolve().parent, Path(__file__).resolve().parent))
        sys.exit(2)


def find_skills(args):
    root = fs.repo_root(Path(__file__)) or fs.repo_root(Path.cwd())
    if args.all:
        if root is None:
            raise ValueError("--all requires Studio repository; use an explicit Skill path")
        skipped: list = []
        found = fs.skill_dirs(root, skipped)
        for item in skipped:  # a skill that was not looked at is said, never left out silently (FR13.1); the exit code is not changed by it
            print("WARN: --all skipped %s (%s); it is not checked" % (item["path"], item["reason"]), file=sys.stderr)
        return found
    if not args.skill:
        raise ValueError("provide a skill path or --all")
    if getattr(args, "typed", False):
        return [validate.resolve_check_path(args.skill)]
    return [Path(args.skill).expanduser()]


def cmd_check(args, audit: bool = False, typed: bool = False) -> int:
    """validate / audit / check. `typed` (check) adds "type": "skill" to each report; a non-skill document is refused by find_skills."""
    args.typed = typed
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
        report = {"skill": str(folder), "findings": findings}
        if typed:
            report = {"skill": report["skill"], "type": "skill", "findings": findings}
        reports.append(report)
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
    gate_root, gate_dir = (evals.gate_root() if args.all else None), None  # the gate follows the engine's repository, never the cwd; outside a repository, or in one without evals/, it is skipped (FR6.2)
    if args.all and evals.installed_engine():  # said once per run, on stderr: a skipped gate is never mistaken for a passed one (FR13.3)
        print("note: model_evaluated gate skipped: installed engine (%s); run `evals --all` from the Studio repository to check it" % Path(__file__).resolve().parent, file=sys.stderr)
    if gate_root is not None:
        catalog = gate_root / evals.CATALOG_REL
        problems = evals.catalog_problems(gate_root)
        if problems:
            reports.append({"skill": evals.CATALOG_REL, "findings": [fs.emit("ERROR", "EV20", catalog, 0, p) for p in problems]})
            gate_dir = catalog
    if args.json:
        print(json.dumps({"reports": reports, "model_runs_performed": 0}, ensure_ascii=False, indent=2))
    else:
        for item in reports:
            validate.print_findings(gate_dir if gate_dir is not None and item is reports[-1] else eval_root / item["skill"], item["findings"])
        print("Schema-only evaluation: NO model sessions were executed.")
    return 1 if any(f["level"] == "ERROR" for x in reports for f in x["findings"]) else 0


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
    p.add_argument("--full", action="store_true", help="scaffold the full template (references/, scripts/, assets/, agents/); the body follows --lang")
    p.set_defaults(func=scaffold.cmd_new)
    for action in ("check", "validate", "audit"):
        if action == "check":
            help_text = "static check of a document, never edits files (a skill folder or SKILL.md; validate and audit stay as aliases)"
        else:
            help_text = "static %s, never edits files" % action
        p = sub.add_parser(action, help=help_text)
        p.add_argument("skill", nargs="?", help="Skill folder or SKILL.md" if action == "check" else "Skill folder")
        p.add_argument("--all", action="store_true", help="all canonical repo skills")
        p.add_argument("--require-evals", action="store_true", help="require matching external eval manifest")
        p.add_argument("--eval-root", help="where external evals are stored")
        p.add_argument("--target", choices=C.TARGETS, default="portable", help="portable (default) or claude-code (also accepts Claude Code only keys as FM6 warnings)")
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=lambda args, audit=(action == "audit"), typed=(action == "check"): cmd_check(args, audit, typed))
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
    p.set_defaults(func=dist.cmd_package)
    p = sub.add_parser("install", help="copy a Skill into a project's runtime discovery folder")
    p.add_argument("skill")
    p.add_argument("--agent", choices=("claude", "codex", "antigravity"), required=True)
    where = p.add_mutually_exclusive_group()
    where.add_argument("--workspace", help="project directory (default .)")
    where.add_argument("--user", action="store_true", help="install into the per-user skill folder (antigravity, codex; not claude); the agent's config folder must already exist")
    p.add_argument("--force", action="store_true", help="back up (to <skill root parent>/.skill-studio-backups/) and replace existing install")
    p.add_argument("--allow-root-link", action="store_true", help="install even when the skill folder (or a parent below HOME/the workspace) is a symlink or junction; the real target is printed")
    p.set_defaults(func=dist.cmd_install)
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
    p.set_defaults(func=doctor.cmd_doctor)
    p = sub.add_parser("fmt", help="check (default) or fix the house style of Markdown files: line endings, key order, quoted metadata (never edits the words of the body)")
    p.add_argument("paths", nargs="*", help="files or folders (*.md); --fix only touches what is named")
    p.add_argument("--all", action="store_true", help="every *.md of the repo, report only (not with --fix)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="list findings, write nothing (default)")
    mode.add_argument("--fix", action="store_true", help="apply the fixable findings; every changed file is first copied to <file>.bak-<ISO> (see --no-backup)")
    p.add_argument("--no-backup", action="store_true", help="skip the <file>.bak-<ISO> copy; use when git or another backup already holds the files")
    p.add_argument("--profile", choices=C.PROFILES, default="portable")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=fmt.cmd_fmt)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
