#!/usr/bin/env python3
"""Contract-case runner for the studio.py command line (SPR-02, FR11).

It builds a throw-away copy of the repo from the code under test (the root studio.py, the skills/skill-creator-studio
folder that carries the engine, and the files repo_root() needs) plus the frozen inputs under
tests/fixtures/contract/inputs, runs every case of cases.json through one of five ways of calling the engine, and
normalises the result so it can be compared with golden.json.

Normalisation beyond paths and times (engine 1211bfa behaves differently per OS, and the contract is the shared part):
  - the sha256 of a file in a `tree` is taken after CRLF -> LF (cmd_new writes text without newline=, so Windows gives CRLF);
  - in the JSON of `fmt` the `files` list is sorted by path (the folder walk order is OS-dependent). Nothing else is sorted.

  R  cwd = the repo copy, `python studio.py ...`
  C  cwd = another folder, absolute path to the repo copy's studio.py
  E  cwd = the engine skill folder of the copy, `python scripts/studio.py ...`
  S  the engine skill copied out of any repo, `python <copy>/scripts/studio.py ...`
  Z  `package` of the engine skill, unzipped, `python <unzipped>/scripts/studio.py ...`
  L  the real repo under test (exit code only)

Usage:
  python tests/contract_runner.py                      compare the working tree with golden.json
  python tests/contract_runner.py --engine <repo root> run another tree (for example a `git archive` of 1211bfa)
  python tests/contract_runner.py --write-golden --engine <archive of 1211bfa>   create golden.json (refused when it exists)
  python tests/contract_runner.py --record-after <case-id> --by SPR-03/TKn      record a deliberate change: writes `after`, never `before`
  python tests/contract_runner.py --only R-version     run the cases whose id starts with the text
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
CONTRACT_DIR = TESTS_DIR / "fixtures" / "contract"
INPUTS_DIR = CONTRACT_DIR / "inputs"
CASES_FILE = CONTRACT_DIR / "cases.json"
GOLDEN_FILE = CONTRACT_DIR / "golden.json"
TIMEOUT = 120
VIAS = ("R", "C", "E", "S", "Z", "L")
COMPARE_KEYS = ("exit", "stdout_json", "stdout_text", "stderr", "tree", "zip")

TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}[:\-]\d{2}[:\-]\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
SHA_RE = re.compile(r"SHA256: [0-9a-f]{64}")
SLOT_RE = re.compile(r"\{(OUT|REPO|SELF|SELFPARENT)\}")
KEEP_ENV = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}


def load_cases() -> list:
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]


def load_golden() -> dict:
    return json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))["cases"]


def expected_result(entry: dict) -> dict:
    """The answer a golden entry asks for: a deliberately changed case keeps `before` until its sprint task fills `after`."""
    if "changed_by" in entry:
        return entry["after"] if entry.get("after") is not None else entry["before"]
    return entry


def build_repo(engine: Path, dest: Path) -> None:
    """Repo copy = code under test + frozen inputs. Files the code under test does not have are simply absent."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    dest.mkdir(parents=True)
    shutil.copyfile(engine / "studio.py", dest / "studio.py")
    (dest / "skills").mkdir()
    shutil.copytree(engine / "skills" / "skill-creator-studio", dest / "skills" / "skill-creator-studio", ignore=ignore)
    for name in (".claude-plugin", "standards", "templates"):
        if (engine / name).is_dir():
            shutil.copytree(engine / name, dest / name, ignore=ignore)
    shutil.copytree(INPUTS_DIR, dest, dirs_exist_ok=True)


def _env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in KEEP_ENV}
    env.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(home), "USERPROFILE": str(home)})
    return env


