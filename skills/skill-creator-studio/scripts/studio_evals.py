"""Static checks of an evals folder (`cases.json`) and the export of its cases to the agentskills layout (SPR-02 TK4b).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import unicodedata
from pathlib import Path

import studio_const as C
import studio_fs as fs


def check_evals(folder: Path) -> list[dict]:
    f = folder / "cases.json"
    results: list[dict] = []
    if not f.is_file():
        return [fs.emit("ERROR", "EV1", f, 0, "missing evals/<skill-name>/cases.json")]
    try:
        obj = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [fs.emit("ERROR", "EV1", f, 0, "cannot read evals JSON: %s" % exc)]
    if not isinstance(obj, dict) or not isinstance(obj.get("cases"), list):
        return [fs.emit("ERROR", "EV1", f, 0, "evals JSON requires an object with cases: []")]
    cases = obj["cases"]
    if len(cases) < 3:
        results.append(fs.emit("ERROR", "EV2", f, 0, "at least 3 realistic test cases required; found %d" % len(cases)))
    if not any(isinstance(c, dict) and c.get("should_trigger") is False for c in cases):
        results.append(fs.emit("ERROR", "EV3", f, 0, "add a negative prompt (should_trigger: false)"))
    if not any(isinstance(c, dict) and c.get("should_trigger") is True for c in cases):
        results.append(fs.emit("ERROR", "EV3", f, 0, "add a positive prompt (should_trigger: true)"))
    ids = set()
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            results.append(fs.emit("ERROR", "EV4", f, 0, "case %d must be an object" % (i + 1)))
            continue
        ident = case.get("id")
        if not isinstance(ident, str) or not ident:
            results.append(fs.emit("ERROR", "EV4", f, 0, "case %d missing string id" % (i + 1)))
        elif ident in ids:
            results.append(fs.emit("ERROR", "EV4", f, 0, "duplicate case id '%s'" % ident))
        ids.add(ident)
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            results.append(fs.emit("ERROR", "EV4", f, 0, "case %d missing prompt" % (i + 1)))
        if not isinstance(case.get("should_trigger"), bool):
            results.append(fs.emit("ERROR", "EV4", f, 0, "case %d should_trigger must be boolean" % (i + 1)))
        if not isinstance(case.get("expected_behaviors"), list) or not case["expected_behaviors"] or not all(isinstance(x, str) and x.strip() for x in case["expected_behaviors"]):
            results.append(fs.emit("ERROR", "EV4", f, 0, "case %d requires at least one nonempty expected_behaviors entry" % (i + 1)))
        fixtures = case.get("fixtures", [])
        if not isinstance(fixtures, list):
            results.append(fs.emit("ERROR", "EV4", f, 0, "case %d fixtures must be a list" % (i + 1)))
        else:
            for relative in fixtures:
                if not isinstance(relative, str):
                    results.append(fs.emit("ERROR", "EV5", f, 0, "fixture path must be string"))
                    continue
                target = folder / relative
                if not fs.valid_resolved_under(target, folder) or not target.is_file():
                    results.append(fs.emit("ERROR", "EV5", f, 0, "missing/outside eval fixture '%s'" % relative))
    if not (folder / "rubric.md").is_file():
        results.append(fs.emit("WARN", "EV6", folder, 0, "rubric.md missing; expected behavior may lack independent grading"))
    return results


def export_skills_dirs(eval_dir: Path) -> list[Path]:
    """Every `skills/` directory an export must never write into: this repo's, the cwd repo's, the one this script is packaged under, and the sibling of the evals root."""
    here = Path(__file__).resolve()
    found = [root / "skills" for root in (fs.repo_root(here), fs.repo_root(Path.cwd())) if root]
    found += [parent for parent in here.parents if parent.name == "skills"]
    if here.parent.name == "scripts" and (here.parent.parent / "SKILL.md").is_file():
        found.append(here.parent.parent)  # a packaged skill copied somewhere that is not called skills/
    found.append(eval_dir.resolve().parent.parent / "skills")
    return found


def export_eval_dirs(eval_dir: Path) -> list[Path]:
    """Every evals root an export must never write into (frozen test data): the root holding this eval, and the evals/ of this repo and of the cwd repo."""
    here = Path(__file__).resolve()
    return [eval_dir.resolve().parent] + [root / "evals" for root in (fs.repo_root(here), fs.repo_root(Path.cwd())) if root]


def export_fixture_check(eval_dir: Path, relative: str) -> tuple[str, str]:
    """(EX code, why) a fixture path from cases.json must not be exported, or ("", "") when it may be. Reads names and link/cloud metadata (lstat) only: it never opens,
    stats-through or follows the fixture itself, so a secret, a cloud placeholder or a link target is not touched before the answer (RK15)."""
    posix = relative.replace("\\", "/")
    parts = [x for x in posix.split("/")]
    if not posix or posix.startswith("/") or ":" in posix or any(x in ("", ".", "..") for x in parts):  # ':' also covers drive letters and NTFS streams (a.csv:hid)
        return "EX4", "unsafe fixture path '%s' (must be a plain relative path inside the eval folder, without ':')" % relative
    for part in parts:
        bad_name = fs.unsafe_windows_name(part)
        if bad_name:
            return C.WIN_NAME_CODES[bad_name.split(":", 1)[0]], "fixture '%s' has a Windows-dangerous name (%s); refusing to copy it" % (relative, bad_name.split(": ", 1)[1])
    for part in parts:
        if fs.secret_file_name(part):
            return "EX4", "fixture '%s' has a secret or credential name ('%s': .env*, *.credentials.json, auth.json, *.pem, *.key, secrets.json...); refusing to copy it" % (relative, part)
        if fs.zone_named(part):
            return "EX4", "fixture '%s' sits in a folder named like a secret or cloud-synced zone ('%s'); refusing to copy it" % (relative, part)
    if fs.zone_reason(eval_dir / relative):
        return "EX4", "fixture '%s' is inside a secret or cloud-synced folder; refusing to copy it" % relative
    current = eval_dir
    for part in parts:
        current = current / part
        if fs.is_link(current):
            return "EX4", "fixture '%s' goes through a symlink or junction; refusing to copy it" % relative
        if fs.path_is_cloud(current):
            return "EX4", "fixture '%s' is a cloud placeholder; refusing to copy it" % relative
    if fs.zone_reason(Path(os.path.realpath(current.parent)) / parts[-1]):
        return "EX4", "fixture '%s' resolves into a secret or cloud-synced folder; refusing to copy it" % relative
    try:
        info = os.lstat(current)
    except OSError:
        return "", ""  # missing: reported by the caller
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        return "EX4", "fixture '%s' is a hard link (%d names for one file); refusing to copy it" % (relative, info.st_nlink)
    return "", ""


def export_fixture_refusal(eval_dir: Path, relative: str) -> str:
    """The message of export_fixture_check, or "" when the fixture may be exported."""
    return export_fixture_check(eval_dir, relative)[1]


def export_eval_check(eval_dir: Path) -> tuple[str, str]:
    """The first reason any fixture named in cases.json is refused (export_fixture_refusal), checked BEFORE check_evals stats a single fixture. An eval folder
    inside a secret or cloud-synced zone is refused without reading cases.json. Unreadable or malformed JSON gives "" so that check_evals reports it (EV1)."""
    if fs.zone_reason(eval_dir):
        return "EX4", "eval folder is inside a secret or cloud-synced folder; refusing to read or export it"
    try:
        cases = json.loads((eval_dir / "cases.json").read_text(encoding="utf-8"))["cases"]
        listed = [c["fixtures"] for c in cases if isinstance(c, dict) and isinstance(c.get("fixtures"), list)]
    except (ValueError, OSError, KeyError, TypeError):
        return "", ""
    for relative in (x for fixtures in listed for x in fixtures if isinstance(x, str)):
        found = export_fixture_check(eval_dir, relative)
        if found[1]:
            return found
    return "", ""


def export_eval_refusal(eval_dir: Path) -> str:
    """The message of export_eval_check, or "" when no fixture is refused."""
    return export_eval_check(eval_dir)[1]


def export_fixture_source(eval_dir: Path, relative: str) -> tuple[Path | None, list[str], str]:
    """Resolve a fixture path from cases.json to (source, export-name parts, problem). Only plain relative paths inside eval_dir, no links,
    no secret/credential names, nothing in a secret or cloud-synced zone (export_fixture_refusal)."""
    problem = export_fixture_check(eval_dir, relative)[1]
    if problem:
        return None, [], problem
    parts = relative.replace("\\", "/").split("/")
    current = eval_dir.joinpath(*parts)
    if not current.is_file() or not fs.valid_resolved_under(current, eval_dir):
        return None, [], "missing/outside eval fixture '%s'" % relative
    return current, (parts[1:] if parts[0] == "fixtures" and len(parts) > 1 else parts), ""


def export_agentskills(eval_dir: Path, skill_name: str, out_root: Path, force: bool = False) -> tuple[int, list[dict], dict]:
    """Write <out_root>/<skill_name>/evals/evals.json (agentskills schema, SPEC 9.6) plus evals/files/ from evals/<skill>/cases.json.

    Returns (exit code, findings, {"exported", "excluded_negative", "path"}). 2 = destination under skills/ or an evals root (EX1);
    1 = refused before any write (EV*, EX2-EX7, EX9-EX12; EX4 also covers a fixture with a secret/credential name, in a secret or cloud-synced zone, behind a link or a hard link, decided from names and lstat before any fixture is opened or stat-ed) or a write error (EX8; EX13 = a source changed between check and copy; EX6 also covers a parent swapped for a link after mkdir). On EX8 the files this run created are removed again (empty folders may remain);
    a file replaced under --force is not restored. Only the positive cases (should_trigger true) are exported; nothing else is deleted,
    and --force only overwrites the files this function generates."""
    eval_dir, out_root = Path(eval_dir), Path(out_root)
    stats = {"exported": 0, "excluded_negative": 0, "path": ""}

    def refuse(code: int, ident: str, message: str, path: Path = eval_dir):
        return code, [fs.emit("ERROR", ident, path, 0, message)], stats

    dest = out_root / skill_name
    if any(fs.valid_resolved_under(dest, skills) for skills in export_skills_dirs(eval_dir)):
        return refuse(2, "EX1", "export destination must not be under skills/ (it would ship test data inside the skill): %s" % out_root, out_root)
    if any(fs.valid_resolved_under(dest, frozen) for frozen in export_eval_dirs(eval_dir)):
        return refuse(2, "EX1", "export destination must not be under evals/ (frozen test data; the export would change the eval it came from): %s" % out_root, out_root)
    if not C.EXPORT_NAME_RE.match(skill_name or ""):
        return refuse(1, "EX2", "skill name '%s' is not a plain lowercase-hyphen name" % skill_name)
    ident, problem = export_eval_check(eval_dir)  # names, zones and links first: check_evals below stats every fixture
    if problem:
        return refuse(1, ident, problem, eval_dir / "cases.json")
    problems = [x for x in check_evals(eval_dir) if x["level"] == "ERROR"]
    if problems:
        return 1, problems, stats
    try:
        data = json.loads((eval_dir / "cases.json").read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return refuse(1, "EV1", "cannot read evals JSON: %s" % exc, eval_dir / "cases.json")
    cases = data["cases"]
    if data.get("status") == "draft" or any("STUDIO-DRAFT" in "%s %s" % (c.get("prompt", ""), " ".join(map(str, c.get("expected_behaviors", [])))) for c in cases):
        return refuse(1, "EX3", "eval is still a draft (status 'draft' or STUDIO-DRAFT text); write real cases before exporting", eval_dir / "cases.json")
    positive = [c for c in cases if c["should_trigger"]]
    sources: dict[str, tuple[str, Path]] = {}  # NFC-casefolded name -> (name as exported: NFC, case kept; source file)
    checked: dict[Path, os.stat_result] = {}  # source -> lstat taken when it was checked; the copy re-proves this identity on the open handle
    evals = []
    for number, case in enumerate(positive, 1):
        names = []
        for relative in case.get("fixtures", []):
            source, parts, problem = export_fixture_source(eval_dir, relative)
            if source is None:
                return refuse(1, "EX4", problem, eval_dir / "cases.json")
            try:
                checked.setdefault(source, os.lstat(source))
            except OSError as exc:
                return refuse(1, "EX4", "cannot inspect fixture '%s': %s" % (relative, exc), eval_dir / "cases.json")
            name = unicodedata.normalize("NFC", "/".join(parts))  # written to disk and to evals.json as NFC, case kept (Data.csv stays Data.csv)
            key = name.casefold()  # a.csv and A.csv are one file on Windows/macOS disks; the key is only for the collision check
            seen = sources.get(key)
            if seen and (seen[0] != name or seen[1] != source):
                return refuse(1, "EX7", "fixture names collide after export (compared ignoring case and Unicode form): '%s' is %s but '%s' is %s" % (seen[0], seen[1], name, source), eval_dir / "cases.json")
            sources[key] = (name, source)
            names.append("evals/files/" + name)
        evals.append({"id": number, "prompt": case["prompt"], "expected_output": "; ".join(case["expected_behaviors"]), "files": names, "assertions": list(case["expected_behaviors"])})
    for key in sources:
        for other in sources:
            if other.startswith(key + "/"):
                return refuse(1, "EX12", "fixture '%s' is a file but '%s' needs it as a folder; rename one of them" % (sources[key][0], sources[other][0]), eval_dir / "cases.json")
    evals_dir = dest / "evals"
    target = evals_dir / "evals.json"
    copies = {evals_dir / "files" / Path(*name.split("/")): source for name, source in sources.values()}
    for owned in [dest, evals_dir, evals_dir / "files"] + [t.parent for t in copies] + [target] + list(copies):
        if fs.is_link(owned):
            return refuse(1, "EX6", "export destination goes through a symlink or junction: %s" % owned, owned)
    for t, source in copies.items():
        if t.exists() and source.exists() and os.path.samefile(t, source):
            return refuse(1, "EX6", "export destination is the source fixture itself: %s" % t, t)
    clash = [x for x in [target] + list(copies) if os.path.lexists(x)]  # a dangling link is a name already taken
    if clash and not force:
        return refuse(1, "EX5", "export file exists: %s; choose another --out or explicitly --force" % clash[0], clash[0])
    fresh = [x for x in [target] + list(copies) if not os.path.lexists(x)]  # only names this run creates are cleaned up again
    temp_name = ""
    try:
        for t, source in copies.items():
            t.parent.mkdir(parents=True, exist_ok=True)
            linked = fs.link_in_chain(t.parent, dest)  # a parent swapped for a junction after the check above would redirect the write
            if linked:
                raise fs.UnsafeOpen("export destination goes through a symlink or junction: %s" % linked, "EX6")
            if t.exists():  # only reachable with --force: replace the file, never write through it
                t.unlink()
            with fs.open_nofollow_read(source, checked[source]) as reader, fs.create_exclusive(t) as writer:
                shutil.copyfileobj(reader, writer)
        evals_dir.mkdir(parents=True, exist_ok=True)
        linked = fs.link_in_chain(evals_dir, dest)
        if linked:
            raise fs.UnsafeOpen("export destination goes through a symlink or junction: %s" % linked, "EX6")
        handle, temp_name = tempfile.mkstemp(prefix=".evals-", suffix=".tmp", dir=str(evals_dir))  # same folder, so os.replace is atomic
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps({"skill_name": skill_name, "evals": evals}, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp_name, target)
        temp_name = ""
    except OSError as exc:
        for leftover in fresh + ([Path(temp_name)] if temp_name else []):  # a half-written export must not look like a finished one
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(exc, fs.UnsafeOpen):
            return refuse(1, exc.code, "%s (files created by this run were removed)" % exc, out_root)
        return refuse(1, "EX8", "cannot write export: %s (files created by this run were removed)" % exc, out_root)
    stats.update({"exported": len(evals), "excluded_negative": len(cases) - len(positive), "path": str(target)})
    return 0, [], stats
