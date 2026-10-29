"""Static checks of an evals folder (`cases.json`) and the export of its cases to the agentskills layout (SPR-02 TK4b).

Internal module of `studio.py`; do not run it. It reaches other studio modules through the module object (FR4.5).
"""

from __future__ import annotations

import json
import os
import re
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
    staged: list = []  # new files written beside their names; they replace the old ones only after every one is complete (--force keeps the old export on a failure)

    def copy_into(source: Path):
        def fill(writer):
            with fs.open_nofollow_read(source, checked[source], anchor=eval_dir) as reader:
                shutil.copyfileobj(reader, writer)
        return fill

    try:
        for t, source in copies.items():
            t.parent.mkdir(parents=True, exist_ok=True)
            linked = fs.link_in_chain(t.parent, dest)  # a parent swapped for a junction after the check above would redirect the write
            if linked:
                raise fs.UnsafeOpen("export destination goes through a symlink or junction: %s" % linked, "EX6")
            staged.append(fs.stage_write(t, copy_into(source), anchor=dest))
        evals_dir.mkdir(parents=True, exist_ok=True)
        linked = fs.link_in_chain(evals_dir, dest)
        if linked:
            raise fs.UnsafeOpen("export destination goes through a symlink or junction: %s" % linked, "EX6")
        payload = (json.dumps({"skill_name": skill_name, "evals": evals}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        staged.append(fs.stage_write(target, lambda writer: writer.write(payload), anchor=dest))
        fs.commit_all(staged)  # every new file in place or, on a failure, every old one back
        staged = []
    except OSError as exc:
        for item in staged:
            item.discard()
        for leftover in fresh:  # a half-written export must not look like a finished one
            try:
                fs.remove_pinned(leftover, anchor=dest)
            except (OSError, ValueError):
                pass
        if isinstance(exc, fs.UnsafeOpen):
            return refuse(1, exc.code, "%s (files created by this run were removed)" % exc, out_root)
        return refuse(1, "EX8", "cannot write export: %s (files created by this run were removed)" % exc, out_root)
    stats.update({"exported": len(evals), "excluded_negative": len(cases) - len(positive), "path": str(target)})
    return 0, [], stats

# --- the `model_evaluated` gate of evals/catalog.json and the compact evidence it reads (SPR-02 TK6 FR6; SPR-03 TK1 FR2, FR3) ---

CATALOG_REL = "evals/catalog.json"
EVIDENCE_KEYS = ("schema", "skill", "batch", "source", "source_sha256", "logs", "smoke", "ab")
LOG_TYPES = {"file": str, "runtime": str, "with_skill": bool, "status": str, "case_id": (str, type(None)), "kind": (str, type(None)),
             "triggered": (bool, type(None))}
LOG_REQUIRED = ("file", "runtime", "with_skill", "status")  # the other three keys of a log entry may be left out (read as null)
SMOKE_TYPES = {"file": str, "runtime": str, "with_skill": bool}
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def engine_repo_root() -> Path | None:
    """The repository this engine file sits in (never the cwd), or None for an engine copied out of any repository."""
    return fs.repo_root(Path(__file__))


def _read_text(path) -> str:
    """UTF-8 text of a plain file, opened without following a link and read up to DOCTOR_MAX_FILE_BYTES; ValueError when larger or not UTF-8."""
    with fs.open_nofollow_read(path, os.lstat(path), single_link=False, anchor=fs.anchor_for(path)) as handle:
        data = handle.read(C.DOCTOR_MAX_FILE_BYTES + 1)
    if len(data) > C.DOCTOR_MAX_FILE_BYTES:
        raise ValueError("%s is larger than %d bytes" % (path, C.DOCTOR_MAX_FILE_BYTES))
    return data.decode("utf-8")


def _load_json(path):
    return json.loads(_read_text(path))


INSTALL_DIR_NAMES = (".claude", ".agents", ".codex", ".gemini")  # the folders an installed copy of the engine lives under (SPR-03 FR13.3)


def installed_engine(engine_file=None) -> bool:
    """True when a folder above the engine file is named exactly `.claude`, `.agents`, `.codex` or `.gemini` (case-insensitive: those file systems
    are): an installed copy, whose surrounding tree is not the Studio repository. Names only; nothing is stat-ed."""
    parents = Path(os.path.abspath(__file__ if engine_file is None else engine_file)).parents
    return any(parent.name.casefold() in INSTALL_DIR_NAMES for parent in parents)


def gate_root() -> Path | None:
    """The repository the `model_evaluated` gate runs in: the engine's own repository when it has an evals/ folder (a plain one), else None
    (an engine installed under `.claude`/`.agents`/`.codex`/`.gemini`, copied out of a repository, or put in a tree without evals/, has nothing to
    count: an installed copy never reads the catalog of the tree around it, FR13.3)."""
    if installed_engine():
        return None
    root = engine_repo_root()
    if root is None or not fs._is_dir_quiet(root / "evals"):
        return None
    return root


def read_logs(runs_dir, skipped=None) -> list[tuple[str, dict]]:
    """[(file name, parsed JSON object)] of the `*.json` files directly in `runs_dir`, sorted by name. Files are read without following a link, up
    to DOCTOR_MAX_FILE_BYTES; one that cannot be read or is not a JSON object is left out (its name goes to `skipped` when a list is given)."""
    out = []
    for f in sorted(Path(runs_dir).glob("*.json")):
        try:
            log = _load_json(f)
        except (ValueError, OSError):
            log = None
        if isinstance(log, dict):
            out.append((f.name, log))
        elif skipped is not None:
            skipped.append(f.name)
    return out


def summarize_logs(logs) -> dict:
    """Per runtime, the with-skill logs that ran: {runtime: {pos, pos_trig, neg, neg_trig}}. The one counting rule of the gate and of
    evals/tools/activation.py; a raw run folder (`summarize`) and a compact evidence file (the gate) both go through it."""
    rows: dict = {}
    for log in logs:
        if not isinstance(log, dict) or "runtime" not in log or "with_skill" not in log or log.get("status") != "ran":
            continue
        if log["with_skill"] is not True:
            continue
        r = rows.setdefault(log["runtime"], {"pos": 0, "pos_trig": 0, "neg": 0, "neg_trig": 0})
        positive = log.get("kind") != "near-miss"
        r["pos" if positive else "neg"] += 1
        if log.get("triggered"):
            r["pos_trig" if positive else "neg_trig"] += 1
    return rows


def ran_logs(logs):
    """{runtime: {"with": [logs], "base": [logs]}} for every log with status ran (baseline logs included)."""
    out = {}
    for log in logs:
        if isinstance(log, dict) and "runtime" in log and "with_skill" in log and log.get("status") == "ran":
            out.setdefault(log["runtime"], {"with": [], "base": []})["with" if log["with_skill"] is True else "base"].append(log)
    return out


def summarize(runs_dir) -> dict:
    """`summarize_logs` of the run logs in a raw folder (for evals/tools/activation.py summarize)."""
    return summarize_logs([log for _name, log in read_logs(runs_dir)])


def _relative_problem(value) -> str | None:
    """Why a catalog value cannot name a folder below the repository (not a string, absolute, a drive, '..', ':' or a dangerous Windows name), else None."""
    if not isinstance(value, str) or not value.strip():
        return "is not a non-empty string"
    text = value.replace("\\", "/")
    if text.startswith("/") or Path(value).is_absolute() or os.path.isabs(value):
        return "is an absolute path"
    for part in text.split("/"):
        if part == "..":
            return "contains '..'"
        reason = fs.unsafe_windows_name(part)
        if reason:
            return "has an unsafe component (%s)" % reason
    return None


def _plain_tree(folder: Path) -> tuple[str | None, list[Path]]:
    """(why the folder cannot be read safely: a link, a cloud placeholder, or more than the walk limits, else None; the files and folders in it). Nothing is opened."""
    if fs.is_link(folder) or fs.path_is_cloud(folder):
        return "%s is a link or a cloud placeholder" % folder, []
    found, links, _dirs, cloud, cut = fs.walk_files(folder)
    if links:
        return "link %s" % sorted(links)[0], []
    if cloud:
        return "cloud placeholder %s" % sorted(cloud)[0], []
    if cut:
        return "more than %d entries or %d levels under %s" % (C.DOCTOR_MAX_FILES_PER_SKILL, C.DOCTOR_MAX_SKILL_DEPTH, folder), []
    return None, found


def _link_below(path, root) -> Path | None:
    """The first link among `path` and its parents below `root` (`root` itself being a link is not counted), else None."""
    link = fs.link_in_chain(path, root)
    return None if link is None or Path(link) == Path(root) else Path(link)


def _log_entry_problem(entry, types, required, where) -> str | None:
    if not isinstance(entry, dict):
        return "%s entry is not an object" % where
    if set(entry) - set(types):
        return "%s entry has unknown key(s) %s" % (where, sorted(set(entry) - set(types)))
    if [k for k in required if k not in entry]:
        return "%s entry lacks key(s) %s" % (where, [k for k in required if k not in entry])
    for key, kind in types.items():
        if key in entry and not isinstance(entry[key], kind):
            return "%s entry %r: %s has the wrong type (%s)" % (where, entry.get("file"), key, type(entry[key]).__name__)
    return None


def _batch_problem(data, skill: str, batch: str) -> str | None:
    """Why a parsed compact evidence file is not acceptable for `skill` / `batch` (schema 1), else None."""
    if not isinstance(data, dict):
        return "is not a JSON object"
    if set(data) - set(EVIDENCE_KEYS):
        return "has unknown key(s) %s" % sorted(set(data) - set(EVIDENCE_KEYS))
    if [k for k in EVIDENCE_KEYS if k not in data]:
        return "lacks key(s) %s" % [k for k in EVIDENCE_KEYS if k not in data]
    if type(data["schema"]) is not int or data["schema"] != 1:
        return "schema %r is not 1" % (data["schema"],)
    if data["skill"] != skill:
        return "skill %r is not %r" % (data["skill"], skill)
    if data["batch"] != batch:
        return "batch %r is not %r" % (data["batch"], batch)
    if data["source"] != "ledger/agent-skill-studio/evidence/%s/%s/" % (batch, skill):
        return "source %r does not name the ledger folder of this batch" % (data["source"],)
    if not isinstance(data["source_sha256"], str) or not SHA256_RE.fullmatch(data["source_sha256"]):
        return "source_sha256 is not 64 lowercase hex"
    if not isinstance(data["logs"], list) or not isinstance(data["smoke"], list):
        return "logs and smoke must be lists"
    seen = set()
    for where, entries, types, required in (("logs", data["logs"], LOG_TYPES, LOG_REQUIRED), ("smoke", data["smoke"], SMOKE_TYPES, tuple(SMOKE_TYPES))):
        for entry in entries:
            bad = _log_entry_problem(entry, types, required, where)
            if bad:
                return bad
            name = entry["file"]
            reason = _relative_problem(name)
            slash = name.count("/")
            if reason or (where == "logs" and slash) or (where == "smoke" and not (slash == 1 and name.startswith("smoke/"))):
                return "%s file %r is not a path inside the batch (%s)" % (where, name, reason or "expected %s" % ("x.json" if where == "logs" else "smoke/x.json"))
            if name in seen:
                return "file %r appears twice" % name
            seen.add(name)
    if not isinstance(data["ab"], dict):
        return "ab must be an object"
    for date, block in data["ab"].items():
        if not DATE_RE.fullmatch(date) or not isinstance(block, dict):
            return "ab key %r must be YYYY-MM-DD with an object value" % date
        per = block.get("per_runtime", {})
        if not isinstance(per, dict) or any(not isinstance(row, dict) for row in per.values()):
            return "ab %s per_runtime must be an object of objects" % date
    return None


def load_batch(path, root, skill: str, batch: str) -> dict:
    """The compact evidence file `path` of `skill`'s batch `batch` as a dict. Read without following a link and never when a link lies between it and `root`
    or it is a cloud placeholder; up to DOCTOR_MAX_FILE_BYTES. ValueError (the reason) for anything else: unreadable, not JSON, wrong schema or type."""
    path = Path(path)
    link = _link_below(path, root)
    if link is not None:
        raise ValueError("link %s lies on its path; it is not read" % link)
    if fs.path_is_cloud(path):
        raise ValueError("is a cloud placeholder; it is not read")
    try:
        data = _load_json(path)
    except OSError as exc:
        raise ValueError("cannot be read: %s: %s" % (type(exc).__name__, exc))
    except ValueError as exc:  # also json.JSONDecodeError, UnicodeDecodeError and the size limit
        raise ValueError("cannot be read: %s" % exc)
    bad = _batch_problem(data, skill, batch)
    if bad:
        raise ValueError(bad)
    return data


def _scan_evidence(root, evals_rel: str, skill: str):
    """(batches {file stem: dict}, stems that failed to load, problems, readable) for evals/<x>/evidence/*.json. A missing folder is empty and readable."""
    ev_dir = Path(root) / evals_rel / "evidence"
    batches, failed, problems = {}, set(), []
    if not os.path.lexists(ev_dir):
        return batches, failed, problems, True
    reason, found = _plain_tree(ev_dir)
    link = _link_below(ev_dir, root)
    if reason or link is not None:
        return batches, failed, ["evidence dir not safe to read: %s" % (reason or "link %s" % link)], False
    for path in sorted(p for p in found if p.parent == ev_dir and p.suffix == ".json" and not fs._is_dir_quiet(p)):
        try:
            batches[path.stem] = load_batch(path, root, skill, path.stem)
        except ValueError as exc:
            failed.add(path.stem)
            problems.append("evidence %s: %s" % (path.relative_to(root).as_posix(), exc))
    return batches, failed, problems, True


def catalog_problems(root) -> list[str]:
    """Every reason evals/catalog.json of the repository at `root` is not backed by counted evidence; a missing catalog or tool is a reason too."""
    root = Path(root)
    catalog = root / CATALOG_REL
    if not catalog.is_file():
        return ["%s is missing in the repository %s; the model_evaluated gate cannot run" % (CATALOG_REL, root)]
    if fs.is_link(catalog) or fs.path_is_cloud(catalog):
        return ["%s is a link or a cloud placeholder; it is not read" % CATALOG_REL]
    try:
        return model_evaluated_problems(catalog, root)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        return ["%s or its evidence cannot be read: %s: %s" % (CATALOG_REL, type(exc).__name__, exc)]


RESULT_VALUES = ("passed", "below-threshold", "partial", "not_run")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
BATCH_SHA_RE = re.compile(r"[0-9a-f]{40}")
AB_THRESHOLDS = (("positive_triggered", lambda v: v >= 4, ">= 4"), ("negative_triggered", lambda v: v == 0, "== 0"),
                 ("worse", lambda v: v == 0, "== 0"), ("better", lambda v: v >= 3, ">= 3"), ("pairs", lambda v: v == 5, "== 5"))


def model_evaluated_problems(catalog_path, root):
    """Return the list of reasons the catalog's model_evaluated / status claims are not backed by counted evidence."""
    problems = []
    catalog = _load_json(Path(catalog_path))
    declared = set()
    for skill in catalog["skills"]:
        name, targets = skill["name"], set(skill["targets"])
        flag, ev = skill.get("model_evaluated"), skill.get("evaluated")
        tag = "%s:" % name
        if "model_evaluated" in skill and not isinstance(flag, bool):
            problems.append("%s model_evaluated=%r must be a JSON bool" % (tag, flag))
        if (skill.get("status") == "model-evaluated") != (flag is True):
            problems.append("%s status %r does not match model_evaluated=%r (model-evaluated only for true)" % (tag, skill.get("status"), flag))
        bad = _relative_problem(skill["evals"])
        if bad:  # catalog values name folders below the repository; nothing outside it is walked or read (FR6.4)
            problems.append("%s evals %r must be a plain relative folder name: it %s" % (tag, skill["evals"], bad))
            continue
        evals_rel = skill["evals"].replace("\\", "/").rstrip("/")
        declared.add(evals_rel)
        # nothing under evidence/ is opened until the folder is known to hold plain files; every runtime in any batch must be a declared target
        batches, failed, scan_problems, readable = _scan_evidence(root, evals_rel, name)
        problems.extend("%s %s" % (tag, p) for p in scan_problems)
        if not readable:
            continue
        for stem, data in sorted(batches.items()):
            for entry in data["logs"] + data["smoke"]:
                if entry["runtime"] not in targets:
                    problems.append("%s log %s/%s has runtime %r not in targets %s" % (tag, stem, entry["file"], entry["runtime"], sorted(targets)))
        if ev is None:
            if flag is True:
                problems.append("%s model_evaluated=true without an `evaluated` block" % tag)
            continue
        result, batch_sha = ev.get("result"), ev.get("batch_sha")
        if result not in RESULT_VALUES:
            problems.append("%s evaluated.result %r must be one of %s" % (tag, result, list(RESULT_VALUES)))
        if not isinstance(batch_sha, str) or not BATCH_SHA_RE.fullmatch(batch_sha):
            problems.append("%s evaluated.batch_sha %r must be 40 lowercase hex" % (tag, batch_sha))
        if ev.get("batch_sha_kind") not in ("commit", "tree"):
            problems.append("%s evaluated.batch_sha_kind %r must be 'commit' or 'tree' (required with batch_sha)" % (tag, ev.get("batch_sha_kind")))
        below = False  # a ran harness missed AB_THRESHOLDS (or has no counted row); only reported as a problem when the flag is true
        sprint, harnesses = ev.get("sprint"), ev.get("harnesses")
        if not sprint or not isinstance(harnesses, dict):
            problems.append("%s evaluated needs sprint and harnesses" % tag)
            continue
        bad = _relative_problem(sprint)
        if bad:
            problems.append("%s evaluated.sprint %r must be a plain relative folder name: it %s" % (tag, sprint, bad))
            continue
        evidence, expected = ev.get("evidence"), "%s/evidence/%s.json" % (evals_rel, sprint)
        bad = "is required" if evidence is None else _relative_problem(evidence)
        if bad is not None or str(evidence).replace("\\", "/") != expected:
            problems.append("%s evaluated.evidence %r must be %s: it %s" % (tag, evidence, expected, bad or "names another file"))
            continue
        if flag is True and set(harnesses) != targets:
            problems.append("%s evaluated.harnesses keys %s != targets %s" % (tag, sorted(harnesses), sorted(targets)))
        if set(harnesses) - targets:
            problems.append("%s evaluated.harnesses has harness outside targets: %s" % (tag, sorted(set(harnesses) - targets)))
        if sprint in failed:  # its reason is already listed above
            continue
        if sprint not in batches:
            problems.append("%s %s is missing" % (tag, expected))
            continue
        batch = batches[sprint]
        counted, ran = summarize_logs(batch["logs"]), ran_logs(batch["logs"])
        cases_file = Path(root) / skill["evals"] / "cases.json"
        cases = _load_json(cases_file).get("cases", []) if cases_file.is_file() else []
        n_pos = sum(1 for c in cases if c.get("should_trigger") is True)
        n_neg = sum(1 for c in cases if c.get("should_trigger") is False)
        ab_report = ev.get("ab_report")
        if ab_report is not None and str(ab_report).replace("\\", "/") != expected:
            problems.append("%s ab_report %r must equal evaluated.evidence %s" % (tag, ab_report, expected))
        elif flag is True and ab_report is None:
            problems.append("%s model_evaluated=true needs evaluated.ab_report" % tag)
        date = ev.get("date")
        if (date is not None or any(v == "ran" for v in harnesses.values())) and not (isinstance(date, str) and DATE_RE.fullmatch(date)):
            problems.append("%s evaluated.date %r must be a string YYYY-MM-DD (it names the ab block of the evidence)" % (tag, date))
            continue
        ab_name = "ab-%s.json" % (date or "")
        ab = None
        if any(v == "ran" for v in harnesses.values()):
            if date not in batch["ab"]:
                problems.append("%s %s missing under %s" % (tag, ab_name, expected))
            else:
                ab = batch["ab"][date].get("per_runtime", {})
        for h, state in sorted(harnesses.items()):
            if state == "ran":
                row = (ab or {}).get(h)
                if ab is not None and row is None:
                    problems.append("%s harness %s is ran but absent from %s" % (tag, h, ab_name))
                    below = True
                    continue
                if row is None:
                    below = True
                if row is not None:
                    for key, ok, text in AB_THRESHOLDS:
                        if not ok(row.get(key, -1)):
                            below = True
                            if flag is True:  # flag false drops only this threshold application, never the integrity checks below
                                problems.append("%s %s %s=%r required %s" % (tag, h, key, row.get(key), text))
                    mine_logs = ran.get(h, {"with": [], "base": []})
                    pos = [l for l in mine_logs["with"] if l.get("kind") != "near-miss"]
                    neg = [l for l in mine_logs["with"] if l.get("kind") == "near-miss"]
                    if len(pos) != n_pos:
                        problems.append("%s %s has %d positive logs but cases.json has %d positive cases" % (tag, h, len(pos), n_pos))
                    if len(neg) != n_neg:
                        problems.append("%s %s has %d negative logs but cases.json has %d negative cases" % (tag, h, len(neg), n_neg))
                    ids = [l.get("case_id") for l in mine_logs["with"] if l.get("case_id") is not None]
                    if len(ids) != len(set(ids)):
                        problems.append("%s %s has duplicate case_id among its with-skill logs" % (tag, h))
                    n_base = len(mine_logs["base"])
                    if row.get("pairs") != n_base:
                        problems.append("%s %s pairs=%r but %d baseline logs ran" % (tag, h, row.get("pairs"), n_base))
                    if sum(row.get(k, 0) for k in ("better", "equal", "worse")) != row.get("pairs"):
                        problems.append("%s %s better+equal+worse = %r != pairs %r" % (tag, h, sum(row.get(k, 0) for k in ("better", "equal", "worse")), row.get("pairs")))
                    mine = counted.get(h, {"pos_trig": 0, "neg_trig": 0})
                    for key, got in (("positive_triggered", mine["pos_trig"]), ("negative_triggered", mine["neg_trig"])):
                        if row.get(key) != got:
                            problems.append("%s %s %s recount from logs = %r but %s says %r" % (tag, h, key, got, ab_name, row.get(key)))
            elif isinstance(state, str) and state.startswith("not_run:") and len(state) > len("not_run:"):
                if ab is not None and h in ab:
                    problems.append("%s harness %s is %r but %s has per_runtime numbers for it" % (tag, h, state, ab_name))
                if h in ran:
                    problems.append("%s harness %s is %r but %s has a ran log for it" % (tag, h, state, expected))
            else:
                problems.append("%s harness %s state %r must be 'ran' or 'not_run:<reason>'" % (tag, h, state))
        # `result` must equal the value recomputed from the harness states + threshold outcome. Priority when several apply:
        # not_run > below-threshold > partial > passed (not_run = no harness ran; partial = a declared harness did not run, the rest pass).
        n_ran = sum(1 for v in harnesses.values() if v == "ran")
        core = "not_run" if n_ran == 0 else ("below-threshold" if below else "passed")
        recomputed = "partial" if core == "passed" and n_ran < len(harnesses) else core
        if flag is True:
            # flag true is not relaxed: every old check above stays, and the block must say passed (not_run:<reason> harnesses keep being tolerated as before)
            if result != "passed" or core != "passed":
                problems.append("%s model_evaluated=true needs evaluated.result == 'passed' (declared %r, recomputed %r)" % (tag, result, recomputed))
        elif result == "passed":
            problems.append("%s model_evaluated=false but evaluated.result is 'passed' (recomputed %r)" % (tag, recomputed))
        elif result in RESULT_VALUES and result != recomputed:
            problems.append("%s evaluated.result %r != recomputed %r" % (tag, result, recomputed))
    evals_dir = Path(root) / "evals"
    if fs.is_link(evals_dir):  # a link, or a folder that cannot be probed (FR13.1): its evidence/ folders cannot be compared with the catalog, and that is said
        problems.append("evals/ is a link or cannot be probed; its evidence folders are not checked against the catalog")
    elif evals_dir.is_dir():  # an evidence/ folder whose skill the catalog does not name is never skipped silently
        linked, folders = [], []
        with os.scandir(evals_dir) as scan:
            for e in sorted(scan, key=lambda x: x.name):
                if e.is_symlink() or fs.is_link(evals_dir / e.name):  # asked first: is_dir(follow_symlinks=False) is False for a symlink and, from Python 3.12, a junction, and they must be said, not skipped
                    linked.append(e.name)  # left out; `evidence` is never probed through it
                elif not e.is_dir(follow_symlinks=False):
                    continue
                elif os.path.lexists(evals_dir / e.name / "evidence"):
                    folders.append(e.name)
        problems.extend("evals/%s is a link or cannot be probed; it is left out, its evidence folder is not checked" % n for n in linked)
        problems.extend("evals/%s/evidence has no catalog entry with evals: evals/%s" % (n, n) for n in folders if "evals/%s" % n not in declared)
    return problems
