"""SPR-33 TK9: `studio.py doctor` v1, report-only scan of many skill roots (SPEC 9.11, FR17, SC10)."""
import builtins
import contextlib
import importlib.util
import io
import json
import ntpath
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "doctor"
CLEAN_ROOTS = ";".join(str(ROOT / x) for x in ("skills", "examples/data-quality-audit", "examples/exemplar", "examples/exemplar-vi"))
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402

studio = _engine.engine
studio_const = _engine.const  # constants live in studio_const (SPR-02 TK4a)
studio_fs = _engine.fs  # file-system helpers live in studio_fs
studio_doctor = _engine.doctor  # SPR-02 TK4c
studio_validate = _engine.validate  # SPR-02 TK4b

SKILL = "---\nname: %s\ndescription: Checks a toy example. Use when testing the doctor command.\n%s---\n\n# Title\n\nShort body.\n"


def run(*argv):
    """Run `studio.py doctor ...` in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = studio.main(["doctor", *argv])
    return code, out.getvalue(), err.getvalue()


def make_skill(parent: Path, name: str, extra: str = "") -> Path:
    folder = parent / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_bytes((SKILL % (name, extra)).encode("utf-8"))
    return folder


def make_dir_link(test, link: Path, target: Path) -> None:
    """A directory symlink, or a junction on Windows without the symlink privilege; skips the test when neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if link.exists():
            return
    test.skipTest("cannot create a symlink or junction here")


def snapshot(base: Path):
    return sorted((p.relative_to(base).as_posix(), p.stat().st_size, p.stat().st_mtime_ns) for p in base.rglob("*"))


def codes_of(report, skill_name=None):
    return {c["code"] for s in report["skills"] if skill_name in (None, s["name"]) for c in s["codes"]}


@contextlib.contextmanager
def watching():
    """Record every call that reaches the OS layer as (function, path, follows-links); used to prove a path was never touched."""
    calls = []

    def wrap(name, real):
        def wrapper(path=".", *a, **k):
            calls.append((name, "" if isinstance(path, int) else os.fspath(path), k.get("follow_symlinks", True)))
            return real(path, *a, **k)
        return wrapper

    targets = [(os, n) for n in ("scandir", "listdir", "stat", "lstat", "readlink", "access")] + [(builtins, "open"), (io, "open")]
    if hasattr(ntpath, "_getfinalpathname"):
        targets.append((ntpath, "_getfinalpathname"))
    with contextlib.ExitStack() as stack:
        for owner, name in targets:
            stack.enter_context(mock.patch.object(owner, name, wrap(name, getattr(owner, name))))
        yield calls


