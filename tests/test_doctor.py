"""SPR-33 TK9: `studio.py doctor` v1, report-only scan of many skill roots (SPEC 9.11, FR17, SC10)."""
import builtins
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "doctor"
CLEAN_ROOTS = ";".join(str(ROOT / x) for x in ("skills", "content/exemplar", "content/exemplar-vi"))
SPEC = importlib.util.spec_from_file_location("studio_doctor_impl", ROOT / "studio.py")
studio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(studio)

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
                code, out, _ = run("--roots", ";".join(map(str, (home, home / ".secret", trap_cloud, absent_cloud))), "--json")
            report = json.loads(out)
            self.assertEqual(code, 0, out)
            self.assertEqual([s["name"] for s in report["skills"]], ["fine-skill"])
            reasons = {(Path(s["path"]).name, s["reason"]) for s in report["skipped"]}
            self.assertIn((".secret", "secret-zone"), reasons)
            self.assertIn(("OneDrive - X", "cloud"), reasons)
            self.assertIn(("OneDrive - Y", "cloud"), reasons)
            self.assertIn(("SharePoint-site", "cloud"), reasons)
            for hidden in ("trap-secret", "trap-cloud", "trap-share"):
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
            found = [f for f in studio.validate_skill(sk) if f["code"] == "ST8"]
            self.assertEqual([f["level"] for f in found], ["WARN"])
            self.assertIn("examples", found[0]["message"])
            self.assertEqual(len([f for f in studio.validate_skill(sk, profile="opcos") if f["code"] == "ST8"]), 1)
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
            fill = studio.CODEX_BODY_MAX_BYTES - len(head[body_start:])
            (sk / "SKILL.md").write_bytes(head + b"x" * fill)
            self.assertEqual([f for f in studio.validate_skill(sk) if f["code"] == "ST3"], [], "exactly the limit is allowed")
            (sk / "SKILL.md").write_bytes(head + b"x" * (fill + 1))
            found = [f for f in studio.validate_skill(sk) if f["code"] == "ST3"]
            self.assertEqual([f["level"] for f in found], ["WARN"])

    def test_doctor_writes_only_out(self):
        before = snapshot(FIX)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            code, stdout, _ = run("--roots", str(FIX), "--json", "--out", str(out))
            self.assertEqual(code, 1)
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
        self.assertEqual(report["studio_version"], studio.VERSION)
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
            with mock.patch.object(studio, "DOCTOR_MAX_DEPTH", 2):
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
                found = [f for f in studio.validate_skill(sk, profile="opcos", allow_links_under=home) if f["code"] == "ST6"]
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
                found = studio.validate_skill(sk, **kwargs)
                self.assertEqual(sorted((f["code"], f["level"]) for f in found if f["code"] in ("FM4", "ST6", "MD1")),
                                 [("FM4", "ERROR"), ("ST6", "ERROR")], kwargs)

    def test_doctor_sensitive_named_reference_is_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = make_skill(Path(tmp), "refs")
            (sk / "references").mkdir()
            (sk / "references" / ".env.md").write_bytes(b"x\n" * 300)  # would be an ST5 ERROR if it were read
            (sk / "references" / "ok.md").write_bytes(b"short\n")
            self.assertEqual([f for f in studio.validate_skill(sk) if f["code"] == "ST5"], [])
            self.assertTrue(studio.is_sensitive_name(".env.local") and studio.is_sensitive_name("Auth.JSON") and studio.is_sensitive_name("x.credentials.json"))
            self.assertTrue(studio.is_sensitive_name("a.pem") and studio.is_sensitive_name("b.key"))
            self.assertFalse(studio.is_sensitive_name("SKILL.md") or studio.is_sensitive_name("environment.md"))

    def test_doctor_cli_subprocess_exit_codes(self):
        env = dict(os.environ, PYTHONUTF8="1")
        cmd = [sys.executable, "-X", "utf8", str(ROOT / "studio.py"), "doctor"]
        self.assertEqual(subprocess.run(cmd + ["--roots", str(ROOT / "content" / "exemplar")], env=env, capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(cmd + ["--roots", str(FIX)], env=env, capture_output=True).returncode, 1)
        self.assertEqual(subprocess.run(cmd + ["--roots", str(ROOT / ".tmp" / "khong-co")], env=env, capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
