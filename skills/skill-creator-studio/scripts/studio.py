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
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

VERSION = "0.1.0"
PORTABLE_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FRONT_KEY_RE = re.compile(r"^([a-zA-Z][\w-]*):(?:\s+(.*))?$")
META_KEY_RE = re.compile(r"^\s{2,}([\w.-]+):(?:\s+(.*))?$")
SKIP_DIRS = {"__pycache__", ".git", ".venv", "evals", "tests", ".pytest_cache", ".mypy_cache"}
REJECT_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
REJECT_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def emit(level: str, code: str, path: Path, line: int, message: str) -> dict:
    return {"level": level, "code": code, "path": str(path), "line": line, "message": message}


def scalar(value: str) -> str:
    """Parse a *small, explicit subset* of YAML string scalars, not general YAML."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            if value[0] == "'":
                return value[1:-1].replace("''", "'")
            raise ValueError("malformed quoted scalar; check quote escaping")
    if ": " in value and not value.startswith("http"):
        raise ValueError("unquoted ': ' is ambiguous YAML; quote this scalar")
    if value.startswith(("[", "{", "@", "`")):
        raise ValueError("complex YAML scalar is not supported by the offline parser; quote it")
    return value


def parse_frontmatter(text: str, path: Path) -> tuple[dict, list, int]:
    lines = text.splitlines()
    findings: list[dict] = []
    if not lines or lines[0].strip() != "---":
        return {}, [emit("ERROR", "FM1", path, 1, "SKILL.md must start on line 1 with YAML '---'")], 0
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, [emit("ERROR", "FM1", path, 1, "closing frontmatter '---' not found")], 0
    parsed: dict = {}
    key = None
    mode = None  # 'block' or 'meta' or None
    block_lines: list[str] = []
    block_kind = None

    def flush():
        nonlocal key, mode, block_lines, block_kind
        if mode == "block" and key is not None:
            parsed[key] = ("\n" if block_kind == "|" else " ").join(block_lines).strip()
        mode = None
        block_lines = []
        block_kind = None

    for index in range(1, end):
        raw = lines[index]
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            flush()
            match = FRONT_KEY_RE.fullmatch(raw.rstrip())
            if not match:
                findings.append(emit("ERROR", "FM1", path, index + 1, "invalid YAML top-level key/value line"))
                key = None
                continue
            key, val = match.group(1), (match.group(2) or "").strip()
            if key in parsed:
                findings.append(emit("ERROR", "FM1", path, index + 1, "duplicate frontmatter key '%s'" % key))
            if val in (">", ">-", "|", "|-"):
                mode, block_kind = "block", val[0]
                parsed[key] = ""
            elif key == "metadata" and val == "":
                mode = "meta"
                parsed[key] = {}
            else:
                try:
                    parsed[key] = scalar(val)
                except ValueError as exc:
                    findings.append(emit("ERROR", "FM1", path, index + 1, str(exc)))
                    parsed[key] = val
        else:
            if mode == "block" and raw.startswith((" ", "\t")):
                block_lines.append(raw.strip())
            elif mode == "meta":
                match = META_KEY_RE.fullmatch(raw.rstrip())
                if not match:
                    findings.append(emit("ERROR", "FM1", path, index + 1, "metadata must be a simple indented key: string map"))
                    continue
                try:
                    parsed["metadata"][match.group(1)] = scalar((match.group(2) or "").strip())
                except ValueError as exc:
                    findings.append(emit("ERROR", "FM1", path, index + 1, str(exc)))
            else:
                findings.append(emit("ERROR", "FM1", path, index + 1, "unexpected indentation outside YAML block/metadata"))
    flush()
    return parsed, findings, end + 1


def repo_root(start: Path) -> Path | None:
    for candidate in [start.resolve()] + list(start.resolve().parents):
        if (candidate / "standards" / "SKILL_AUTHORING_STANDARD.md").is_file() and (candidate / "templates" / "skill-template" / "SKILL.md").is_file():
            return candidate
    return None


def skill_dirs(root: Path) -> list[Path]:
    p = root / "skills"
    if not p.is_dir():
        return []
    return sorted(x for x in p.iterdir() if x.is_dir() and (x / "SKILL.md").exists())


def valid_resolved_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def check_evals(folder: Path) -> list[dict]:
    f = folder / "cases.json"
    results: list[dict] = []
    if not f.is_file():
        return [emit("ERROR", "EV1", f, 0, "missing evals/<skill-name>/cases.json")]
    try:
        obj = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [emit("ERROR", "EV1", f, 0, "cannot read evals JSON: %s" % exc)]
    if not isinstance(obj, dict) or not isinstance(obj.get("cases"), list):
        return [emit("ERROR", "EV1", f, 0, "evals JSON requires an object with cases: []")]
    cases = obj["cases"]
    if len(cases) < 3:
        results.append(emit("ERROR", "EV2", f, 0, "at least 3 realistic test cases required; found %d" % len(cases)))
    if not any(isinstance(c, dict) and c.get("should_trigger") is False for c in cases):
        results.append(emit("ERROR", "EV3", f, 0, "add a negative prompt (should_trigger: false)"))
    if not any(isinstance(c, dict) and c.get("should_trigger") is True for c in cases):
        results.append(emit("ERROR", "EV3", f, 0, "add a positive prompt (should_trigger: true)"))
    ids = set()
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            results.append(emit("ERROR", "EV4", f, 0, "case %d must be an object" % (i + 1)))
            continue
        ident = case.get("id")
        if not isinstance(ident, str) or not ident:
            results.append(emit("ERROR", "EV4", f, 0, "case %d missing string id" % (i + 1)))
        elif ident in ids:
            results.append(emit("ERROR", "EV4", f, 0, "duplicate case id '%s'" % ident))
        ids.add(ident)
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            results.append(emit("ERROR", "EV4", f, 0, "case %d missing prompt" % (i + 1)))
        if not isinstance(case.get("should_trigger"), bool):
            results.append(emit("ERROR", "EV4", f, 0, "case %d should_trigger must be boolean" % (i + 1)))
        if not isinstance(case.get("expected_behaviors"), list) or not case["expected_behaviors"] or not all(isinstance(x, str) and x.strip() for x in case["expected_behaviors"]):
            results.append(emit("ERROR", "EV4", f, 0, "case %d requires at least one nonempty expected_behavior" % (i + 1)))
        fixtures = case.get("fixtures", [])
        if not isinstance(fixtures, list):
            results.append(emit("ERROR", "EV4", f, 0, "case %d fixtures must be a list" % (i + 1)))
        else:
            for relative in fixtures:
                if not isinstance(relative, str):
                    results.append(emit("ERROR", "EV5", f, 0, "fixture path must be string"))
                    continue
                target = folder / relative
                if not valid_resolved_under(target, folder) or not target.is_file():
                    results.append(emit("ERROR", "EV5", f, 0, "missing/outside eval fixture '%s'" % relative))
    if not (folder / "rubric.md").is_file():
        results.append(emit("WARN", "EV6", folder, 0, "rubric.md missing; expected behavior may lack independent grading"))
    return results


def validate_skill(folder: Path, eval_root: Path | None = None, require_evals: bool = False) -> list[dict]:
    folder = folder.resolve()
    manifest = folder / "SKILL.md"
    if not manifest.is_file():
        return [emit("ERROR", "FM1", manifest, 0, "SKILL.md is missing")]
    try:
        text = manifest.read_text(encoding="utf-8")
    except UnicodeError:
        return [emit("ERROR", "FM1", manifest, 0, "SKILL.md must be UTF-8 text")]
    meta, findings, body_start = parse_frontmatter(text, manifest)
    name = meta.get("name")
    desc = meta.get("description")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or len(name) > 64:
        findings.append(emit("ERROR", "FM2", manifest, 2, "name must be lowercase kebab-case, 1–64 chars and without '--'"))
    elif name != folder.name:
        findings.append(emit("ERROR", "FM2", manifest, 2, "name '%s' differs from folder '%s'" % (name, folder.name)))
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 1024 or re.search(r"<[^>]+>", desc or ""):
        findings.append(emit("ERROR", "DS1", manifest, 3, "description must be a nonempty string <=1024 chars without XML tags"))
    elif not re.search(r"(?i)\b(use when|when to use|used when|for tasks involving)\b", desc):
        findings.append(emit("WARN", "DS3", manifest, 3, "description should describe when to invoke the Skill, e.g. 'Use when ...'"))
    elif re.match(r"(?i)^\s*(i can|you can|i will|we can)\b", desc):
        findings.append(emit("WARN", "DS2", manifest, 3, "prefer third-person description e.g. 'Validates CSV...'"))
    for key in meta:
        if key not in PORTABLE_KEYS:
            findings.append(emit("ERROR", "FM4", manifest, 2, "unknown portable frontmatter key '%s'; use metadata or a target adapter" % key))
    if "metadata" in meta and (not isinstance(meta["metadata"], dict) or any(not isinstance(v, str) for v in meta["metadata"].values())):
        findings.append(emit("ERROR", "FM4", manifest, 0, "metadata must be a mapping of string keys to string values"))
    if "compatibility" in meta and len(str(meta["compatibility"])) > 500:
        findings.append(emit("ERROR", "FM4", manifest, 0, "compatibility max length is 500 chars"))
    body = "\n".join(text.splitlines()[body_start:])
    if len(body.splitlines()) >= 500:
        findings.append(emit("WARN", "ST1", manifest, body_start + 1, "Skill body should be under 500 lines (best-practice, not spec hard limit)"))
    if re.search(r"<!--\s*STUDIO-DRAFT|\[FILL:|\bTODO\b|\bFIXME\b", body, re.IGNORECASE):
        findings.append(emit("WARN", "CT9", manifest, body_start + 1, "draft marker/TODO/FIXME remains; do not ship unreviewed scaffold"))
    if re.search(r"(?i)(show|write out|transcribe|echo)\s+(your\s+)?(private\s+)?(chain.of.thought|internal reasoning|hidden reasoning)", body):
        findings.append(emit("WARN", "NM2", manifest, body_start + 1, "possible request to disclose private model reasoning"))
    refs_linked = set()
    for match in LINK_RE.finditer(body):
        link = match.group(1).strip().strip('<>')
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        link = link.split('#')[0].split('?')[0]
        if not link:
            continue
        resolved = folder / link
        line = body_start + body[:match.start()].count("\n") + 1
        if not valid_resolved_under(resolved, folder):
            findings.append(emit("ERROR", "ST6", manifest, line, "reference escapes Skill folder: '%s'" % link))
        elif not resolved.exists():
            findings.append(emit("ERROR", "ST6", manifest, line, "missing referenced resource '%s'" % link))
        else:
            try:
                refs_linked.add(resolved.resolve())
            except OSError:
                pass
    ref_dir = folder / "references"
    if ref_dir.is_dir():
        for p in ref_dir.rglob("*.md"):
            if p.is_symlink():
                findings.append(emit("ERROR", "SEC", p, 0, "symlink in reference tree may escape package; replace with real file"))
                continue
            if p.resolve() not in refs_linked:
                findings.append(emit("WARN", "ST4", p, 0, "reference Markdown is not directly linked from SKILL.md"))
            try:
                ref_lines = p.read_text(encoding="utf-8").splitlines()
            except UnicodeError:
                findings.append(emit("ERROR", "ST6", p, 0, "reference must be UTF-8"))
                continue
            if len(ref_lines) > 100 and not re.search(r"(?im)^#{1,3}\s+(contents|table of contents|mục lục)\b", "\n".join(ref_lines[:25])):
                findings.append(emit("WARN", "ST5", p, 1, "reference >100 lines should start with Contents / Mục lục"))
    scripts = folder / "scripts"
    if scripts.is_dir():
        for script in scripts.iterdir():
            if script.is_file() and script.suffix in {".py", ".sh", ".js", ".ts"} and script.name not in body:
                findings.append(emit("WARN", "SC3", script, 0, "script not mentioned in SKILL.md; document whether to run or read"))
    for p in folder.rglob('*'):
        if p.is_symlink():
            findings.append(emit("ERROR", "SEC", p, 0, "symlinks are not portable/safe in distributed skill packages"))
    if eval_root is None:
        root = repo_root(folder)
        if root is not None:
            eval_root = root / "evals"
    if require_evals:
        if eval_root is None:
            findings.append(emit("ERROR", "EV1", folder, 0, "eval root not found; supply --eval-root or use within Studio repo"))
        else:
            findings.extend(check_evals(eval_root / folder.name))
    return findings


def print_findings(folder: Path, findings: list[dict]) -> None:
    errors = sum(f["level"] == "ERROR" for f in findings)
    warnings = sum(f["level"] == "WARN" for f in findings)
    print("%s: %d errors; %d warnings" % (folder, errors, warnings))
    for item in findings:
        location = item["path"] + ((":%s" % item["line"]) if item["line"] else "")
        print("  %-5s %-4s %s — %s" % (item["level"], item["code"], location, item["message"]))


def get_template() -> Path:
    root = repo_root(Path(__file__).resolve())
    if root is not None:
        return root / "templates" / "skill-template"
    return Path(__file__).resolve().parents[1] / "assets" / "skill-template"


def cmd_new(args) -> int:
    name = args.name
    if not NAME_RE.fullmatch(name) or len(name) > 64:
        print("ERROR: name must be lowercase kebab-case <=64 chars", file=sys.stderr)
        return 2
    if not args.description or len(args.description) > 1024 or "\n" in args.description:
        print("ERROR: --description is required, single line and <=1024 characters", file=sys.stderr)
        return 2
    root = repo_root(Path(__file__))
    output = Path(args.output).expanduser() if args.output else (root / "skills" if root else Path.cwd() / "skills")
    target = (output / name).resolve()
    if target.exists():
        print("ERROR: refusing to overwrite existing %s" % target, file=sys.stderr)
        return 1
    template = get_template()
    if not (template / "SKILL.md").is_file():
        print("ERROR: bundled template missing at %s" % template, file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, target)
    p = target / "SKILL.md"
    content = p.read_text(encoding="utf-8")
    content = content.replace("name: skill-template", "name: " + name, 1)
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
    (ef / "cases.json").write_text(json.dumps({"skill_name": name, "status": "draft", "cases": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ef / "rubric.md").write_text("# %s — evaluation rubric (draft)\n\nDefine actual success criteria, trigger expectations, and failure cases before release.\n" % name, encoding="utf-8")
    (ef / "baselines" / "BASELINE.md").write_text("# Baseline: NOT RUN\n\nRecord fresh-session model/runtime, prompt, outputs, score and evidence after real execution.\n", encoding="utf-8")
    print("Created draft Skill: %s\nExternal evals: %s\nNext: replace STUDIO-DRAFT, write real references and >=3 eval cases, then validate." % (target, ef))
    return 0


def find_skills(args):
    root = repo_root(Path(__file__)) or repo_root(Path.cwd())
    if args.all:
        if root is None:
            raise ValueError("--all requires Studio repository; use an explicit Skill path")
        return skill_dirs(root)
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
    root = repo_root(Path(__file__))
    external = Path(args.eval_root) if args.eval_root else (root / "evals" if root else None)
    for folder in folders:
        findings = validate_skill(folder, eval_root=external, require_evals=args.require_evals)
        reports.append({"skill": str(folder), "findings": findings})
    if args.json:
        print(json.dumps({"audit": audit, "reports": reports}, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print_findings(Path(report["skill"]), report["findings"])
        if audit:
            print("\nAUDIT IS READ-ONLY. Semantic review is required for SK-03/04/06/07/08/10/12; model tests were not run.")
    return 1 if any(f["level"] == "ERROR" for x in reports for f in x["findings"]) else 0


def cmd_evals(args) -> int:
    root = repo_root(Path(__file__)) or repo_root(Path.cwd())
    eval_root = Path(args.eval_root) if args.eval_root else (root / "evals" if root else None)
    if eval_root is None:
        print("ERROR: provide --eval-root for non-Studio repository", file=sys.stderr)
        return 2
    if args.all:
        paths = sorted(p for p in eval_root.iterdir() if p.is_dir()) if eval_root.is_dir() else []
    elif args.skill:
        paths = [eval_root / Path(args.skill).name]
    else:
        print("ERROR: specify --all or skill name", file=sys.stderr)
        return 2
    reports = []
    for path in paths:
        findings = check_evals(path)
        reports.append({"skill": path.name, "findings": findings})
    if args.json:
        print(json.dumps({"reports": reports, "model_runs_performed": 0}, ensure_ascii=False, indent=2))
    else:
        for item in reports:
            print_findings(eval_root / item["skill"], item["findings"])
        print("Schema-only evaluation: NO model sessions were executed.")
    return 1 if any(f["level"] == "ERROR" for x in reports for f in x["findings"]) else 0


def ensure_distributable(folder: Path) -> tuple[list[Path], list[dict]]:
    findings = validate_skill(folder)
    manifest = folder / "SKILL.md"
    if manifest.is_file() and re.search(r"<!--\s*STUDIO-DRAFT", manifest.read_text(encoding="utf-8")):
        findings.append(emit("ERROR", "PACK", manifest, 0, "cannot package an unfinished template: remove draft marker after authoring"))
    files = []
    for p in folder.rglob("*"):
        rel = p.relative_to(folder)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_symlink():
            findings.append(emit("ERROR", "SEC", p, 0, "cannot package symlink"))
            continue
        if not p.is_file():
            continue
        if p.name in REJECT_NAMES or p.name.startswith(".env.") or p.suffix.lower() in REJECT_SUFFIXES:
            findings.append(emit("ERROR", "SEC", p, 0, "secret/credential-like file must not be shipped"))
            continue
        if p.stat().st_size > 25 * 1024 * 1024:
            findings.append(emit("ERROR", "PACK", p, 0, "file exceeds 25 MB; review before shipping"))
            continue
        if p.suffix.lower() in {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".sh"}:
            try:
                raw = p.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                raw = ""
            if ("-----BEGIN " + "PRIVATE KEY-----") in raw or re.search(r"\b(?:sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})\b", raw):
                findings.append(emit("ERROR", "SEC", p, 0, "possible hardcoded secret in package"))
        files.append(p)
    return files, findings


def cmd_package(args) -> int:
    folder = Path(args.skill).expanduser().resolve()
    if not folder.is_dir():
        print("ERROR: skill folder not found: %s" % folder, file=sys.stderr)
        return 2
    files, findings = ensure_distributable(folder)
    if any(f["level"] == "ERROR" for f in findings):
        print_findings(folder, findings)
        print("Package blocked; correct errors before trying again.", file=sys.stderr)
        return 1
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / (folder.name + ".zip")
    if target.exists() and not args.force:
        print("ERROR: package exists: %s; choose another --out or explicitly --force" % target, file=sys.stderr)
        return 1
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, arcname=str(Path(folder.name) / p.relative_to(folder)))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print("Packaged %d runtime files -> %s\nSHA256: %s\nExcluded: evals/, tests/, secrets, caches. Model evaluation status is unchanged." % (len(files), target, digest))
    return 0


def cmd_install(args) -> int:
    folder = Path(args.skill).expanduser().resolve()
    if not folder.is_dir():
        print("ERROR: skill folder not found", file=sys.stderr)
        return 2
    files, findings = ensure_distributable(folder)
    if any(f["level"] == "ERROR" for f in findings):
        print_findings(folder, findings)
        return 1
    rel = Path(".claude") / "skills" if args.agent == "claude" else Path(".agents") / "skills"
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        print("ERROR: workspace directory not found: %s" % workspace, file=sys.stderr)
        return 2
    dest = workspace / rel / folder.name
    if dest.resolve() == folder or valid_resolved_under(dest, folder):
        print("ERROR: destination is the source Skill or nested under it; refusing self-overwrite", file=sys.stderr)
        return 1
    if dest.exists() and not args.force:
        print("ERROR: %s exists; no changes made. Use --force only if you intend replacement." % dest, file=sys.stderr)
        return 1
    if dest.exists() and args.force:
        # Refuse symlink targets and back up rather than silently erasing.
        if dest.is_symlink():
            print("ERROR: symlink destination refused", file=sys.stderr)
            return 1
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = dest.with_name(dest.name + ".backup-" + stamp)
        if backup.exists():
            print("ERROR: backup collision", file=sys.stderr)
            return 1
        dest.rename(backup)
        print("Existing installation backed up to %s" % backup)
    dest.mkdir(parents=True, exist_ok=False)
    for source in files:
        destination = dest / source.relative_to(folder)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    print("Installed %s for %s at %s. This copies files; it does not run the agent or its scripts." % (folder.name, args.agent, dest))
    return 0


def cmd_sync(args) -> int:
    root = repo_root(Path(__file__))
    if root is None:
        print("ERROR: sync-template is for Studio source repository only", file=sys.stderr)
        return 2
    src = root / "templates" / "skill-template"
    dst = root / "skills" / "skill-creator-studio" / "assets" / "skill-template"
    if args.check:
        for source in src.rglob("*"):
            if source.is_file():
                mirror = dst / source.relative_to(src)
                if not mirror.is_file() or source.read_bytes() != mirror.read_bytes():
                    print("ERROR: template mirror differs: %s" % source.relative_to(src), file=sys.stderr)
                    return 1
        print("Template distribution mirror is in sync.")
        return 0
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print("Synced canonical template to bundled skill asset.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Skill Studio: create, audit, lint, package and install portable skills")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("new", help="scaffold a new Skill and an external, empty eval suite")
    p.add_argument("name")
    p.add_argument("--description", required=True)
    p.add_argument("--output", help="parent directory (default repo skills/)")
    p.add_argument("--eval-root", help="external evals directory (default repo evals/)")
    p.set_defaults(func=cmd_new)
    for action in ("validate", "audit"):
        p = sub.add_parser(action, help="static %s, never edits files" % action)
        p.add_argument("skill", nargs="?", help="Skill folder")
        p.add_argument("--all", action="store_true", help="all canonical repo skills")
        p.add_argument("--require-evals", action="store_true", help="require matching external eval manifest")
        p.add_argument("--eval-root", help="where external evals are stored")
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=lambda args, audit=(action == "audit"): cmd_check(args, audit))
    p = sub.add_parser("evals", help="validate eval manifest schemas only; no model calls")
    p.add_argument("skill", nargs="?", help="Skill name")
    p.add_argument("--all", action="store_true")
    p.add_argument("--eval-root")
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
    p.add_argument("--workspace", default=".")
    p.add_argument("--force", action="store_true", help="back up and replace existing install")
    p.set_defaults(func=cmd_install)
    p = sub.add_parser("sync-template", help="sync source template to packaged Skill asset")
    p.add_argument("--check", action="store_true", help="verify byte-identical mirror without modifications")
    p.set_defaults(func=cmd_sync)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