def norm(path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_under(path, base) -> bool:
    return norm(path) == norm(base) or norm(path).startswith(norm(base) + os.sep)


@contextlib.contextmanager
def cloud_flagged(flags):
    """os.scandir whose entries report the given Windows file attributes ({full path: attributes}), as OneDrive placeholders do."""
    real = os.scandir
    wanted = {norm(k): v for k, v in flags.items()}

    class Entry:
        def __init__(self, entry):
            self._entry = entry

        def __getattr__(self, name):
            return getattr(self._entry, name)

        def stat(self, *, follow_symlinks=True):
            base = self._entry.stat(follow_symlinks=follow_symlinks)
            fields = {k: getattr(base, k) for k in dir(base) if k.startswith("st_")}
            fields["st_file_attributes"] = wanted[norm(self._entry.path)]
            return types.SimpleNamespace(**fields)

    class Scan:
        def __init__(self, path):
            self._inner = real(path)

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

        def __iter__(self):
            return (Entry(e) if norm(e.path) in wanted else e for e in self._inner)

    with mock.patch.object(os, "scandir", Scan):
        yield


class DoctorTests(unittest.TestCase):
    def test_doctor_dedupes_mirror(self):
        code, out, _ = run("--roots", str(FIX), "--json")
        report = json.loads(out)
        names = sorted(s["name"] for s in report["skills"])
        self.assertEqual(names, ["bad-dir", "bad-key", "bad-long-ref"], "the .claude/skills mirror must not be counted")
        code, out, _ = run("--roots", "%s;%s" % (FIX, FIX / "bad-key"), "--json")
        report = json.loads(out)
        self.assertEqual([s["name"] for s in report["skills"]].count("bad-key"), 1, "overlapping roots count a skill once")
        self.assertEqual(report["totals"]["skills"], 3)

    def test_doctor_exit_codes_0_1_2(self):
        code, out, _ = run("--roots", CLEAN_ROOTS, "--json")
        clean = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(clean["totals"]["errors"], 0)
        self.assertGreaterEqual(clean["totals"]["skills"], 3)
        code, out, _ = run("--roots", str(FIX), "--json")
        bad = json.loads(out)
        self.assertEqual(code, 1)
        self.assertTrue({"ST5", "FM4", "ST8"} <= codes_of(bad), codes_of(bad))
        self.assertEqual(run("--roots", str(ROOT / ".tmp" / "khong-co"), "--json")[0], 2)
        code, _, err = run("--roots", CLEAN_ROOTS, "--fail-on", "new")
        self.assertEqual(code, 2)
        self.assertIn("--baseline", err)
        # --fail-on warn trips on warnings that --fail-on error ignores
        with tempfile.TemporaryDirectory() as tmp:
            sk = make_skill(Path(tmp), "only-warns")
            (sk / "SKILL.md").write_bytes((SKILL % ("only-warns", "")).replace("Use when testing", "Tests").encode())  # DS3 WARN, no ERROR
            self.assertEqual(run("--roots", tmp)[0], 0)
            self.assertEqual(run("--roots", tmp, "--fail-on", "warn")[0], 1)
        # negative: a broken baseline file and an unusable --out are exit 2, not a crash
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            wrong = Path(tmp) / "wrong.json"
            wrong.write_text(json.dumps({"schema": 99, "skills": []}), encoding="utf-8")
            for base in (broken, wrong, Path(tmp) / "absent.json"):
                code, _, err = run("--roots", CLEAN_ROOTS, "--baseline", str(base))
                self.assertEqual(code, 2, base.name)
                self.assertIn("baseline", err.lower())
            code, _, err = run("--roots", CLEAN_ROOTS, "--out", str(Path(tmp) / "no-such-dir" / "r.json"))
            self.assertEqual(code, 2)
            self.assertFalse((Path(tmp) / "no-such-dir").exists(), "doctor must not create the parent of --out")

    def test_doctor_out_refuses_roots_and_skills_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = Path(tmp) / "scan"
            scan.mkdir()
            make_skill(scan, "alpha")
            self.assertEqual(run("--roots", str(scan), "--out", str(scan / "r.json"))[0], 2)
            self.assertFalse((scan / "r.json").exists())
            skills_dir = Path(tmp) / "skills"
            skills_dir.mkdir()
            self.assertEqual(run("--roots", str(scan), "--out", str(skills_dir / "r.json"))[0], 2)
            self.assertFalse((skills_dir / "r.json").exists())
            self.assertEqual(run("--roots", str(scan), "--out", str(Path(tmp) / "ok.json"))[0], 0)
            self.assertTrue((Path(tmp) / "ok.json").is_file())

    def test_doctor_profile_opcos_relaxes_st6_and_source_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plugins"
            (root / "shared").mkdir(parents=True)
            (root / "shared" / "note.md").write_bytes(b"shared note\n")
            sk = make_skill(root, "linker", "source: https://example.test/x\nsource_sha: abc\n")
            links = b"\nSee [note](../shared/note.md) and [gone](../shared/gone.md) and [out](../../../outside.md).\n"
            (sk / "SKILL.md").write_bytes((sk / "SKILL.md").read_bytes() + links)
            make_skill(root, "has-meta", "metadata:\n  opcos_when: always\n")
            portable = json.loads(run("--roots", str(root), "--json")[1])
            opcos = json.loads(run("--roots", str(root), "--profile", "opcos", "--json")[1])

            def levels(report, skill, code):
                return sorted(c["level"] for s in report["skills"] if s["name"] == skill for c in s["codes"] if c["code"] == code)

            self.assertEqual(levels(portable, "linker", "FM4"), ["ERROR", "ERROR"])
            self.assertEqual(levels(opcos, "linker", "FM4"), ["WARN", "WARN"])
            self.assertEqual(levels(portable, "linker", "ST6"), ["ERROR", "ERROR", "ERROR"])
            self.assertEqual(levels(opcos, "linker", "ST6"), ["ERROR", "ERROR", "WARN"], "only the existing link inside the scanned root is relaxed")
            self.assertEqual(levels(opcos, "linker", "MD1"), ["NOTE"])
            self.assertEqual(levels(opcos, "has-meta", "MD1"), [])
            self.assertEqual(levels(portable, "linker", "MD1"), [], "MD1 is an opcos-profile code")
            self.assertEqual(portable["totals"]["notes"], 0)
            self.assertGreaterEqual(opcos["totals"]["notes"], 1)
            # a NOTE never changes the exit code
            only_notes = Path(tmp) / "only-notes"
            make_skill(only_notes, "plain")
            self.assertEqual(run("--roots", str(only_notes), "--profile", "opcos", "--fail-on", "warn")[0], 0)

    def test_doctor_skips_secret_and_cloud_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            ok = make_skill(home / "proj", "fine-skill")
            trap_secret = make_skill(home / ".secret", "trap-secret")
            trap_cloud = make_skill(home / "proj" / "OneDrive - X", "trap-cloud")
            make_skill(home / "SharePoint-site", "trap-share")
            make_skill(home / "proj" / ".secret", "trap-nested-secret")
            (trap_secret.parent / "token.json").write_bytes(b"{}")
            (ok / "auth.json").write_bytes(b"{}")  # secret-looking file inside a skill: never opened
            (ok / "references" / "OneDrive-copy").mkdir(parents=True)  # a folder named like a zone inside a skill: never entered
            (ok / "references" / "OneDrive-copy" / "deep.md").write_bytes(b"line\n" * 300)
            absent_cloud = home / "proj" / "OneDrive - Y"
            touched = []

            def watch(real):
                def wrapper(path=".", *a, **k):
                    touched.append("" if isinstance(path, int) else os.fspath(path))
                    return real(path, *a, **k)
                return wrapper

            env = {"HOME": str(home), "USERPROFILE": str(home)}
            with mock.patch.dict(os.environ, env), mock.patch.object(os, "scandir", watch(os.scandir)), \
                    mock.patch.object(os, "listdir", watch(os.listdir)), mock.patch.object(os, "stat", watch(os.stat)), \
                    mock.patch.object(os, "lstat", watch(os.lstat)), mock.patch.object(builtins, "open", watch(builtins.open)), \
                    mock.patch.object(io, "open", watch(io.open)):
                code, out, _ = run("--roots", ";".join(map(str, (home / "proj", home / ".secret", home / "SharePoint-site", trap_cloud, absent_cloud))), "--json")
            report = json.loads(out)
            self.assertEqual(code, 0, out)
            self.assertEqual([s["name"] for s in report["skills"]], ["fine-skill"])
            reasons = {(Path(s["path"]).name, s["reason"]) for s in report["skipped"]}
            self.assertIn((".secret", "secret-zone"), reasons)
            self.assertIn(("OneDrive - X", "cloud"), reasons)
            self.assertIn(("OneDrive - Y", "cloud"), reasons)
            self.assertIn(("SharePoint-site", "cloud"), reasons)
            for hidden in ("trap-secret", "trap-cloud", "trap-share", "trap-nested-secret"):
                self.assertNotIn(hidden, json.dumps(report["skills"]))
            self.assertTrue(touched, "the access watcher saw nothing; the test would prove nothing")
            for path in touched:
                low = path.replace("\\", "/").lower()
                self.assertNotIn("/.secret", low, path)
                self.assertNotIn("onedrive", low, path)
                self.assertNotIn("sharepoint", low, path)
                self.assertFalse(low.endswith("auth.json"), path)

    def test_doctor_secret_zone_through_a_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            make_skill(home / ".secret", "trap-secret")
            work = home / "work"
            make_skill(work, "fine-skill")
            make_dir_link(self, work / "innocent", home / ".secret")
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                report = json.loads(run("--roots", str(work), "--json")[1])
                alias = json.loads(run("--roots", str(work / "innocent"), "--json")[1])
            self.assertEqual([s["name"] for s in report["skills"]], ["fine-skill"])
            self.assertIn("link", {s["reason"] for s in report["skipped"]})
            self.assertEqual(alias["skills"], [])
            self.assertEqual({s["reason"] for s in alias["skipped"]}, {"secret-zone"})

    def test_doctor_baseline_new_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.json"
            self.assertEqual(run("--roots", str(FIX), "--out", str(first))[0], 1)
            base = json.loads(first.read_text(encoding="utf-8"))
            code, out, _ = run("--roots", str(FIX), "--json", "--baseline", str(first), "--fail-on", "new")
            self.assertEqual(code, 0, out)
            self.assertEqual(json.loads(out)["new_vs_baseline"], [])
            # baseline with one bad-key finding removed: exactly that (skill, code) pair is new
            dropped = []
            for skill in base["skills"]:
                if skill["name"] == "bad-key":
                    dropped = [c for c in skill["codes"] if c["code"] == "FM4"]
                    skill["codes"] = [c for c in skill["codes"] if c["code"] != "FM4"]
            self.assertEqual(len(dropped), 1)
            trimmed = Path(tmp) / "trimmed.json"
            trimmed.write_text(json.dumps(base), encoding="utf-8")
            code, out, _ = run("--roots", str(FIX), "--json", "--baseline", str(trimmed), "--fail-on", "new")
            new = json.loads(out)["new_vs_baseline"]
            self.assertEqual(code, 1)
            self.assertEqual([(Path(n["path"]).name, n["code"], n["before"], n["after"]) for n in new], [("bad-key", "FM4", 0, 1)])
            # more findings in the baseline than now are not "new"
            more = json.loads(first.read_text(encoding="utf-8"))
            more["skills"][0]["codes"] = more["skills"][0]["codes"] * 3
            (Path(tmp) / "more.json").write_text(json.dumps(more), encoding="utf-8")
            self.assertEqual(json.loads(run("--roots", str(FIX), "--json", "--baseline", str(Path(tmp) / "more.json"))[1])["new_vs_baseline"], [])

    def test_doctor_baseline_ignores_notes_but_counts_new_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.json"
            empty.write_text(json.dumps({"schema": 1, "skills": []}), encoding="utf-8")
            plain = Path(tmp) / "plain"
            make_skill(plain, "only-note")
            code, out, _ = run("--roots", str(plain), "--profile", "opcos", "--json", "--baseline", str(empty), "--fail-on", "new")
            self.assertEqual(json.loads(out)["totals"]["notes"], 1)
            self.assertEqual((code, json.loads(out)["new_vs_baseline"]), (0, []), "a NOTE is never new")
            bad = Path(tmp) / "bad"
            make_skill(bad, "has-error", "triggers: x\n")
            code, out, _ = run("--roots", str(bad), "--json", "--baseline", str(empty), "--fail-on", "new")
            self.assertEqual(code, 1)
            self.assertEqual([(n["code"], n["before"], n["after"]) for n in json.loads(out)["new_vs_baseline"]], [("FM4", 0, 1)])

    def test_doctor_st8_unknown_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = make_skill(Path(tmp), "dir-skill")
            for name in ("examples", "agents", "tests", "references", "scripts", "assets", "evals", ".git"):
                (sk / name).mkdir()
            found = [f for f in studio_validate.validate_skill(sk) if f["code"] == "ST8"]
            self.assertEqual([f["level"] for f in found], ["WARN"])
            self.assertIn("examples", found[0]["message"])
            self.assertEqual(len([f for f in studio_validate.validate_skill(sk, profile="opcos") if f["code"] == "ST8"]), 1)
        report = json.loads(run("--roots", str(FIX), "--json")[1])
        by_name = {s["name"]: {c["code"] for c in s["codes"]} for s in report["skills"]}
        self.assertIn("ST8", by_name["bad-dir"])
        self.assertNotIn("ST8", by_name["bad-key"])
        self.assertNotIn("ST8", by_name["bad-long-ref"], "references/ is an allowed directory")

    def test_doctor_st3_body_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = make_skill(Path(tmp), "big-body")
            head = (sk / "SKILL.md").read_bytes()
            body_start = head.index(b"---\n\n") + len(b"---\n")  # the validator body starts at the blank line after the closing ---
            fill = studio_const.CODEX_BODY_MAX_BYTES - len(head[body_start:])
            (sk / "SKILL.md").write_bytes(head + b"x" * fill)
            self.assertEqual([f for f in studio_validate.validate_skill(sk) if f["code"] == "ST3"], [], "exactly the limit is allowed")
            (sk / "SKILL.md").write_bytes(head + b"x" * (fill + 1))
            found = [f for f in studio_validate.validate_skill(sk) if f["code"] == "ST3"]
            self.assertEqual([f["level"] for f in found], ["WARN"])

    def test_doctor_writes_only_out(self):
        before = snapshot(FIX)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            written, mutated = [], []
            real_open = builtins.open

            def spy_open(path, mode="r", *a, **k):
                if isinstance(path, (str, os.PathLike)) and any(c in mode for c in "wax+"):
                    written.append(os.path.normcase(os.path.abspath(os.fspath(path))))
                return real_open(path, mode, *a, **k)

            replaced = []

            def spy_mut(name):
                real = getattr(os, name)

                def wrapper(*a, **k):
                    mutated.append(name)
                    if name == "replace":
                        replaced.append((os.path.basename(os.fspath(a[0])), os.path.basename(os.fspath(a[1]))))
                    return real(*a, **k)
                return wrapper

            patches = [mock.patch.object(builtins, "open", spy_open), mock.patch.object(io, "open", spy_open)]
            patches += [mock.patch.object(os, n, spy_mut(n)) for n in ("mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir", "utime", "chmod")]
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                code, stdout, _ = run("--roots", str(FIX), "--json", "--out", str(out))
            self.assertEqual(code, 1)
            # SPR-05 TK4: --out is written under a temp name beside it (os.open / CreateFile, not builtins.open) and renamed over the name with one os.replace
            self.assertEqual(written, [], "doctor opened something for writing with open()")
            self.assertEqual(mutated, ["replace"], "doctor created, removed, renamed or re-stamped something besides the one rename of the temp file")
            self.assertTrue(replaced[0][0].startswith(".report.json.") and replaced[0][0].endswith(".spr05tmp"), replaced)
            self.assertEqual(replaced[0][1], out.name)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["report.json"])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["schema"], 1)
            self.assertNotIn('"schema"', stdout, "with --out the JSON goes to the file, stdout keeps a summary")
        self.assertEqual(snapshot(FIX), before, "doctor changed the scanned tree")
        self.assertFalse(list(FIX.rglob("*.json")))

    def test_doctor_json_schema(self):
        report = json.loads(run("--roots", str(FIX), "--json")[1])
        self.assertEqual(list(report), ["schema", "generated_at", "studio_version", "roots", "skills", "skipped", "totals", "new_vs_baseline"])
        self.assertEqual(report["schema"], 1)
        self.assertRegex(report["generated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(report["studio_version"], studio_const.VERSION)
        self.assertEqual(len(report["roots"]), 1)
        self.assertEqual(list(report["totals"]), ["skills", "errors", "warnings", "notes"])
        self.assertEqual(report["new_vs_baseline"], [])
        for skill in report["skills"]:
            self.assertEqual(list(skill), ["path", "name", "lang", "errors", "warnings", "codes"])
            self.assertIn(skill["lang"], ("en", "vi"))
            self.assertEqual(skill["errors"], sum(c["level"] == "ERROR" for c in skill["codes"]))
            self.assertEqual(skill["warnings"], sum(c["level"] == "WARN" for c in skill["codes"]))
            for c in skill["codes"]:
                self.assertEqual(list(c), ["code", "level", "file", "line", "message"])
                self.assertIn(c["level"], ("ERROR", "WARN", "NOTE"))
        self.assertEqual(report["totals"]["errors"], sum(s["errors"] for s in report["skills"]))
        for entry in report["skipped"]:
            self.assertEqual(list(entry), ["path", "reason"])

    def test_doctor_limit_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            make_skill(root / "a" / "b" / "c", "deep-skill")
            make_skill(root, "near-skill")
            with mock.patch.object(studio_const, "DOCTOR_MAX_DEPTH", 2):
                report = json.loads(run("--roots", str(root), "--json")[1])
            self.assertEqual([s["name"] for s in report["skills"]], ["near-skill"])
            self.assertIn("limit", {s["reason"] for s in report["skipped"]})
            outside = Path(tmp) / "outside"
            make_skill(outside, "outside-skill")
            make_dir_link(self, root / "linked", outside)
            report = json.loads(run("--roots", str(root), "--json")[1])
            self.assertNotIn("outside-skill", [s["name"] for s in report["skills"]])
            self.assertIn(("linked", "link"), {(Path(s["path"]).name, s["reason"]) for s in report["skipped"]})

    def test_doctor_roots_file_and_cache_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_skill(Path(tmp) / "one", "one-skill")
            make_skill(Path(tmp) / "one" / "my-cache", "cached-skill")
            make_skill(Path(tmp) / "node_modules", "mod-skill")
            listing = Path(tmp) / "roots.txt"
            listing.write_text("# comment\n\n%s\n" % (Path(tmp) / "one"), encoding="utf-8")
            report = json.loads(run("--roots-file", str(listing), "--json")[1])
            self.assertEqual([s["name"] for s in report["skills"]], ["one-skill"])
            report = json.loads(run("--roots-file", str(listing), "--include-cache", "--json")[1])
            self.assertEqual(sorted(s["name"] for s in report["skills"]), ["cached-skill", "one-skill"])
            report = json.loads(run("--roots", tmp, "--json")[1])
            self.assertNotIn("mod-skill", [s["name"] for s in report["skills"]])

    def test_doctor_reference_into_secret_zone_is_not_stat_ed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / ".secret").mkdir(parents=True)
            (home / ".secret" / "note.md").write_bytes(b"private\n")
            sk = make_skill(home / "proj", "linker")
            link = b"\nSee [x](../../.secret/note.md) and [y](../../OneDrive - X/a.md).\n"
            (sk / "SKILL.md").write_bytes((sk / "SKILL.md").read_bytes() + link)
            touched = []
            real_stat = os.stat

            def watch_stat(path, *a, **k):
                touched.append(os.fspath(path) if not isinstance(path, int) else "")
                return real_stat(path, *a, **k)

            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}), mock.patch.object(os, "stat", watch_stat):
                found = [f for f in studio_validate.validate_skill(sk, profile="opcos", allow_links_under=home) if f["code"] == "ST6"]
            self.assertEqual([f["level"] for f in found], ["ERROR", "ERROR"], "a link into a forbidden zone stays an ERROR even for the opcos profile")
            for path in touched:
                low = path.replace("\\", "/").lower()
                self.assertNotIn("/.secret", low, path)
                self.assertNotIn("onedrive", low, path)

    def test_validate_skill_default_profile_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shared").mkdir()
            (root / "shared" / "note.md").write_bytes(b"x\n")
            sk = make_skill(root, "plain", "source: a\n")
            (sk / "SKILL.md").write_bytes((sk / "SKILL.md").read_bytes() + b"\n[n](../shared/note.md)\n")
            for kwargs in ({}, {"allow_links_under": root}, {"profile": "portable", "allow_links_under": root}):
                found = studio_validate.validate_skill(sk, **kwargs)
                self.assertEqual(sorted((f["code"], f["level"]) for f in found if f["code"] in ("FM4", "ST6", "MD1")),
                                 [("FM4", "ERROR"), ("ST6", "ERROR")], kwargs)

    def test_doctor_sensitive_named_reference_is_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = make_skill(Path(tmp), "refs")
            (sk / "references").mkdir()
            (sk / "references" / ".env.md").write_bytes(b"x\n" * 300)  # would be an ST5 ERROR if it were read
            (sk / "references" / "ok.md").write_bytes(b"short\n")
            self.assertEqual([f for f in studio_validate.validate_skill(sk) if f["code"] == "ST5"], [])
            self.assertTrue(studio_fs.is_sensitive_name(".env.local") and studio_fs.is_sensitive_name("Auth.JSON") and studio_fs.is_sensitive_name("x.credentials.json"))
            self.assertTrue(studio_fs.is_sensitive_name("a.pem") and studio_fs.is_sensitive_name("b.key"))
            self.assertFalse(studio_fs.is_sensitive_name("SKILL.md") or studio_fs.is_sensitive_name("environment.md"))

    def test_doctor_cli_subprocess_exit_codes(self):
        env = dict(os.environ, PYTHONUTF8="1")
        cmd = [sys.executable, "-X", "utf8", str(ROOT / "studio.py"), "doctor"]
        self.assertEqual(subprocess.run(cmd + ["--roots", str(ROOT / "examples" / "exemplar")], env=env, capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(cmd + ["--roots", str(FIX)], env=env, capture_output=True).returncode, 1)
        self.assertEqual(subprocess.run(cmd + ["--roots", str(ROOT / ".tmp" / "khong-co")], env=env, capture_output=True).returncode, 2)


CHILD = (
    "import sys, importlib.util, tempfile, time\n"
    "from pathlib import Path\n"
    "spec = importlib.util.spec_from_file_location('s', sys.argv[1]); s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)\n"
    "head = '---\\nname: bench\\ndescription: Bench. Use when benching.\\n%s---\\n\\n# T\\n\\n'\n"
    "vi = 'Xin chào các bạn. '\n"
    "cases = {\n"
    "  'brackets': ('[' * 100000, ''),\n"
    "  'comments': ('<!--' * 25000, ''),\n"
    "  'emptylinks': ('[](' * 33000, ''),\n"
    "  'meta': (vi * 30 + '\\n', 'metadata:\\n' + ''.join('  k%d: v\\n' % i for i in range(20000))),\n"
    "  'vi_lines': ('Xin chào.\\n' * 40000, ''),\n"
    "  'many_links': ('[x](a)\\n' * 60000, ''),\n"
    "  'one_line_links': ('[](a)' * 100000, ''),\n"
    "  'backticks': ('`' * 100000, ''),\n"
    "}\n"
    "body, extra = cases[sys.argv[2]]\n"
    "with tempfile.TemporaryDirectory() as t:\n"
    "    d = Path(t) / 'bench'; d.mkdir()\n"
    "    (d / 'SKILL.md').write_bytes((head % extra + body).encode('utf-8'))\n"
    "    start = time.perf_counter(); sys.modules['studio_validate'].validate_skill(d); print('%.3f' % (time.perf_counter() - start))\n"
)


class DoctorHardeningTests(unittest.TestCase):
    """SPR-33 TK9 round 2: the review of the first doctor found it could read what it must not (RK15) and be made to spin."""

    def test_doctor_skips_cloud_attribute_entries(self):
        for bit in (0x40000, 0x400000, 0x1000, 0x80000 | 0x400000, 0x100000):  # RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS, OFFLINE, PINNED|RECALL_ON_DATA_ACCESS, UNPINNED (PINNED alone is local: SPR-01 TK3)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve() / "root"
                ok = make_skill(root, "ok-skill")
                (ok / "references").mkdir()
                (ok / "references" / "placeholder.md").write_bytes(b"line\n" * 300)  # would be an ST5 ERROR if it were read
                (ok / "references" / "sub").mkdir()
                (ok / "references" / "sub" / "deep.md").write_bytes(b"line\n" * 300)
                make_skill(root / "KPIM Joint Stock Company", "trap-dir")
                make_skill(root, "trap-manifest")
                flags = {root / "KPIM Joint Stock Company": bit, root / "trap-manifest" / "SKILL.md": bit,
                         ok / "references" / "placeholder.md": bit, ok / "references" / "sub": bit}
                with mock.patch.object(studio_const, "CLOUD_ATTRS_AVAILABLE", True), cloud_flagged(flags), watching() as calls:
                    code, out, err = run("--roots", str(root), "--json")
                report = json.loads(out)
                self.assertEqual(code, 0, (hex(bit), out, err))
                self.assertEqual([s["name"] for s in report["skills"]], ["ok-skill"], hex(bit))
                reasons = {(Path(s["path"]).name, s["reason"]) for s in report["skipped"]}
                self.assertIn(("KPIM Joint Stock Company", "cloud"), reasons, hex(bit))
                self.assertIn(("trap-manifest", "cloud"), reasons, hex(bit))
                codes = [c["code"] for c in report["skills"][0]["codes"]]
                self.assertNotIn("ST5", codes, "a cloud placeholder reference must not be read")
                self.assertIn("SZ2", codes)
                for _, path, _ in calls:
                    low = path.replace("\\", "/").lower()
                    self.assertFalse(low.endswith(("trap-manifest/skill.md", "/placeholder.md", "/sub/deep.md", "/sub")), (hex(bit), path))
                    self.assertNotIn("/trap-dir", low, (hex(bit), path))

    def test_doctor_refuses_roots_that_are_too_broad(self):
        scans = []
        real_scandir = os.scandir

        def spy(path):
            scans.append(os.fspath(path))
            return real_scandir(path)

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "people" / "home"
            make_skill(home / "proj", "fine-skill")
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}), mock.patch.object(os, "scandir", spy):
                for broad in (home, home.parent, home.parent.parent, Path(home.anchor)):
                    code, out, err = run("--roots", str(broad), "--json")
                    self.assertEqual((code, out), (2, ""), str(broad))
                    self.assertIn("too broad", err, str(broad))
                listing = Path(tmp) / "roots.txt"
                listing.write_text("%s\n%s\n" % (home / "proj", home), encoding="utf-8")
                self.assertEqual(run("--roots-file", str(listing))[0], 2)
                self.assertEqual(run("--roots", "%s;%s" % (home / "proj", home))[0], 2)
                self.assertEqual(scans, [], "a refused run must not list anything")
                self.assertEqual(run("--roots", str(home / "proj"))[0], 0)
            if os.name == "nt":  # a drive that is not the home drive: only the "is a root" rule can refuse it
                with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                    self.assertTrue(studio_fs.root_too_broad("Z:\\") and studio_fs.root_too_broad("\\\\tk9-nohost.invalid\\share"))
                    self.assertFalse(studio_fs.root_too_broad("Z:\\work"))
            with mock.patch.object(os, "scandir", spy):
                scans.clear()
                self.assertEqual(run("--roots", str(Path.home()))[0], 2, "the real home folder is a root that is too broad")
                self.assertEqual(scans, [])

    def test_doctor_skip_marker_names_extra_cloud_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "root"
            make_skill(root, "ok-skill")
            make_skill(root / "Acme Sync Folder" / "team", "trap-one")
            make_skill(root / "other-share", "trap-two")
            plain = json.loads(run("--roots", str(root), "--json")[1])
            self.assertEqual(sorted(s["name"] for s in plain["skills"]), ["ok-skill", "trap-one", "trap-two"], "without a marker nothing is guessed")
            code, out, _ = run("--roots", str(root), "--json", "--skip-marker", "acme sync", "--skip-marker", "OTHER-share")
            report = json.loads(out)
            self.assertEqual((code, [s["name"] for s in report["skills"]]), (0, ["ok-skill"]))
            self.assertEqual({(Path(s["path"]).name, s["reason"]) for s in report["skipped"]}, {("Acme Sync Folder", "cloud"), ("other-share", "cloud")})
            with watching() as calls:
                run("--roots", str(root), "--json", "--skip-marker", "Acme Sync")
            self.assertFalse([p for _, p, _ in calls if "trap-one" in p or p.endswith("team")], "a marked folder is not entered")
            code, _, err = run("--roots", str(root), "--skip-marker", "  ")
            self.assertEqual(code, 2)
            self.assertIn("--skip-marker", err)
            code, out, _ = run("--roots", str(root / "Acme Sync Folder"), "--json", "--skip-marker", "acme sync")
            self.assertEqual((json.loads(out)["skills"], [s["reason"] for s in json.loads(out)["skipped"]]), ([], ["cloud"]), "a marked root is skipped whole")

    def test_doctor_does_not_follow_junctions_inside_a_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "home"
            secret = home / ".secret"
            secret.mkdir(parents=True)
            (secret / "CANARY-SECRET-NAME.md").write_bytes(b"line\n" * 300)
            (secret / "CANARY-SECRET-RUN.py").write_bytes(b"print(1)\n")
            sk = make_skill(home / "work", "linked-skill")
            (sk / "SKILL.md").write_bytes((sk / "SKILL.md").read_bytes() + b"\nRun [it](scripts/run.py).\n")
            make_dir_link(self, sk / "scripts", secret)
            make_dir_link(self, sk / "references", secret)
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}), watching() as calls:
                code, out, err = run("--roots", str(home / "work"), "--json")
            self.assertEqual(code, 1, (out, err))
            report = json.loads(out)
            self.assertNotIn("CANARY", out + err, "nothing from behind the junction may reach the report")
            sec = {c["file"] for s in report["skills"] for c in s["codes"] if c["code"] == "SEC"}
            self.assertTrue({"scripts", "references"} <= sec, sec)
            self.assertIn("ST6", {c["code"] for s in report["skills"] for c in s["codes"]}, "a link through a junction is refused, not resolved")
            for name, path, follow in calls:
                for link in (sk / "scripts", sk / "references"):
                    if is_under(path, link):
                        self.assertTrue(norm(path) == norm(link) and name == "lstat" or (name == "stat" and not follow and norm(path) == norm(link)),
                                        "%s touched %s" % (name, path))
                self.assertNotIn(".secret", path.lower(), "%s reached the secret folder: %s" % (name, path))

    def test_doctor_never_opens_unc_or_absolute_links(self):
        links = ["//tk9-nohost.invalid/share/a.md", "\\\\tk9-nohost.invalid\\share\\b.md", "file://tk9-nohost.invalid/c.md",
                 "smb://tk9-nohost.invalid/d.md", "C:/tk9-absolute/e.md", "/tk9-absolute/f.md"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "root"
            sk = make_skill(root, "linker")
            (sk / "SKILL.md").write_bytes((sk / "SKILL.md").read_bytes() + b"\n" + b"\n".join(b"See [x](%s)." % x.encode() for x in links) + b"\n")
            for extra in ([], ["--profile", "opcos"]):
                with watching() as calls:
                    code, out, err = run("--roots", str(root), "--json", *extra)
                self.assertEqual(code, 1, (extra, out, err))
                st6 = [c for s in json.loads(out)["skills"] for c in s["codes"] if c["code"] == "ST6"]
                self.assertEqual([c["level"] for c in st6], ["ERROR"] * len(links), extra)
                self.assertTrue(all("not opened" in c["message"] for c in st6), st6)
                for name, path, _ in calls:
                    low = path.replace("\\", "/").lower()
                    self.assertNotIn("tk9-nohost", low, (extra, name, path))
                    self.assertNotIn("tk9-absolute", low, (extra, name, path))
            code, out, _ = run("--roots", str(root), "--json", "--profile", "opcos")
            plain = studio_validate.validate_skill(sk, profile="opcos", allow_links_under=root)
            self.assertEqual(len([f for f in plain if f["code"] == "ST6"]), len(links), "an absolute link is an ERROR even where the scanned root would allow a link")

    def test_doctor_does_not_echo_secret_file_content(self):
        canary = "CANARY-TOKEN-9f3a"
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            dotenv = tmp / ".env"
            dotenv.write_text("API_KEY=%s\n" % canary, encoding="utf-8")
            auth = tmp / "auth.json"
            auth.write_text('{"token": "%s"}' % canary, encoding="utf-8")
            for argv in (["--roots-file", str(dotenv)], ["--baseline", str(dotenv)], ["--baseline", str(auth)],
                         ["--roots", CLEAN_ROOTS, "--baseline", str(dotenv)], ["--roots-file", str(tmp / "x.credentials.json")]):
                with watching() as calls:
                    code, out, err = run(*argv)
                self.assertEqual(code, 2, argv)
                self.assertNotIn(canary, out + err, argv)
                self.assertFalse([p for _, p, _ in calls if p.endswith((".env", "auth.json", "x.credentials.json"))], ("opened", argv))
            listing = tmp / "roots.txt"
            listing.write_text("# comment\n%s\n" % canary, encoding="utf-8")
            code, out, err = run("--roots-file", str(listing))
            self.assertEqual(code, 2)
            self.assertNotIn(canary, out + err, "the message names the line number, not the line")
            self.assertRegex(err, r"line 2")
            binary = tmp / "roots.bin"
            binary.write_bytes(b"\x97" + canary.encode())
            code, out, err = run("--roots-file", str(binary))
            self.assertEqual(code, 2)
            self.assertNotIn(canary, out + err)

    def test_doctor_out_refuses_sensitive_names_and_foreign_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            keep = {}
            for name in (".env", ".env.local", "auth.json", "server.pem", "id.key", "x.credentials.json", "notes.txt", "README.md"):
                keep[name] = tmp / name
                keep[name].write_bytes(b"KEEP-ME")
            for name, path in keep.items():
                code, _, err = run("--roots", CLEAN_ROOTS, "--out", str(path))
                self.assertEqual(code, 2, name)
                self.assertEqual(path.read_bytes(), b"KEEP-ME", "%s was overwritten" % name)
            old = tmp / "old-report.json"
            self.assertEqual(run("--roots", CLEAN_ROOTS, "--out", str(old))[0], 0)
            self.assertEqual(run("--roots", CLEAN_ROOTS, "--out", str(old))[0], 0)
            self.assertEqual(json.loads(old.read_text(encoding="utf-8"))["schema"], 1, "an earlier .json report may be replaced")
            self.assertEqual(run("--roots", CLEAN_ROOTS, "--out", str(tmp / "fresh.txt"))[0], 0, "a new file may have any name")

    def test_doctor_out_may_sit_under_a_folder_the_scan_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp).resolve() / "plugins"
            make_skill(plugins / "studio" / "skills", "x")
            make_skill(plugins, "solo")
            for sub in (("studio", ".worktrees", "spr", ".tmp"), ("studio", ".tmp"), ("keep-cache",), ("other",)):
                (plugins.joinpath(*sub)).mkdir(parents=True)
            fine = plugins / "studio" / ".worktrees" / "spr" / ".tmp" / "x.json"
            self.assertEqual(run("--roots", str(plugins), "--out", str(fine))[0], 0)
            self.assertTrue(fine.is_file())
            self.assertEqual(run("--roots", str(plugins), "--out", str(plugins / "studio" / ".tmp" / "x.json"))[0], 0)
            self.assertEqual(run("--roots", str(plugins), "--out", str(plugins / "keep-cache" / "x.json"))[0], 0)
            for bad in (plugins / "studio" / "skills" / "x" / "r.json", plugins / "other" / "r.json", plugins / "solo" / "r.json"):
                code, _, err = run("--roots", str(plugins), "--out", str(bad))
                self.assertEqual(code, 2, str(bad))
                self.assertFalse(bad.exists(), str(bad))
            (plugins / "solo" / ".tmp").mkdir()
            self.assertEqual(run("--roots", str(plugins), "--out", str(plugins / "solo" / ".tmp" / "r.json"))[0], 2, "still inside a skill that is scanned")
            self.assertEqual(run("--roots", str(plugins), "--include-cache", "--out", str(plugins / "keep-cache" / "y.json"))[0], 2, "--include-cache scans that folder")

    def test_doctor_out_through_a_link_into_the_secret_zone_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            home = tmp / "home"
            (home / ".secret").mkdir(parents=True)
            make_dir_link(self, tmp / "innocent", home / ".secret")
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                code, _, err = run("--roots", CLEAN_ROOTS, "--out", str(tmp / "innocent" / "r.json"))
            self.assertEqual(code, 2, err)
            self.assertEqual(list((home / ".secret").iterdir()), [], "nothing may be written into the secret folder")

    def test_doctor_size_cap_skips_oversized_files(self):
        cap = 2000
        with mock.patch.object(studio_const, "DOCTOR_MAX_FILE_BYTES", cap), tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "root"
            big_ref = make_skill(root, "big-ref")
            (big_ref / "references").mkdir()
            (big_ref / "references" / "BIG.md").write_bytes(b"line\n" * 1000)  # 5000 B: ST5 if it were read
            (big_ref / "references" / "small.md").write_bytes(b"ok\n")
            big_manifest = make_skill(root, "big-manifest")
            (big_manifest / "SKILL.md").write_bytes((big_manifest / "SKILL.md").read_bytes() + b"padding line\n" * 400)
            reads = []
            real_open = builtins.open

            class Proxy:
                def __init__(self, handle, path):
                    self._h, self._p = handle, path

                def __getattr__(self, name):
                    return getattr(self._h, name)

                def __enter__(self):
                    self._h.__enter__()
                    return self

                def __exit__(self, *exc):
                    return self._h.__exit__(*exc)

                def read(self, size=-1, *a):
                    reads.append((self._p, size))
                    return self._h.read(size, *a)

            def spy(path, *a, **k):
                handle = real_open(path, *a, **k)
                return Proxy(handle, os.fspath(path)) if isinstance(path, (str, os.PathLike)) and os.fspath(path).endswith(("BIG.md", "SKILL.md")) else handle

            real_safe_open = _engine.fs.open_nofollow_read  # SPR-05 TK1: read_capped now opens through open_nofollow_read, so that is where the read is spied

            def safe_spy(path, *a, **k):
                handle = real_safe_open(path, *a, **k)
                return Proxy(handle, os.fspath(path)) if os.fspath(path).endswith(("BIG.md", "SKILL.md")) else handle

            with mock.patch.object(builtins, "open", spy), mock.patch.object(io, "open", spy), mock.patch.object(_engine.fs, "open_nofollow_read", safe_spy):
                code, out, err = run("--roots", str(root), "--json")
            report = json.loads(out)
            self.assertEqual(code, 1, (out, err))  # SPR-01 TK6: an unread SKILL.md is an SZ1 ERROR
            by_name = {s["name"]: s for s in report["skills"]}
            ref_codes = [(c["code"], c["level"], c["file"]) for c in by_name["big-ref"]["codes"]]
            self.assertIn(("SZ1", "WARN", "references/BIG.md"), ref_codes)
            self.assertNotIn("ST5", [c[0] for c in ref_codes])
            man_codes = [(c["code"], c["level"], c["file"]) for c in by_name["big-manifest"]["codes"]]
            self.assertEqual(man_codes, [("SZ1", "ERROR", "SKILL.md")], "an oversized SKILL.md is not linted")
            limited = {Path(s["path"]).name for s in report["skipped"] if s["reason"] == "limit"}
            self.assertEqual(limited, {"BIG.md", "SKILL.md"})
            big_reads = [(p, n) for p, n in reads if p.endswith("BIG.md") or "big-manifest" in p]
            self.assertTrue(big_reads)
            for path, size in big_reads:
                self.assertTrue(isinstance(size, int) and 0 < size <= cap + 1, "read(%r) on %s would load the whole file" % (size, path))
            # without a cap (plain validate) behaviour is unchanged
            self.assertIn("ST5", [f["code"] for f in studio_validate.validate_skill(big_ref)])

    def test_validate_skill_is_fast_on_hostile_bodies(self):
        for case in ("brackets", "comments", "emptylinks", "meta", "vi_lines", "many_links", "one_line_links", "backticks"):
            try:
                done = subprocess.run([sys.executable, "-X", "utf8", "-c", CHILD, str(_engine.ENGINE_PATH), case], capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                self.fail("%s: validate_skill still running after 30 s" % case)
            self.assertEqual(done.returncode, 0, (case, done.stderr[-300:]))
            self.assertLess(float(done.stdout.strip()), 5.0, "%s took %s s" % (case, done.stdout.strip()))

    def test_strip_html_comments_matches_the_regex_it_replaced(self):
        import random
        import re
        rng = random.Random(7)
        pieces = ["<!--", "-->", "x", " ", "\n", "-", ">", "!", "<", "--"]
        for _ in range(4000):
            sample = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 14)))
            self.assertEqual(studio_fs.strip_html_comments(sample), re.sub(r"<!--.*?-->", " ", sample), repr(sample))
            self.assertEqual(studio_fs.strip_html_comments(sample, "#"), re.sub(r"<!--.*?-->", "#", sample), repr(sample))

    def test_zone_reason_secret_branches(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            (tmp / "real" / "home").mkdir(parents=True)
            alias = tmp / "alias"
            make_dir_link(self, alias, tmp / "real" / "home")
            _engine.clear_caches()
            with mock.patch.dict(os.environ, {"HOME": str(alias), "USERPROFILE": str(alias)}):
                try:
                    self.assertEqual(studio_fs.zone_reason(tmp / "elsewhere" / ".secret" / "k.json"), "secret-zone", "a .secret folder outside HOME")
                    self.assertEqual(studio_fs.zone_reason(tmp / "elsewhere" / ".SECRET" / "k.json"), "secret-zone", "case does not matter on any platform")
                    self.assertEqual(studio_fs.zone_reason(alias / ".secret" / "k.json"), "secret-zone", "HOME spelled through the link")
                    self.assertEqual(studio_fs.zone_reason(tmp / "real" / "home" / ".secret"), "secret-zone", "HOME spelled by its real path")
                    self.assertIsNone(studio_fs.zone_reason(tmp / "real" / "home" / "work"))
                finally:
                    _engine.clear_caches()

    def test_doctor_st3_counts_bytes_not_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = make_skill(Path(tmp), "wide-body")
            (sk / "SKILL.md").write_bytes((sk / "SKILL.md").read_bytes() + ("é" * 5000).encode("utf-8"))  # ~5 000 characters, ~10 000 bytes
            self.assertEqual([f["level"] for f in studio_validate.validate_skill(sk) if f["code"] == "ST3"], ["WARN"])
            narrow = make_skill(Path(tmp), "narrow-body")
            (narrow / "SKILL.md").write_bytes((narrow / "SKILL.md").read_bytes() + b"x" * 7000)
            self.assertEqual([f for f in studio_validate.validate_skill(narrow) if f["code"] == "ST3"], [])



CHILD3 = (
    "import sys, importlib.util, tempfile, time, io, contextlib\n"
    "from pathlib import Path\n"
    "spec = importlib.util.spec_from_file_location('s', sys.argv[1]); s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)\n"
    "bodies = {'run': 'x' + '`' * 20000, 'run30': 'x' + '`' * 30000, 'alt': '`a' * 20000, 'pairs': '`` `' * 10000, 'triples': '``` ' * 8000}\n"
    "body = bodies[sys.argv[2]]\n"
    "head = '---\\nname: bench\\ndescription: Bench. Use when benching.\\n---\\n\\n# T\\n\\n'\n"
    "t0 = time.perf_counter(); sys.modules['studio_lint'].lint_forcing_words(body, 0, Path('m')); a = time.perf_counter() - t0\n"
    "t0 = time.perf_counter(); sys.modules['studio_lint'].prose_lines(body); b = time.perf_counter() - t0\n"
    "with tempfile.TemporaryDirectory() as t:\n"
    "    d = Path(t) / 'bench'; d.mkdir(); (d / 'SKILL.md').write_bytes((head + body).encode('utf-8'))\n"
    "    t0 = time.perf_counter(); sys.modules['studio_validate'].validate_skill(d); c = time.perf_counter() - t0\n"
    "    out = io.StringIO(); t0 = time.perf_counter()\n"
    "    with contextlib.redirect_stdout(out): s.main(['doctor', '--roots', t, '--json'])\n"
    "    e = time.perf_counter() - t0\n"
    "print('%.3f %.3f %.3f %.3f' % (a, b, c, e))\n"
)


def short_name(path: Path):
    """The 8.3 spelling of an existing path on Windows, else None."""
    if os.name != "nt":
        return None
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 1024)
    return Path(buf.value) if n and buf.value and norm(buf.value) != norm(path) else None