def _run(script: str, args: list, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-X", "utf8", script] + list(args), cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)


class Normaliser:
    """Turns temp paths into <REPO> / <TMP>, `\\` into `/`, ISO times into <TS>. Never drops or reorders anything."""

    def __init__(self, repo: Path, case_dir: Path, base: Path):
        self.rules = []
        for path, token in ((repo, "<REPO>"), (case_dir, "<TMP>"), (base, "<TMP>")):
            forms = {str(path).replace("\\", "/"), str(path.resolve()).replace("\\", "/"), os.path.realpath(path).replace("\\", "/")}
            for form in sorted(forms, key=len, reverse=True):
                self.rules.append((re.compile(re.escape(form), re.IGNORECASE), token))

    def text(self, s: str) -> str:
        s = s.replace("\r\n", "\n").replace("\\", "/")
        for rx, token in self.rules:
            s = rx.sub(token, s)
        return SHA_RE.sub("SHA256: <SHA>", TS_RE.sub("<TS>", s))

    def json(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.json(v) for v in value]
        if isinstance(value, dict):
            return {self.text(k): self.json(v) for k, v in value.items()}
        return value


def tree_of(path: Path) -> dict:
    """{relative posix path: sha256 of the bytes with CRLF folded to LF | "<dir>"} for everything below `path`, sorted; "<missing>" if it does not exist."""
    if not path.exists():
        return {"<missing>": "<missing>"}
    out = {}
    for p in sorted(path.rglob("*"), key=lambda q: q.relative_to(path).as_posix()):
        rel = p.relative_to(path).as_posix()
        if "__pycache__" in p.relative_to(path).parts:
            continue
        out[rel] = "<dir>" if p.is_dir() else hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return out


def stderr_prefix(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.split(":", 1)[0].strip()
    return ""


def run_case(case: dict, engine: Path, base: Path, shared_repo: Path) -> dict:
    cid = case["id"]
    via = case["via"]
    if via not in VIAS:
        raise ValueError("%s: unknown via %r" % (cid, via))
    bad = set(case["compare"]) - set(COMPARE_KEYS)
    if bad:
        raise ValueError("%s: unknown compare %s" % (cid, sorted(bad)))
    case_dir = base / re.sub(r"[^A-Za-z0-9_.-]", "_", cid)
    out = case_dir / "out"
    out.mkdir(parents=True)
    (case_dir / "home").mkdir()
    env = _env(case_dir / "home")
    repo = shared_repo
    if case.get("fresh"):
        repo = case_dir / "repo"
        build_repo(engine, repo)
    live = repo / "skills" / "skill-creator-studio"
    other = case_dir / "cwd"
    other.mkdir()
    self_dir = live
    if via == "R":
        cwd, script = repo, "studio.py"
    elif via == "C":
        cwd, script = other, str(repo / "studio.py")
    elif via == "E":
        cwd, script = live, "scripts/studio.py"
    elif via == "S":
        self_dir = case_dir / "s" / "skill-creator-studio"
        shutil.copytree(live, self_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        cwd, script = other, str(self_dir / "scripts" / "studio.py")
    elif via == "Z":
        made = _run(str(repo / "studio.py"), ["package", str(live), "--out", str(case_dir / "zpkg")], case_dir, env)
        if made.returncode != 0:
            raise RuntimeError("%s: package of the engine skill failed (%d): %s" % (cid, made.returncode, made.stderr[-400:]))
        with zipfile.ZipFile(case_dir / "zpkg" / "skill-creator-studio.zip") as zf:
            zf.extractall(case_dir / "zx")
        self_dir = case_dir / "zx" / "skill-creator-studio"
        cwd, script = other, str(self_dir / "scripts" / "studio.py")
    else:  # L: the real repo under test
        cwd, script = engine, "studio.py"
    slots = {"OUT": out, "REPO": repo, "SELF": self_dir, "SELFPARENT": self_dir.parent}
    args = [SLOT_RE.sub(lambda m: str(slots[m.group(1)]), a) for a in case["args"]]
    proc = _run(script, args, cwd, env)
    norm = Normaliser(repo, case_dir, base)
    result: dict = {"exit": proc.returncode}
    for key in case["compare"]:
        if key == "stdout_json":
            try:
                result[key] = norm.json(json.loads(proc.stdout))
                if case["args"][0] == "fmt" and isinstance(result[key].get("files"), list):
                    result[key]["files"].sort(key=lambda item: item["path"])
            except ValueError:
                result[key] = {"<not json>": norm.text(proc.stdout)[:400]}
        elif key == "stdout_text":
            result[key] = norm.text(proc.stdout)
        elif key == "stderr":
            result[key] = norm.text(stderr_prefix(proc.stderr))
        elif key == "tree":
            result[key] = {norm.text(str(slots_path(t, slots))): tree_of(slots_path(t, slots)) for t in case["trees"]}
        elif key == "zip":
            names = {}
            for z in case["zips"]:
                zp = slots_path(z, slots)
                names[norm.text(str(zp))] = sorted(zipfile.ZipFile(zp).namelist()) if zp.is_file() else ["<missing>"]
            result[key] = names
    return {k: result[k] for k in ("exit",) + tuple(k for k in COMPARE_KEYS if k in result and k != "exit")}


def slots_path(template: str, slots: dict) -> Path:
    return Path(SLOT_RE.sub(lambda m: str(slots[m.group(1)]), template))


def run_all(engine: Path, only: str = "", exact: bool = False) -> dict:
    """Run every case against `engine` (a repo root) in a fresh temp dir that is removed afterwards. Returns {id: result}.
    `only` selects the cases whose id starts with it (exact: whose id is it)."""
    engine = Path(engine).resolve()
    base = Path(tempfile.mkdtemp(prefix="studio-contract-")).resolve()
    try:
        shared = base / "ws"
        build_repo(engine, shared)
        return {c["id"]: run_case(c, engine, base, shared) for c in load_cases() if (c["id"] == only if exact else c["id"].startswith(only))}
    finally:
        shutil.rmtree(base, ignore_errors=True)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def compare(results: dict, golden: dict) -> list:
    """Human-readable mismatches between results and golden (order-sensitive for every JSON value)."""
    problems = []
    for cid, got in results.items():
        if cid not in golden:
            problems.append("%s: no golden answer" % cid)
            continue
        want = expected_result(golden[cid])
        if dumps(want) != dumps(got):
            problems.append("%s: differs\n--- golden\n%s\n--- got\n%s" % (cid, dumps(want), dumps(got)))
    return problems


def write_golden(results: dict, source: str) -> None:
    cases = {c["id"]: c for c in load_cases()}
    out = {}
    for cid, res in results.items():
        if cases[cid].get("changed_by"):
            out[cid] = {"changed_by": cases[cid]["changed_by"], "before": res, "after": None}
        else:
            out[cid] = res
    store(GOLDEN_FILE, dumps({"schema": 1, "source": source, "cases": out}))


def store(path: Path, text: str) -> None:
    """Write `text` plus a final LF, UTF-8, LF line ends on every OS."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text + "\n")


def record_after(entry: dict, result: dict, by: str) -> dict:
    """The golden entry once the case is recorded as deliberately changed. A flat entry is wrapped: {changed_by, before: the entry as it was, after: result}.
    An entry that is already wrapped keeps `changed_by` and `before` and takes the new `after`. `before` is never written (SPR-03 RK2)."""
    if "changed_by" in entry:
        return {"changed_by": entry["changed_by"], "before": entry["before"], "after": result}
    return {"changed_by": by, "before": entry, "after": result}


def cmd_record_after(cid: str, by: str, engine: Path) -> int:
    golden = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    results = run_all(engine, cid, exact=True)
    if cid not in golden["cases"] or cid not in results:
        print("ERROR: %s is not a case of this suite" % cid, file=sys.stderr)
        return 2
    golden["cases"][cid] = record_after(golden["cases"][cid], results[cid], by)
    store(GOLDEN_FILE, dumps(golden))
    raw = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    for case in raw["cases"]:
        if case["id"] == cid and not case.get("changed_by"):  # cases.json and golden.json must mark the same cases (test_contract_regression)
            case["changed_by"] = by
            store(CASES_FILE, json.dumps(raw, indent=1, ensure_ascii=False))
    print("recorded after of %s (by %s)" % (cid, by))
    return 0


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", default=str(REPO_ROOT), help="repo root of the code under test (default: this repo)")
    ap.add_argument("--write-golden", action="store_true", help="create golden.json from the run instead of comparing (refused when it exists)")
    ap.add_argument("--record-after", metavar="CASE_ID", help="record the result of this case as the `after` of its golden entry")
    ap.add_argument("--by", help="with --record-after: who changed the answer, for example SPR-03/TK1")
    ap.add_argument("--source", default="git archive 1211bfa", help="label stored in golden.json")
    ap.add_argument("--only", default="", help="run only the cases whose id starts with this text")
    args = ap.parse_args(argv)
    if args.record_after:
        if not args.by or args.write_golden or args.only:
            ap.error("--record-after needs --by and takes neither --write-golden nor --only")
        return cmd_record_after(args.record_after, args.by, Path(args.engine))
    if args.write_golden:
        if GOLDEN_FILE.exists():
            print("ERROR: %s exists; its `before` answers are frozen - use --record-after <case-id> --by <task>" % GOLDEN_FILE, file=sys.stderr)
            return 2
        if args.only:
            ap.error("--write-golden needs the whole suite (no --only)")
    results = run_all(Path(args.engine), args.only)
    if args.write_golden:
        write_golden(results, args.source)
        print("wrote %s: %d cases" % (GOLDEN_FILE, len(results)))
        return 0
    problems = compare(results, load_golden())
    for p in problems:
        print(p)
    print("%d cases, %d differ" % (len(results), len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