class DoctorRound3Tests(unittest.TestCase):
    """SPR-33 TK9 round 3 (security review of round 2): a backtick run made CODE_SPAN_RE cubic; roots, inputs and --out were checked by spelling only."""

    def test_code_span_strip_matches_the_regex_it_replaced(self):
        import random
        import re
        old = re.compile(r"(`+).+?\1")
        rng = random.Random(33)
        pieces = ["`", "`", "``", "```", "a", "b c", " ", "x", "\n", "`` ", "~"]
        different = []
        for _ in range(24000):
            sample = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 16)))
            for repl in (" ", "#"):
                if studio_fs.strip_code_spans(sample, repl) != old.sub(repl, sample):
                    different.append(sample)
        self.assertEqual(different[:5], [], "%d samples differ from the old regex" % len(different))
        self.assertEqual(studio_fs.strip_code_spans("a `b` c ``d`e`` f"), "a   c   f")
        self.assertEqual(studio_fs.strip_code_spans("no code here"), "no code here")

    def test_hostile_backtick_bodies_finish_fast(self):
        for case in ("run", "alt", "pairs", "triples", "run30"):
            try:
                done = subprocess.run([sys.executable, "-X", "utf8", "-c", CHILD3, str(_engine.ENGINE_PATH), case], capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                self.fail("%s: still running after 60 s (lint_forcing_words, prose_lines, validate_skill and doctor each get a backtick run)" % case)
            self.assertEqual(done.returncode, 0, (case, done.stderr[-300:]))
            times = [float(x) for x in done.stdout.split()]
            self.assertEqual(len(times), 4, done.stdout)
            self.assertLess(max(times), 5.0, "%s took %s s (lint, prose, validate, doctor)" % (case, done.stdout.strip()))

    def test_every_regex_in_studio_is_linear_on_hostile_text(self):
        import ast
        import re
        import time
        tree = ast.parse(_engine.engine_source())
        patterns = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "re" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                patterns.setdefault(node.args[0].value, 0)
        self.assertGreater(len(patterns), 25)
        units = ["`", "[", "(", "<", "<!--", "*", "_", "|", "-", " ", "\n", "#", ":", '"', "'", "\\", "a", "]", ")", "[](", "http://"]
        size, slow = 8000, []
        for pattern in patterns:
            try:
                rx = re.compile(pattern, re.IGNORECASE)
            except re.error:
                continue
            for unit in units:
                for text in (unit * (size // len(unit)), "x" + unit * (size // len(unit)), (unit + "a") * (size // (len(unit) + 1)), unit * (size // len(unit)) + "x"):
                    start = time.perf_counter()
                    list(rx.finditer(text))
                    rx.match(text)
                    rx.fullmatch(text)
                    rx.search(text)
                    took = time.perf_counter() - start
                    if took > 1.0:
                        slow.append((pattern, unit, round(took, 2)))
        self.assertEqual(slow, [], "regex(es) over 1 s on %d characters" % size)

    def test_xml_tag_check_matches_the_regex_it_replaced(self):
        import random
        import re
        rng = random.Random(5)
        for _ in range(8000):
            sample = "".join(rng.choice("<>a <") for _ in range(rng.randint(0, 12)))
            self.assertEqual(studio_fs.has_xml_tag(sample), bool(re.search(r"<[^>]+>", sample)), repr(sample))
        start = __import__("time").perf_counter()
        studio_fs.has_xml_tag("<" * 100000)
        studio_fs.has_xml_tag("<>" * 100000)
        self.assertLess(__import__("time").perf_counter() - start, 1.0)
        start = __import__("time").perf_counter()
        studio_const.ABSOLUTE_LINK_RE.search("a" * 100000)
        studio_const.ABSOLUTE_LINK_RE.match("a" * 100000)
        self.assertLess(__import__("time").perf_counter() - start, 1.0, "a scheme-looking run of letters must not be quadratic")

    def test_root_too_broad_looks_through_links_and_short_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            home = tmp / "people" / "a-rather-long-home-folder-name"
            make_skill(home / "proj", "fine-skill")
            up = tmp / "up-alias"
            make_dir_link(self, up, home.parent)
            alias = tmp / "home-alias"
            make_dir_link(self, alias, home)
            scans = []
            real_scandir = os.scandir

            def spy(path):
                scans.append(os.fspath(path))
                return real_scandir(path)

            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}), mock.patch.object(os, "scandir", spy):
                self.assertTrue(studio_fs.root_too_broad(alias) and studio_fs.root_too_broad(up))
                for broad in (alias, up, alias / "..", alias / "proj" / ".."):
                    self.assertEqual(run("--roots", str(broad), "--json")[0], 2, str(broad))
                self.assertEqual(scans, [], "a refused run must not list anything")
                if os.name == "nt":
                    self.assertTrue(studio_fs.root_too_broad("\\\\?\\" + str(home)))
                    self.assertEqual(run("--roots", "\\\\?\\" + str(home))[0], 2)
                    spelled = short_name(home)
                    if spelled is None:
                        self.skipTest("8.3 names are off on this volume")
                    self.assertTrue(studio_fs.root_too_broad(spelled))
                    self.assertEqual(run("--roots", str(spelled))[0], 2)
                    with mock.patch.dict(os.environ, {"HOME": str(spelled), "USERPROFILE": str(spelled)}):
                        self.assertEqual(run("--roots", str(home))[0], 2, "HOME in its short spelling, root in the long one")
                    self.assertEqual(scans, [])
                self.assertEqual(run("--roots", str(home / "proj"))[0], 0)

    def test_iter_skill_dirs_checks_cloud_attributes_on_the_real_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            real = tmp / "plain-name"
            make_skill(real, "hidden-skill")
            alias = tmp / "alias"
            make_dir_link(self, alias, real)
            with mock.patch.object(studio_fs, "path_is_cloud", lambda p: norm(p) == norm(real)), watching() as calls:
                skills, skipped = studio_doctor.iter_skill_dirs([alias])
            self.assertEqual(skills, [])
            self.assertEqual([s["reason"] for s in skipped], ["cloud"])
            self.assertFalse([p for n, p, _ in calls if n in ("scandir", "listdir") and is_under(p, real)], "the placeholder folder must not be listed")

    def test_roots_file_and_baseline_are_resolved_before_they_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            home = tmp / "home"
            secret = home / ".secret"
            secret.mkdir(parents=True)
            (secret / "roots.txt").write_text("%s\n# CANARY-ROOTS\n" % FIX, encoding="utf-8")
            (secret / "base.json").write_text('{"schema": 1, "skills": [], "x": "CANARY-BASE"}', encoding="utf-8")
            door = tmp / "innocent"
            make_dir_link(self, door, secret)
            cases = [(["--roots-file", str(door / "roots.txt")], "roots.txt"), (["--roots", CLEAN_ROOTS, "--baseline", str(door / "base.json")], "base.json")]
            short = short_name(secret)
            if short is not None:
                cases += [(["--roots-file", str(short / "roots.txt")], "roots.txt"), (["--roots", CLEAN_ROOTS, "--baseline", str(short / "base.json")], "base.json")]
            if os.name == "nt":
                plain = tmp / "plain.txt"
                plain.write_text("%s\n" % FIX, encoding="utf-8")
                cases += [(["--roots-file", str(plain) + "::$DATA"], "$DATA"), (["--roots-file", str(plain) + ":evil"], ":evil"),
                          (["--roots", CLEAN_ROOTS, "--baseline", str(plain) + "::$DATA"], "$DATA")]
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                for argv, tail in cases:
                    with watching() as calls:
                        code, out, err = run(*argv)
                    self.assertEqual(code, 2, (argv, out, err))
                    self.assertNotIn("CANARY", out + err, argv)
                    self.assertFalse([p for n, p, _ in calls if n == "open" and p.endswith(tail)], ("opened", argv))

    def test_doctor_out_overwrites_only_its_own_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            keep = {}
            for name, content in (("secrets.json", b'{"token": "CANARY-OUT"}'), (".claude.json", b'{"oauth": "CANARY-OUT"}'), ("package.json", b"{}"),
                                  ("UPPER.JSON", b'{"a": 1}'), ("notes.json", b"[1, 2]"), ("binary.json", b"\x97\x98\x99")):
                keep[name] = (tmp / name, content)
                (tmp / name).write_bytes(content)
            for name, (path, content) in keep.items():
                code, out, err = run("--roots", CLEAN_ROOTS, "--out", str(path))
                self.assertEqual(code, 2, (name, err))
                self.assertEqual(path.read_bytes(), content, "%s was overwritten" % name)
                self.assertNotIn("CANARY", out + err)
            report = tmp / "report.json"
            self.assertEqual(run("--roots", CLEAN_ROOTS, "--out", str(report))[0], 0)
            self.assertEqual(run("--roots", CLEAN_ROOTS, "--out", str(report))[0], 0, "a report doctor wrote may be replaced")
            compact = tmp / "compact.json"
            compact.write_bytes(b'{"schema":1,"skills":[]}')
            self.assertEqual(run("--roots", CLEAN_ROOTS, "--out", str(compact))[0], 0, "a report that starts with the schema key may be replaced")
            empty = tmp / "empty.json"
            empty.write_bytes(b"")
            self.assertEqual(run("--roots", CLEAN_ROOTS, "--out", str(empty))[0], 0, "an empty file holds nothing to lose")
            if os.name == "nt":
                for spelled in (str(tmp / "stream.json") + ":evil", str(tmp / "stream.json") + "::$DATA", str(report) + ":evil"):
                    code, _, err = run("--roots", CLEAN_ROOTS, "--out", spelled)
                    self.assertEqual(code, 2, spelled)
                    self.assertFalse((tmp / "stream.json").exists(), "no stream may be created")

    def test_walk_files_stops_at_a_file_and_depth_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = make_skill(Path(tmp), "wide-skill")
            (sk / "references").mkdir()
            for i in range(120):
                (sk / "references" / ("r%03d.md" % i)).write_bytes(b"x\n")
            deep = sk / "assets"
            for level in range(8):
                deep = deep / ("d%d" % level)
            deep.mkdir(parents=True)
            (deep / "bottom.txt").write_bytes(b"x")
            with mock.patch.object(studio_const, "DOCTOR_MAX_FILES_PER_SKILL", 50), watching() as calls:
                found = studio_validate.validate_skill(sk)
            self.assertIn("SZ1", [f["code"] for f in found])
            self.assertTrue([f for f in found if f["code"] == "SZ1" and "50" in f["message"]])
            listed = [p for n, p, _ in calls if n == "scandir" and is_under(p, sk / "references")]
            self.assertLessEqual(len(listed), 2)
            with mock.patch.object(studio_const, "DOCTOR_MAX_SKILL_DEPTH", 3), watching() as calls:
                found = studio_validate.validate_skill(sk)
            self.assertIn("SZ1", [f["code"] for f in found])
            self.assertFalse([p for n, p, _ in calls if n == "scandir" and p.endswith("d5")], "a folder below the depth cap is not listed")
            quiet = studio_validate.validate_skill(sk)
            self.assertNotIn("SZ1", [f["code"] for f in quiet], "default caps are far above this skill")

    def test_input_file_that_resolves_to_a_secret_name_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            plain = tmp / "notes.txt"
            self.assertIsNone(studio_fs.input_file_problem(plain))
            with mock.patch.object(Path, "resolve", lambda self, strict=False: tmp / ".env"):
                self.assertIn("secret-looking", studio_fs.input_file_problem(plain))


class DoctorRound4Tests(unittest.TestCase):
    """SPR-33 TK9 round 4 (RF-A, RF-B): every name/zone/cloud check on --out comes before any stat or open; device namespaces are not roots."""

    def _touched(self, calls, names):
        return [(n, p) for n, p, _ in calls if n in ("open", "stat", "lstat", "access", "scandir", "listdir") and os.path.basename(p).lower() in names]

    def test_doctor_out_checks_names_and_zones_before_touching_the_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            home = tmp / "home"
            secret = home / ".secret"
            secret.mkdir(parents=True)
            cloud = tmp / "OneDrive - Fake"
            cloud.mkdir()
            door_secret, door_cloud = tmp / "door-secret", tmp / "door-cloud"
            make_dir_link(self, door_secret, secret)
            make_dir_link(self, door_cloud, cloud)
            cases = [(door_secret / "canary.json", "canary.json", secret / "canary.json"),
                     (door_cloud / "report.json", "report.json", cloud / "report.json")]
            short = short_name(secret)
            if short is not None:
                cases.append((short / "canary.json", "canary.json", secret / "canary.json"))
            contents = (b"", b'{"schema": 1, "skills": []}', b"CANARY-OUT plain text", b'{"token": "CANARY-OUT"}')
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                for out, name, real in cases:
                    messages = set()
                    for content in contents:
                        real.write_bytes(content)
                        with watching() as calls:
                            code, stdout, err = run("--roots", CLEAN_ROOTS, "--out", str(out))
                        self.assertEqual(code, 2, (str(out), err))
                        self.assertEqual(real.read_bytes(), content, "the file behind the link was changed")
                        self.assertNotIn("CANARY", stdout + err)
                        self.assertEqual(self._touched(calls, {name}), [], ("the target was touched before the zone check", str(out), content))
                        messages.add(err)
                    self.assertEqual(len(messages), 1, ("the refusal depends on the file content", messages))

    def test_doctor_out_cloud_placeholder_is_refused_before_it_is_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            old = tmp / "old.json"
            old.write_bytes(b'{"schema": 1, "skills": []}')
            for flagged in (old, tmp):
                with mock.patch.object(studio_fs, "path_is_cloud", lambda p, flagged=flagged: norm(p) == norm(flagged)), watching() as calls:
                    code, _, err = run("--roots", CLEAN_ROOTS, "--out", str(old))
                self.assertEqual(code, 2, (str(flagged), err))
                self.assertIn("cloud", err)
                self.assertEqual([x for x in self._touched(calls, {"old.json"}) if x[0] == "open"], [], str(flagged))
            self.assertEqual(old.read_bytes(), b'{"schema": 1, "skills": []}')

    def test_doctor_out_still_replaces_its_own_old_report_and_empty_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            for content in (b"", b'{"schema": 1, "skills": []}', b'  \n{"schema":1}'):
                target = tmp / "r.json"
                target.write_bytes(content)
                code, _, err = run("--roots", CLEAN_ROOTS, "--out", str(target))
                self.assertEqual(code, 0, (content, err))
                self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["schema"], 1)

    def test_root_too_broad_refuses_device_namespaces_and_admin_shares(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            home = tmp / "people" / "a-rather-long-home-folder-name"
            make_skill(home / "proj", "fine-skill")
            drive, rest = os.path.splitdrive(str(home))
            drive = drive or "C:"
            guid = "{12345678-1234-1234-1234-123456789abc}"
            hostile = ["\\\\.\\" + str(home), "\\\\.\\" + drive, "\\\\localhost\\C$" + rest, "\\\\localhost\\C$", "\\\\127.0.0.1\\D$\\Users",
                       "\\\\?\\UNC\\localhost\\C$" + rest, "\\\\?\\UNC\\server\\ADMIN$",
                       "\\\\?\\GLOBALROOT\\Device\\HarddiskVolume3" + rest, "\\\\?\\Volume" + guid + "\\", "\\\\?\\Volume" + guid + rest,
                       "//./" + drive + rest.replace("\\", "/"), "//?/Volume" + guid + "/", "\\\\?\\x"]
            scans = []
            real_scandir = os.scandir

            def spy(path):
                scans.append(os.fspath(path))
                return real_scandir(path)

            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}), mock.patch.object(os, "scandir", spy):
                for text in hostile:
                    self.assertTrue(studio_fs.root_too_broad(text), text)
                    code, _, err = run("--roots", text, "--json")
                    self.assertEqual(code, 2, (text, err))
                self.assertEqual(scans, [], "a refused run must not list anything")
                self.assertFalse(studio_fs.root_too_broad("\\\\server\\share\\skills"), "an ordinary share is not refused by name")
                self.assertFalse(studio_fs.root_too_broad("\\\\?\\UNC\\server\\share\\skills"))
                self.assertEqual(run("--roots", str(home / "proj"))[0], 0)
                if os.name == "nt":
                    self.assertEqual(run("--roots", "\\\\?\\" + str(home / "proj"))[0], 0, "a drive-letter extended path is still accepted")

    def test_input_file_problem_checks_cloud_on_the_real_path_and_all_secret_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            real = tmp / "real"
            real.mkdir()
            (real / "notes.txt").write_text("x", encoding="utf-8")
            alias = tmp / "alias"
            make_dir_link(self, alias, real)
            with mock.patch.object(studio_fs, "path_is_cloud", lambda p: norm(p) == norm(real / "notes.txt")):
                self.assertIn("cloud", studio_fs.input_file_problem(alias / "notes.txt") or "")
            self.assertIsNone(studio_fs.input_file_problem(alias / "notes.txt"))
            for name in ("secrets.json", "Credentials.json", "id_rsa", "id_ed25519", ".env", "x.pem"):
                self.assertIn("secret-looking", studio_fs.input_file_problem(tmp / name) or "", name)
            self.assertIsNone(studio_fs.input_file_problem(tmp / "roots.txt"))


class DoctorRq029Tests(unittest.TestCase):
    """SPR-04 TK2 (FR11.3, RQ-029): a skill whose SKILL.md was refused (INPUT) is not opened again for its name."""

    def test_rq029_identity_does_not_reread_a_skill_with_input(self):
        """bắt-lỗi (red at c3deee2: `_skill_identity` opens SKILL.md after validate said INPUT): FR11.3 the entry's name is the folder name and no read reaches SKILL.md."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            skill = make_skill(tmp / "root", "folder-name")
            (skill / "SKILL.md").write_bytes((SKILL % ("name-in-file", "")).encode("utf-8"))
            refused = [studio_fs.emit("ERROR", "INPUT", skill / "SKILL.md", 0, "SKILL.md is inside a cloud zone; not read")]
            reads, real = [], studio_fs.read_capped

            def spy(path, *a, **k):
                reads.append(os.fspath(path))
                return real(path, *a, **k)

            with mock.patch.object(studio_validate, "validate_skill", return_value=refused), mock.patch.object(studio_fs, "read_capped", spy):
                report = studio_doctor.doctor_run([tmp / "root"], "opcos", "portable", False, None)
            self.assertEqual(["folder-name"], [s["name"] for s in report["skills"]])
            self.assertEqual([], [r for r in reads if r.endswith("SKILL.md")], "SKILL.md was opened for the name")


if __name__ == "__main__":
    unittest.main()
