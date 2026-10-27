"""Offline tests for Studio manifest, CLI, package and install.

Run: python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "skills" / "skill-creator-studio" / "scripts" / "studio.py"
SPEC = importlib.util.spec_from_file_location("studio_impl", CODE)
studio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(studio)


_ACT_SPEC = importlib.util.spec_from_file_location("activation_impl", ROOT / "evals" / "tools" / "activation.py")
activation = importlib.util.module_from_spec(_ACT_SPEC)
_ACT_SPEC.loader.exec_module(activation)

RESULT_VALUES = ("passed", "below-threshold", "partial", "not_run")
BATCH_SHA_RE = re.compile(r"[0-9a-f]{40}")
AB_THRESHOLDS = (("positive_triggered", lambda v: v >= 4, ">= 4"), ("negative_triggered", lambda v: v == 0, "== 0"),
                 ("worse", lambda v: v == 0, "== 0"), ("better", lambda v: v >= 3, ">= 3"), ("pairs", lambda v: v == 5, "== 5"))


def model_evaluated_problems(catalog_path, root):
    """Return the list of reasons the catalog's model_evaluated / status claims are not backed by counted run logs."""
    problems = []
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    for skill in catalog["skills"]:
        name, targets = skill["name"], set(skill["targets"])
        flag, ev = skill.get("model_evaluated"), skill.get("evaluated")
        tag = "%s:" % name
        if "model_evaluated" in skill and not isinstance(flag, bool):
            problems.append("%s model_evaluated=%r must be a JSON bool" % (tag, flag))
        if (skill.get("status") == "model-evaluated") != (flag is True):
            problems.append("%s status %r does not match model_evaluated=%r (model-evaluated only for true)" % (tag, skill.get("status"), flag))
        runs_root = Path(root) / skill["evals"] / "runs"
        # every runtime that appears in any run log must be a declared target
        for f in sorted(list(runs_root.glob("*/*.json")) + list(runs_root.glob("*/smoke/*.json"))) if runs_root.is_dir() else []:
            try:
                log = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if isinstance(log, dict) and "runtime" in log and "with_skill" in log and log["runtime"] not in targets:
                problems.append("%s log %s has runtime %r not in targets %s" % (tag, f.name, log["runtime"], sorted(targets)))
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
        if flag is True and set(harnesses) != targets:
            problems.append("%s evaluated.harnesses keys %s != targets %s" % (tag, sorted(harnesses), sorted(targets)))
        if set(harnesses) - targets:
            problems.append("%s evaluated.harnesses has harness outside targets: %s" % (tag, sorted(set(harnesses) - targets)))
        runs_dir = runs_root / sprint
        counted = activation.summarize(runs_dir) if runs_dir.is_dir() else {}
        ran_logs = _ran_logs(runs_dir) if runs_dir.is_dir() else {}
        cases_file = Path(root) / skill["evals"] / "cases.json"
        cases = json.loads(cases_file.read_text(encoding="utf-8")).get("cases", []) if cases_file.is_file() else []
        n_pos = sum(1 for c in cases if c.get("should_trigger") is True)
        n_neg = sum(1 for c in cases if c.get("should_trigger") is False)
        ab_report = ev.get("ab_report")
        if ab_report is not None and not str(ab_report).replace("\\", "/").startswith("%s/runs/%s/" % (str(skill["evals"]).rstrip("/"), sprint)):
            problems.append("%s ab_report %r must be under %s/runs/%s/" % (tag, ab_report, str(skill["evals"]).rstrip("/"), sprint))
        elif flag is True and ab_report is None:
            problems.append("%s model_evaluated=true needs evaluated.ab_report" % tag)
        ab_name = "ab-%s.json" % ev.get("date", "")
        ab_path = runs_dir / ab_name
        ab = None
        if any(v == "ran" for v in harnesses.values()):
            if not ab_path.is_file():
                problems.append("%s %s missing under %s" % (tag, ab_name, runs_dir.as_posix()))
            else:
                ab = json.loads(ab_path.read_text(encoding="utf-8")).get("per_runtime", {})
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
                    mine_logs = ran_logs.get(h, {"with": [], "base": []})
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
                if h in ran_logs:
                    problems.append("%s harness %s is %r but %s has a ran log for it" % (tag, h, state, runs_dir.as_posix()))
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
    return problems


def _ran_logs(runs_dir):
    """{runtime: {"with": [logs], "base": [logs]}} for every top-level run log with status ran (baseline logs included)."""
    out = {}
    for f in sorted(Path(runs_dir).glob("*.json")):
        try:
            log = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(log, dict) and "runtime" in log and "with_skill" in log and log.get("status") == "ran":
            out.setdefault(log["runtime"], {"with": [], "base": []})["with" if log["with_skill"] is True else "base"].append(log)
    return out


def _fake_evidence(base, write_ab=True, drop_harness=None, extra_runtime=None, status=None, model_evaluated=True, claim_positive=4, mutate=None, flag=None, trig=4, result=None, batch_sha=None, kind="commit"):
    """Build a temp catalog + run logs (claude-code, codex ran; antigravity not_run). Returns (catalog_path, root).

    mutate(runs_dir, ab_dict, harnesses_dict, evaluated_dict) may break the evidence before it is written (gate self-tests)."""
    base = Path(base)
    evals_dir = base / "evals" / "fake-skill"
    runs = evals_dir / "runs" / "SPR-18"
    runs.mkdir(parents=True)
    cases = [{"id": "pos%d" % i, "kind": "typical", "should_trigger": True} for i in range(5)] + [{"id": "neg%d" % i, "kind": "near-miss", "should_trigger": False} for i in range(3)]
    (evals_dir / "cases.json").write_text(json.dumps({"skill_name": "fake-skill", "cases": cases}), encoding="utf-8")
    runtimes = ["claude-code", "codex"] + ([extra_runtime] if extra_runtime else [])
    for rt in runtimes:
        for i in range(5):
            (runs / ("%s_pos%d.json" % (rt, i))).write_text(json.dumps(
                {"runtime": rt, "case_id": "pos%d" % i, "with_skill": True, "status": "ran", "kind": "typical", "triggered": i < trig}), encoding="utf-8")
            (runs / ("%s_base%d.json" % (rt, i))).write_text(json.dumps(
                {"runtime": rt, "case_id": "pos%d" % i, "with_skill": False, "status": "ran", "kind": "typical", "triggered": False}), encoding="utf-8")
        for i in range(3):
            (runs / ("%s_neg%d.json" % (rt, i))).write_text(json.dumps(
                {"runtime": rt, "case_id": "neg%d" % i, "with_skill": True, "status": "ran", "kind": "near-miss", "triggered": False}), encoding="utf-8")
    claim_positive = trig if claim_positive == 4 else claim_positive
    row = lambda: {"positive_triggered": claim_positive, "negative_triggered": 0, "better": 3, "equal": 2, "worse": 0, "pairs": 5}
    ab = {"per_runtime": {"claude-code": row(), "codex": row()}}
    harnesses = {"claude-code": "ran", "codex": "ran", "antigravity": "not_run:headless-no-skill-catalog"}
    if drop_harness:
        del harnesses[drop_harness]
    if status is None:
        status = "model-evaluated" if model_evaluated else "prototype-static-validated"
    evaluated = {"sprint": "SPR-18", "date": "2026-10-18", "harnesses": harnesses,
                 "ab_report": "evals/fake-skill/runs/SPR-18/ab-2026-10-18.md",
                 "result": result if result is not None else ("passed" if (model_evaluated if flag is None else flag) else "partial"),
                 "batch_sha": batch_sha if batch_sha is not None else "a" * 40,
                 "batch_sha_kind": kind}
    if mutate:
        mutate(runs, ab, harnesses, evaluated)
    if write_ab:
        (runs / "ab-2026-10-18.json").write_text(json.dumps(ab), encoding="utf-8")
    catalog = {"skills": [{"name": "fake-skill", "evals": "evals/fake-skill", "status": status, "targets": ["claude-code", "codex", "antigravity"],
                           "model_evaluated": model_evaluated if flag is None else flag,
                           "evaluated": evaluated}]}
    path = base / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path, base


class StudioTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), *map(str, args)], cwd=ROOT, text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_canonical_skills_have_no_static_errors(self):
        for path in studio.skill_dirs(ROOT):
            findings = studio.validate_skill(path, eval_root=ROOT / "evals", require_evals=True)
            self.assertEqual([], [x for x in findings if x["level"] == "ERROR"], path.as_posix())

    def test_every_evals_manifest_is_structurally_valid(self):
        for path in (ROOT / "evals").iterdir():
            if path.is_dir() and any((path / m).exists() for m in ("cases.json", "rubric.md", "fixtures", "baselines", "expected")):
                self.assertFalse([x for x in studio.check_evals(path) if x["level"] == "ERROR"])

    def test_frontmatter_name_and_unsupported_fields_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            skill = Path(t) / "correct-name"
            skill.mkdir()
            (skill / "SKILL.md").write_text('---\nname: Wrong_Name\ndescription: "A test skill. Use when testing name compliance."\ntriggers: all\n---\n\n# Test\n', encoding="utf-8")
            codes = {f["code"] for f in studio.validate_skill(skill) if f["level"] == "ERROR"}
            self.assertIn("FM2", codes)
            self.assertIn("FM4", codes)

    def test_relative_link_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            skill = Path(t) / "sample-safe"
            skill.mkdir()
            (skill / "SKILL.md").write_text('---\nname: sample-safe\ndescription: "Validates names. Use when testing a link."\n---\n\nRead [unsafe](../secret.txt).\n', encoding="utf-8")
            codes = {f["code"] for f in studio.validate_skill(skill) if f["level"] == "ERROR"}
            self.assertIn("ST6", codes)

    def test_new_refuses_overwrite_and_creates_external_empty_evals(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            out = base / "skills"
            evals = base / "evals"
            args = ["new", "test-deep-skill", "--output", str(out), "--eval-root", str(evals), "--description", "Checks data carefully. Use when testing safe skill creation."]
            p = self.run_cli(*args)
            self.assertEqual(0, p.returncode, p.stderr)
            self.assertTrue((out / "test-deep-skill" / "SKILL.md").exists())
            self.assertFalse((out / "test-deep-skill" / "evals").exists())
            cases = json.loads((evals / "test-deep-skill" / "cases.json").read_text())["cases"]
            self.assertEqual(3, len(cases))
            self.assertEqual({True, False}, {c["should_trigger"] for c in cases})
            self.assertTrue(all(c["prompt"].startswith("STUDIO-DRAFT: ") for c in cases))
            name = "test-deep-skill"
            self.assertEqual([(name + "-typical", "typical", True), (name + "-edge", "edge", True), (name + "-negative", "near-miss", False)],
                             [(c["id"], c["kind"], c["should_trigger"]) for c in cases])
            self.assertTrue(all(c["fixtures"] == [] for c in cases))
            self.assertTrue(all(c["expected_behaviors"] and all(b.startswith("STUDIO-DRAFT: ") for b in c["expected_behaviors"]) for c in cases))
            self.assertNotIn(">=3 eval cases", p.stdout)
            self.assertFalse([f for f in studio.check_evals(evals / "test-deep-skill") if f["level"] == "ERROR"])
            self.assertEqual(1, self.run_cli(*args).returncode, "second creation should refuse overwrite")
            self.assertEqual(1, self.run_cli("package", out / "test-deep-skill", "--out", base / "dist").returncode, "draft cannot publish")

    def test_ev4_message_names_plural_key(self):
        with tempfile.TemporaryDirectory() as t:
            ef = Path(t) / "x"
            ef.mkdir()
            (ef / "cases.json").write_text(json.dumps({"skill_name": "x", "cases": [
                {"id": "a", "prompt": "p", "should_trigger": True, "expected_behaviors": []}]}), encoding="utf-8")
            msgs = [f["message"] for f in studio.check_evals(ef) if f["code"] == "EV4"]
            self.assertTrue(any("expected_behaviors" in m for m in msgs), msgs)

    def run_evals_all(self, er):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), "evals", "--all", "--eval-root", str(er)],
                              cwd=ROOT, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_evals_all_skips_folder_with_no_eval_files_but_not_a_broken_eval(self):
        with tempfile.TemporaryDirectory() as t:
            er = Path(t)
            (er / "misc-helpers").mkdir()
            (er / "misc-helpers" / "helper.py").write_text("x = 1\n", encoding="utf-8")
            p = self.run_evals_all(er)
            self.assertEqual(0, p.returncode, p.stdout + p.stderr)
            (er / "half-done").mkdir()
            (er / "half-done" / "rubric.md").write_text("# r\n", encoding="utf-8")
            p = self.run_evals_all(er)
            self.assertEqual(1, p.returncode, "a folder with eval files but no cases.json is still an error")
            self.assertIn("EV1", p.stdout)

    def test_packaged_factory_matches_root_studio(self):
        self.assertEqual((ROOT / "studio.py").read_bytes(), (ROOT / "skills/skill-creator-studio/scripts/studio.py").read_bytes())

    def test_package_is_runtime_only(self):
        with tempfile.TemporaryDirectory() as t:
            package_dir = Path(t)
            run = self.run_cli("package", "skills/data-quality-audit", "--out", package_dir)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            zip_path = package_dir / "data-quality-audit.zip"
            self.assertTrue(zip_path.is_file())
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                self.assertIn("data-quality-audit/SKILL.md", names)
                self.assertFalse(any("evals/" in x or "__pycache__" in x for x in names))

    def test_package_rejects_secret_file(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t) / "demo-skill"
            folder.mkdir()
            (folder / "SKILL.md").write_text('---\nname: demo-skill\ndescription: "Checks inputs. Use when testing security."\n---\n\n# Demo\n', encoding="utf-8")
            (folder / ".env").write_text("PASSWORD=secret", encoding="utf-8")
            files, findings = studio.ensure_distributable(folder)
            self.assertTrue(any(x["code"] == "SEC" and x["level"] == "ERROR" for x in findings))

    def test_install_copy_and_no_implicit_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            workspace = Path(t)
            first = self.run_cli("install", "skills/data-quality-audit", "--agent", "codex", "--workspace", workspace)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            self.assertTrue((workspace / ".agents" / "skills" / "data-quality-audit" / "SKILL.md").is_file())
            self.assertEqual(1, self.run_cli("install", "skills/data-quality-audit", "--agent", "antigravity", "--workspace", workspace).returncode)
            claude = self.run_cli("install", "skills/data-quality-audit", "--agent", "claude", "--workspace", workspace)
            self.assertEqual(0, claude.returncode, claude.stdout + claude.stderr)
            self.assertTrue((workspace / ".claude" / "skills" / "data-quality-audit" / "SKILL.md").exists())

    def test_install_refuses_self_overwrite_even_with_force(self):
        with tempfile.TemporaryDirectory() as t:
            workspace = Path(t)
            src = workspace / ".agents" / "skills" / "data-quality-audit"
            src.parent.mkdir(parents=True)
            import shutil
            shutil.copytree(ROOT / "skills" / "data-quality-audit", src)
            attempt = self.run_cli("install", src, "--agent", "codex", "--workspace", workspace, "--force")
            self.assertEqual(1, attempt.returncode)
            self.assertTrue((src / "SKILL.md").exists())

    def test_standalone_factory_runs_from_packaged_skill(self):
        with tempfile.TemporaryDirectory() as t:
            temp = Path(t)
            packed = self.run_cli("package", "skills/skill-creator-studio", "--out", temp)
            self.assertEqual(0, packed.returncode, packed.stdout + packed.stderr)
            with zipfile.ZipFile(temp / "skill-creator-studio.zip") as zf:
                zf.extractall(temp / "installed")
            factory = temp / "installed" / "skill-creator-studio" / "scripts" / "studio.py"
            run = subprocess.run([sys.executable, str(factory), "new", "external-skill", "--output", str(temp / "skills"), "--eval-root", str(temp / "evals"), "--description", "Checks external data. Use when testing portability outside Studio."], text=True, capture_output=True)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertTrue((temp / "skills" / "external-skill" / "SKILL.md").is_file())
            self.assertTrue((temp / "evals" / "external-skill" / "cases.json").is_file())

    def test_template_mirror_matches(self):
        run = self.run_cli("sync-template", "--check")
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        self.assertEqual((("skill-template", "skill-template"), ("skill-template-full", "skill-template-full")), studio.TEMPLATE_PAIRS)
        for src_name, dst_name in studio.TEMPLATE_PAIRS:
            self.assertEqual([], studio.mirror_diff(ROOT / "templates" / src_name, ROOT / "skills" / "skill-creator-studio" / "assets" / dst_name), src_name)

    def test_registry_matches_skill_folders(self):
        obj = json.loads((ROOT / "registry" / "catalog.json").read_text(encoding="utf-8"))
        catalog_names = {x["name"] for x in obj["skills"]}
        actual_names = {x.name for x in studio.skill_dirs(ROOT)}
        self.assertEqual(actual_names, catalog_names)
        for x in obj["skills"]:
            self.assertTrue((ROOT / x["path"] / "SKILL.md").is_file())
            self.assertTrue((ROOT / x["evals"] / "cases.json").is_file())

    def test_model_evaluated_requires_counted_evidence(self, catalog_path=None):
        """`model_evaluated: true` is allowed only with A/B evidence recounted from the run logs in the repo."""
        problems = model_evaluated_problems(Path(catalog_path) if catalog_path else ROOT / "registry" / "catalog.json", ROOT)
        self.assertEqual([], problems)

    # --- gate self-tests: fake catalogs/logs live in a temp dir, never in the repo ---

    def test_gate_accepts_complete_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t))
            self.assertEqual([], model_evaluated_problems(catalog, root))

    def test_gate_red_true_without_ab_file(self):
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t), write_ab=False)
            problems = model_evaluated_problems(catalog, root)
            self.assertTrue(any("ab-2026-10-18.json" in p and "missing" in p for p in problems), problems)

    def test_gate_red_harness_set_not_equal_targets(self):
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t), drop_harness="antigravity")
            problems = model_evaluated_problems(catalog, root)
            self.assertTrue(any("harnesses keys" in p and "antigravity" in p for p in problems), problems)

    def test_gate_red_runtime_outside_targets(self):
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t), extra_runtime="gemini-cli")
            problems = model_evaluated_problems(catalog, root)
            self.assertTrue(any("gemini-cli" in p and "targets" in p for p in problems), problems)

    def test_gate_red_not_run_harness_with_ran_log(self):
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t), extra_runtime="antigravity")
            problems = model_evaluated_problems(catalog, root)
            self.assertTrue(any("antigravity" in p and "not_run" in p for p in problems), problems)

    def test_gate_red_status_mismatch(self):
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t), status="prototype-static-validated")
            problems = model_evaluated_problems(catalog, root)
            self.assertTrue(any("status" in p for p in problems), problems)
            catalog, root = _fake_evidence(Path(t) / "b", model_evaluated=False, status="model-evaluated")  # false + status model-evaluated
            problems = model_evaluated_problems(catalog, root)
            self.assertTrue(any("status" in p for p in problems), problems)

    # --- SC8 / FR9: `evaluated.result` + `batch_sha`; flag false drops only the AB_THRESHOLDS application ---

    def _gate(self, **kw):
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t), **kw)
            return model_evaluated_problems(catalog, root)

    def test_gate_false_below_threshold_with_matching_counts_is_green(self):
        """tương-đương: SC8-1 (accepting): flag false + result below-threshold, counts recounted from logs (3/5) really below threshold -> green."""
        self.assertEqual([], self._gate(model_evaluated=False, trig=3, result="below-threshold"))

    def test_gate_false_below_threshold_but_counts_meet_thresholds_is_red(self):
        """tương-đương (green at df875ce: the gate function lives in this file): SC8-2 flag false + below-threshold while the recounted numbers meet every threshold -> red (result != recomputed)."""
        problems = self._gate(model_evaluated=False, trig=4, result="below-threshold")
        self.assertTrue(any("result" in p and "recomputed" in p for p in problems), problems)

    def test_gate_false_with_passed_is_red(self):
        """tương-đương (green at df875ce): SC8-3 flag false + result passed is never allowed."""
        problems = self._gate(model_evaluated=False, trig=4, result="passed")
        self.assertTrue(any("passed" in p and "false" in p for p in problems), problems)
        problems = self._gate(model_evaluated=False, trig=3, result="passed")
        self.assertTrue(any("passed" in p and "false" in p for p in problems), problems)

    def test_gate_true_with_below_threshold_is_red(self):
        """tương-đương (green at df875ce): SC8-4 flag true is not relaxed: below-threshold counts stay red, and result must be passed."""
        problems = self._gate(model_evaluated=True, trig=3, result="below-threshold")
        self.assertTrue(any("positive_triggered" in p and ">= 4" in p for p in problems), problems)
        self.assertTrue(any("result" in p and "passed" in p for p in problems), problems)
        problems = self._gate(model_evaluated=True, trig=4, result="partial")
        self.assertTrue(any("result" in p and "passed" in p for p in problems), problems)

    def test_gate_overlap_not_run_harness_and_below_threshold_is_below_threshold(self):
        """tương-đương: SC8-5 antigravity not_run AND a ran harness below threshold -> must be below-threshold, not partial."""
        self.assertEqual([], self._gate(model_evaluated=False, trig=3, result="below-threshold"))
        problems = self._gate(model_evaluated=False, trig=3, result="partial")
        self.assertTrue(any("result" in p and "recomputed" in p and "below-threshold" in p for p in problems), problems)

    def test_gate_false_partial_and_integrity_checks_still_apply(self):
        """tương-đương: FR9.2: flag false only skips AB_THRESHOLDS; log-vs-ab recount, ab_report location and missing ab file stay red."""
        self.assertEqual([], self._gate(model_evaluated=False, trig=4, result="partial"))
        problems = self._gate(model_evaluated=False, trig=3, result="below-threshold", claim_positive=5)
        self.assertTrue(any("recount" in p for p in problems), problems)
        problems = self._gate(model_evaluated=False, result="partial", write_ab=False)
        self.assertTrue(any("missing" in p for p in problems), problems)

        def bad_report(runs, ab, h, ev):
            ev["ab_report"] = "elsewhere/ab.md"
        self._gate_red(bad_report, "ab_report", model_evaluated=False, result="partial")

    def test_gate_result_enum_and_batch_sha_format(self):
        """tương-đương: FR9.1: result must be a known value and batch_sha 40 lowercase hex."""
        problems = self._gate(model_evaluated=False, result="great")
        self.assertTrue(any("result" in p and "great" in p for p in problems), problems)
        for bad in ("abc1234", "G" * 40, "A" * 40):
            problems = self._gate(model_evaluated=False, result="partial", batch_sha=bad)
            self.assertTrue(any("batch_sha" in p for p in problems), (bad, problems))

    def test_gate_batch_sha_kind_required_and_valid(self):
        """tương-đương: batch_sha_kind is required with batch_sha and must be commit or tree."""
        self.assertEqual([], self._gate(model_evaluated=False, result="partial", kind="tree"))
        for bad in ("blob", None, ""):
            problems = self._gate(model_evaluated=False, result="partial", kind=bad)
            self.assertTrue(any("batch_sha_kind" in p for p in problems), (bad, problems))

    def test_gate_not_run_when_no_harness_ran(self):
        """tương-đương: FR9.1: no harness ran at all -> result not_run; claiming below-threshold is red."""
        def m(runs, ab, h, ev):
            for k in ("claude-code", "codex"):
                h[k] = "not_run:no-quota"
            for f in runs.glob("*.json"):
                f.unlink()
        self._gate_red(m, "recomputed", model_evaluated=False, result="partial", write_ab=False)
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t), model_evaluated=False, result="not_run", write_ab=False, mutate=m)
            self.assertEqual([], model_evaluated_problems(catalog, root))

    def test_runbook_has_batch_rules_section(self):
        """bắt-lỗi (red at df875ce: no «Luật lô» section): FR8.1: RUNBOOK «Luật lô» exists and names the four mandatory phrases, with PowerShell and bash examples."""
        text = (ROOT / "evals" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("## Luật lô", text)
        section = text[text.index("## Luật lô"):]
        for phrase in ("--plugin-dir", "redact.py", "SHA lô", "git archive"):
            self.assertIn(phrase, section, phrase)
        self.assertIn("```powershell", section)
        self.assertIn("```bash", section)
        self.assertIn("--main-skill-dir", section)

    def test_gate_red_log_count_differs_from_ab_report(self):
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t), claim_positive=5)  # ab json claims 5, logs show 4
            problems = model_evaluated_problems(catalog, root)
            self.assertTrue(any("recount" in p and "positive_triggered" in p for p in problems), problems)

    def _gate_red(self, mutate, needle, **kw):
        with tempfile.TemporaryDirectory() as t:
            catalog, root = _fake_evidence(Path(t), mutate=mutate, **kw)
            problems = model_evaluated_problems(catalog, root)
            self.assertTrue(any(needle in p for p in problems), problems)

    def test_gate_red_zero_negative_logs(self):
        def m(runs, ab, h, ev):
            for f in runs.glob("codex_neg*.json"):
                f.unlink()
        self._gate_red(m, "negative logs")

    def test_gate_red_only_four_positive_logs(self):
        def m(runs, ab, h, ev):
            (runs / "claude-code_pos4.json").unlink()
        self._gate_red(m, "positive logs")

    def test_gate_red_duplicate_codex_batch(self):
        def m(runs, ab, h, ev):
            for i in range(5):
                (runs / ("codex_dup%d.json" % i)).write_text((runs / ("codex_pos%d.json" % i)).read_text(encoding="utf-8"), encoding="utf-8")
            for f in runs.glob("codex_neg*.json"):
                f.unlink()
        self._gate_red(m, "duplicate")

    def test_gate_red_buckets_do_not_sum_to_pairs(self):
        def m(runs, ab, h, ev):
            ab["per_runtime"]["codex"]["equal"] = 1  # 3 + 1 + 0 != 5
        self._gate_red(m, "better+equal+worse")

    def test_gate_red_pairs_differ_from_baseline_logs(self):
        def m(runs, ab, h, ev):
            (runs / "codex_base4.json").unlink()  # 4 baselines, ab claims 5 pairs
        self._gate_red(m, "baseline logs")

    def test_gate_red_ab_report_of_another_skill(self):
        def m(runs, ab, h, ev):
            ev["ab_report"] = "evals/other-skill/runs/SPR-18/ab-2026-10-18.md"
        self._gate_red(m, "ab_report")

    def test_gate_red_not_run_harness_with_ran_baseline(self):
        def m(runs, ab, h, ev):
            (runs / "antigravity_base0.json").write_text(json.dumps(
                {"runtime": "antigravity", "case_id": "pos0", "with_skill": False, "status": "ran", "kind": "typical", "triggered": False}), encoding="utf-8")
        self._gate_red(m, "antigravity")

    def test_gate_red_per_runtime_numbers_for_not_run_harness(self):
        def m(runs, ab, h, ev):
            ab["per_runtime"]["antigravity"] = {"positive_triggered": 4, "negative_triggered": 0, "better": 3, "equal": 2, "worse": 0, "pairs": 5}
        self._gate_red(m, "antigravity")

    def test_gate_red_flag_is_a_string_not_a_bool(self):
        self._gate_red(None, "bool", flag="true")

    def test_gate_checks_smoke_log_runtime_against_targets(self):
        def m(runs, ab, h, ev):
            (runs / "smoke").mkdir()
            (runs / "smoke" / "x_with.json").write_text(json.dumps({"runtime": "gemini-cli", "with_skill": True, "status": "ran"}), encoding="utf-8")
        self._gate_red(m, "gemini-cli")

    def test_gate_blocks_enabling_with_real_numbers(self):
        """Real SPR-18 evidence (better 0, Codex negative 2/3) must not allow flipping data-quality-audit to true."""
        obj = json.loads((ROOT / "registry" / "catalog.json").read_text(encoding="utf-8"))
        for x in obj["skills"]:
            if x["name"] == "data-quality-audit":
                x["model_evaluated"] = True
                x["status"] = "model-evaluated"
                x["evaluated"] = {"sprint": "SPR-18", "date": "2026-10-18",
                                  "harnesses": {"claude-code": "ran", "codex": "ran", "antigravity": "not_run:headless-no-skill-catalog"},
                                  "ab_report": "evals/data-quality-audit/runs/SPR-18/ab-2026-10-18.md"}
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "catalog.json"
            path.write_text(json.dumps(obj), encoding="utf-8")
            problems = model_evaluated_problems(path, ROOT)
            self.assertTrue(any("better" in p for p in problems), problems)
            self.assertTrue(any("codex" in p and "negative_triggered" in p for p in problems), problems)
            with self.assertRaises(AssertionError):
                self.test_model_evaluated_requires_counted_evidence(catalog_path=path)


DESC = "Checks data carefully. Use when testing scaffold generation."


def nonblank(path: Path) -> int:
    return sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())


class TemplateTests(unittest.TestCase):
    """FR10 / FR19: minimal EN/VI template, --full, mirror_diff and install --user (SPR-33 TK6)."""

    def run_cli(self, *args):
        return self.run_cli_env({}, *args)

    def run_cli_env(self, env, *args):
        merged = dict(os.environ)
        merged.update(env)
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), *map(str, args)], cwd=ROOT, env=merged,
                              text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def make_home(self, base, *subdirs):
        home = Path(base) / "home"
        home.mkdir()
        for sub in subdirs:
            (home / sub).mkdir(parents=True)
        return home, {"HOME": str(home), "USERPROFILE": str(home)}

    def new_skill(self, base, name, *extra):
        out, evals = Path(base) / "skills", Path(base) / "evals"
        run = self.run_cli("new", name, "--description", DESC, "--output", out, "--eval-root", evals, *extra)
        return run, out / name

    def split(self, skill_md):
        text = skill_md.read_text(encoding="utf-8").replace("\r\n", "\n")
        _, front, body = text.split("---\n", 2)
        return front, body

    def test_new_minimal_default(self):
        with tempfile.TemporaryDirectory() as t:
            run, skill = self.new_skill(t, "demo-min")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertEqual(["SKILL.md"], sorted(p.relative_to(skill).as_posix() for p in skill.rglob("*") if p.is_file()))
            self.assertLessEqual(nonblank(skill / "SKILL.md"), 20)
            self.assertIn("STUDIO-DRAFT", (skill / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual([], [f for f in studio.validate_skill(skill) if f["level"] == "ERROR"])
            pack = self.run_cli("package", skill, "--out", Path(t) / "dist")
            self.assertEqual(1, pack.returncode, pack.stdout + pack.stderr)
            self.assertIn("PACK", pack.stdout)

    def test_new_full_flag(self):
        with tempfile.TemporaryDirectory() as t:
            run, skill = self.new_skill(t, "demo-full", "--full")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            for rel in ("SKILL.md", "references/PROCESS_TEMPLATE.md", "scripts/check_inputs.py", "agents/openai.yaml",
                        "assets/templates/OUTPUT_TEMPLATE.md", "assets/sample-data/example.json"):
                self.assertTrue((skill / rel).is_file(), rel)
            self.assertFalse((skill / "references" / "WORKFLOW_GUIDE.md").exists())
            self.assertNotIn("WORKFLOW_GUIDE", (skill / "SKILL.md").read_text(encoding="utf-8"))
            findings = studio.validate_skill(skill)
            self.assertEqual([], [f for f in findings if f["level"] == "ERROR"])
            self.assertNotIn("CT10", {f["code"] for f in findings})

    def test_new_lang_vi_body_vietnamese_frontmatter_english(self):
        with tempfile.TemporaryDirectory() as t:
            run, skill = self.new_skill(t, "demo-vi", "--lang", "vi")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertEqual(["SKILL.md"], sorted(p.relative_to(skill).as_posix() for p in skill.rglob("*") if p.is_file()))
            front, body = self.split(skill / "SKILL.md")
            self.assertTrue(front.isascii(), front)
            self.assertEqual("vi", studio.detect_lang(body))
            self.assertEqual(body, unicodedata.normalize("NFC", body))
            self.assertIn("## Gotchas", body)
            self.assertIn("## References", body)
            findings = studio.validate_skill(skill)
            self.assertEqual([], [f for f in findings if f["code"].startswith("VI")])
            self.assertEqual([], [f for f in findings if f["level"] == "ERROR"])

    def test_new_lang_default_en(self):
        with tempfile.TemporaryDirectory() as t:
            run, skill = self.new_skill(t, "demo-en")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            front, body = self.split(skill / "SKILL.md")
            self.assertEqual("en", studio.detect_lang(body))
            self.assertIn("what an agent would get wrong", body)
            run2, skill2 = self.new_skill(t, "demo-en2", "--lang", "en")
            self.assertEqual(0, run2.returncode, run2.stdout + run2.stderr)
            self.assertEqual(body, self.split(skill2 / "SKILL.md")[1].replace("Demo En2", "Demo En"))

    def test_new_lang_invalid_exit2(self):
        with tempfile.TemporaryDirectory() as t:
            run, skill = self.new_skill(t, "demo-fr", "--lang", "fr")
            self.assertEqual(2, run.returncode, run.stdout + run.stderr)
            self.assertIn("invalid choice: 'fr'", run.stderr)
            self.assertFalse(skill.exists())

    def test_new_full_lang_vi_exit2(self):
        with tempfile.TemporaryDirectory() as t:
            run, skill = self.new_skill(t, "demo-fv", "--full", "--lang", "vi")
            self.assertEqual(2, run.returncode, run.stdout + run.stderr)
            self.assertIn("full template is English-only", run.stderr)
            self.assertFalse(skill.exists())
            self.assertFalse((Path(t) / "evals" / "demo-fv").exists())

    def test_minimal_templates_stay_under_20_nonblank_lines(self):
        """SC4: both default templates stay small; the Vietnamese one mirrors the English headings."""
        counts = [nonblank(ROOT / "templates" / "skill-template" / f) for f in ("SKILL.md", "SKILL.vi.md")]
        self.assertEqual([14, 14], counts)
        en = (ROOT / "templates" / "skill-template" / "SKILL.md").read_text(encoding="utf-8")
        vi = (ROOT / "templates" / "skill-template" / "SKILL.vi.md").read_text(encoding="utf-8")
        for heading in ("# Skill Template", "## Gotchas", "## References"):
            self.assertIn(heading, en)
            self.assertIn(heading, vi)
        self.assertNotIn("<", re.search(r"^description: (.*)$", en, re.M).group(1))

    def test_full_has_process_template(self):
        process = studio.get_template(full=True) / "references" / "PROCESS_TEMPLATE.md"
        text = process.read_text(encoding="utf-8")
        for needle in ("# Process Template", "> **Conclusion:**", "## When to use / not", "## Steps", "### Step 1",
                       "Command:", "Expect:", "Stop if:", "## Gotchas", "## Done when"):
            self.assertIn(needle, text)
        lines = text.replace("\r\n", "\n").split("\n")
        for label in ("Command", "Expect", "Stop if"):
            self.assertEqual(1, sum(1 for ln in lines if ln.startswith("- %s: " % label)), label)
            self.assertFalse([ln for ln in lines if ln.startswith(label + ":")], "bare %s: line would merge when rendered" % label)
        self.assertIn("- Command: [FILL: ", text)
        self.assertFalse((process.parent / "WORKFLOW_GUIDE.md").exists())
        self.assertEqual("# Optional, Codex only; delete if unused.", (process.parent.parent / "agents" / "openai.yaml").read_text(encoding="utf-8").splitlines()[0])

    def test_get_template_selects_files(self):
        base = studio.get_template().parent
        self.assertEqual(base / "SKILL.md", studio.get_template())
        self.assertEqual(base / "SKILL.vi.md", studio.get_template(False, "vi"))
        self.assertEqual(base.parent / "skill-template-full", studio.get_template(True))
        self.assertEqual(base.parent / "skill-template-full", studio.get_template(full=True, lang="en"))

    def test_mirror_diff_detects_extra_file(self):
        with tempfile.TemporaryDirectory() as t:
            src, dst = Path(t) / "src", Path(t) / "dst"
            for root in (src, dst):
                (root / "sub").mkdir(parents=True)
                (root / "same.txt").write_bytes(b"same")
                (root / "sub" / "keep.txt").write_bytes(b"keep")
            self.assertEqual([], studio.mirror_diff(src, dst))
            (dst / "extra.txt").write_bytes(b"x")
            (dst / "sub" / "keep.txt").write_bytes(b"changed")
            (src / "missing.txt").write_bytes(b"m")
            self.assertEqual(["extra.txt", "missing.txt", "sub/keep.txt"], studio.mirror_diff(src, dst))
            self.assertEqual(["missing.txt", "same.txt", "sub/keep.txt"], studio.mirror_diff(src, Path(t) / "absent"))

    def test_package_includes_agents_dir(self):
        with tempfile.TemporaryDirectory() as t:
            skill = Path(t) / "pack-me"
            (skill / "agents").mkdir(parents=True)
            (skill / "evals").mkdir()
            (skill / "tests").mkdir()
            (skill / "SKILL.md").write_text('---\nname: pack-me\ndescription: "Packs a sample. Use when testing agents directory packaging; not for real work."\n---\n\n# Pack Me\n\nBody.\n', encoding="utf-8")
            (skill / "agents" / "openai.yaml").write_text("policy:\n  allow_implicit_invocation: true\n", encoding="utf-8")
            (skill / "evals" / "cases.json").write_text("{}", encoding="utf-8")
            (skill / "tests" / "t.py").write_text("x = 1\n", encoding="utf-8")
            run = self.run_cli("package", skill, "--out", Path(t) / "dist")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            with zipfile.ZipFile(Path(t) / "dist" / "pack-me.zip") as zf:
                names = set(zf.namelist())
            self.assertIn("pack-me/agents/openai.yaml", names)
            self.assertIn("pack-me/SKILL.md", names)
            self.assertFalse([n for n in names if "/evals/" in n or "/tests/" in n], names)

    def test_install_user_antigravity_under_home(self):
        with tempfile.TemporaryDirectory() as t:
            home, env = self.make_home(t, ".gemini/config")
            run = self.run_cli_env(env, "install", "skills/data-quality-audit", "--agent", "antigravity", "--user")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            dest = home / ".gemini" / "config" / "skills" / "data-quality-audit"
            self.assertTrue((dest / "SKILL.md").is_file())
            self.assertTrue(dest.resolve().is_relative_to(Path(t).resolve()))
            self.assertIn(str(dest), run.stdout)

    def test_install_user_codex_under_home(self):
        with tempfile.TemporaryDirectory() as t:
            home, env = self.make_home(t, ".agents")
            run = self.run_cli_env(env, "install", "skills/data-quality-audit", "--agent", "codex", "--user")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            dest = home / ".agents" / "skills" / "data-quality-audit"
            self.assertTrue((dest / "SKILL.md").is_file())
            self.assertTrue(dest.resolve().is_relative_to(Path(t).resolve()))

    def test_install_user_claude_exit2(self):
        with tempfile.TemporaryDirectory() as t:
            home, env = self.make_home(t, ".claude")
            run = self.run_cli_env(env, "install", "skills/data-quality-audit", "--agent", "claude", "--user")
            self.assertEqual(2, run.returncode, run.stdout + run.stderr)
            self.assertIn("not supported for claude", run.stderr)
            self.assertEqual([], list((home / ".claude").iterdir()))

    def test_install_user_with_workspace_exit2(self):
        with tempfile.TemporaryDirectory() as t:
            home, env = self.make_home(t, ".agents")
            run = self.run_cli_env(env, "install", "skills/data-quality-audit", "--agent", "codex", "--user", "--workspace", ".")
            self.assertEqual(2, run.returncode, run.stdout + run.stderr)
            self.assertIn("not allowed with argument", run.stderr)
            self.assertEqual([], list((home / ".agents").iterdir()))

    def test_install_user_missing_parent_exit2(self):
        with tempfile.TemporaryDirectory() as t:
            for agent, parent in (("antigravity", ".gemini"), ("codex", ".agents")):
                home, env = self.make_home(Path(tempfile.mkdtemp(dir=t)))
                run = self.run_cli_env(env, "install", "skills/data-quality-audit", "--agent", agent, "--user")
                self.assertEqual(2, run.returncode, run.stdout + run.stderr)
                self.assertIn("parent directory not found", run.stderr)
                self.assertEqual([], list(home.iterdir()), "must not create anything under HOME")
                self.assertFalse((home / parent).exists())

    def test_full_and_minimal_templates_validate_clean(self):
        """Round-2 fix 1: the full template is named like its folder, so validate has no FM2."""
        for folder in ("skill-template", "skill-template-full"):
            findings = studio.validate_skill(ROOT / "templates" / folder)
            self.assertEqual([], [f for f in findings if f["level"] == "ERROR"], folder)
            run = self.run_cli("validate", ROOT / "templates" / folder)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            self.assertIn(": 0 errors;", run.stdout)
        self.assertIn("name: skill-template-full\n", (ROOT / "templates" / "skill-template-full" / "SKILL.md").read_text(encoding="utf-8"))

    def test_new_full_does_not_leak_template_suffix_into_name(self):
        with tempfile.TemporaryDirectory() as t:
            run, skill = self.new_skill(t, "demo-nm", "--full")
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(1, len(re.findall(r"^name: demo-nm$", text, re.M)), text[:200])
            self.assertNotIn("demo-nm-full", text)
            self.assertNotIn("name: skill-template", text)
            self.assertEqual([], [f for f in studio.validate_skill(skill) if f["code"] == "FM2"])

    def test_install_without_scope_flag_means_workspace_dot(self):
        """No --workspace/--user is --workspace . (the current directory), not its parent."""
        source = (ROOT / "skills" / "data-quality-audit").resolve()
        with tempfile.TemporaryDirectory() as t:
            cwd = Path(t) / "proj" / "inner"
            cwd.mkdir(parents=True)
            run = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "studio.py"), "install", str(source), "--agent", "codex"],
                                 cwd=cwd, text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            dest = cwd / ".agents" / "skills" / "data-quality-audit"
            self.assertTrue((dest / "SKILL.md").is_file(), run.stdout)
            self.assertTrue(dest.resolve().is_relative_to(Path(t).resolve()))
            self.assertFalse((cwd.parent / ".agents").exists())
            self.assertIn("Installed data-quality-audit for codex at ", run.stdout)

    def test_install_force_refuses_symlink_destination_in_process(self):
        """Guard test that needs no symlink privilege: a destination reported as a link is never replaced."""
        import contextlib
        import io
        from unittest import mock

        original = Path.is_symlink
        with tempfile.TemporaryDirectory() as t:
            home, env = self.make_home(t, ".agents/skills")
            dest = home / ".agents" / "skills" / "data-quality-audit"
            dest.mkdir()
            (dest / "marker.txt").write_text("keep", encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()

            def fake(self):
                return self == dest or original(self)

            with mock.patch.dict(os.environ, env), mock.patch.object(Path, "is_symlink", fake), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = studio.main(["install", str(ROOT / "skills" / "data-quality-audit"), "--agent", "codex", "--user", "--force"])
            self.assertEqual((1, True), (code, "symlink destination refused" in err.getvalue()), err.getvalue())
            self.assertEqual("keep", (dest / "marker.txt").read_text(encoding="utf-8"))
            self.assertEqual(["data-quality-audit"], sorted(p.name for p in dest.parent.iterdir()), "no backup may be created")

    @unittest.skipUnless(os.name == "nt", "directory junctions are the unprivileged link type on Windows; plain symlinks need admin there")
    def test_install_user_force_refuses_junction_destination(self):
        import _winapi
        import hashlib

        def tree_sha(base):
            digest = hashlib.sha256()
            for q in sorted(base.rglob("*")):
                digest.update(q.relative_to(base).as_posix().encode() + (q.read_bytes() if q.is_file() else b""))
            return digest.hexdigest()

        with tempfile.TemporaryDirectory() as t:
            home, env = self.make_home(t, ".agents/skills")
            outside = Path(t) / "outside"
            outside.mkdir()
            (outside / "keep.txt").write_text("keep", encoding="utf-8")
            before = tree_sha(outside)
            dest = home / ".agents" / "skills" / "data-quality-audit"
            _winapi.CreateJunction(str(outside), str(dest))
            try:
                run = self.run_cli_env(env, "install", "skills/data-quality-audit", "--agent", "codex", "--user", "--force")
                self.assertEqual(1, run.returncode, run.stdout + run.stderr)
                self.assertIn("symlink destination refused", run.stderr)
                self.assertEqual(before, tree_sha(outside), "junction target must not be written through")
                self.assertEqual(["keep.txt"], sorted(q.name for q in outside.iterdir()))
                self.assertEqual(["data-quality-audit"], sorted(q.name for q in dest.parent.iterdir()), "no backup may be created")
            finally:
                try:
                    os.rmdir(dest)  # removes the junction itself, never its target; a real dir here means the guard failed
                except OSError:
                    pass

    @unittest.skipUnless(os.name == "nt", "directory junctions are the unprivileged link type on Windows; plain symlinks need admin there")
    def test_install_user_force_junction_to_source_refuses_self_overwrite(self):
        import _winapi
        import hashlib
        import shutil

        def tree_sha(base):
            digest = hashlib.sha256()
            for q in sorted(base.rglob("*")):
                digest.update(q.relative_to(base).as_posix().encode() + (q.read_bytes() if q.is_file() else b""))
            return digest.hexdigest()

        with tempfile.TemporaryDirectory() as t:
            home, env = self.make_home(t, ".agents/skills")
            source = Path(t) / "src" / "data-quality-audit"
            shutil.copytree(ROOT / "skills" / "data-quality-audit", source)
            before = tree_sha(source)
            dest = home / ".agents" / "skills" / "data-quality-audit"
            _winapi.CreateJunction(str(source), str(dest))
            try:
                run = self.run_cli_env(env, "install", source, "--agent", "codex", "--user", "--force")
                self.assertEqual(1, run.returncode, run.stdout + run.stderr)
                self.assertIn("refusing self-overwrite", run.stderr)
                self.assertEqual(before, tree_sha(source))
            finally:
                try:
                    os.rmdir(dest)  # removes the junction itself, never its target; a real dir here means the guard failed
                except OSError:
                    pass

    def test_is_link_detects_reparse_points(self):
        with tempfile.TemporaryDirectory() as t:
            plain = Path(t) / "plain"
            plain.mkdir()
            self.assertFalse(studio.is_link(plain))
            self.assertFalse(studio.is_link(Path(t) / "absent"))
            if os.name == "nt":
                import _winapi
                link = Path(t) / "junction"
                _winapi.CreateJunction(str(plain), str(link))
                try:
                    self.assertTrue(studio.is_link(link))
                finally:
                    os.rmdir(link)


    def test_install_user_in_process(self):
        """Same paths through main() so the changed lines are measured by coverage."""
        import contextlib
        import io
        from unittest import mock

        def call(env, *argv):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = studio.main(list(map(str, argv)))
                except SystemExit as exc:
                    code = exc.code
            return code, out.getvalue(), err.getvalue()

        skill = ROOT / "skills" / "data-quality-audit"
        with tempfile.TemporaryDirectory() as t:
            home, env = self.make_home(t, ".gemini/config", ".agents")
            with mock.patch.dict(os.environ, env):
                self.assertEqual(home / ".gemini" / "config" / "skills", studio.user_skill_root("antigravity"))
                self.assertEqual(home / ".agents" / "skills", studio.user_skill_root("codex"))
                with self.assertRaises(ValueError):
                    studio.user_skill_root("claude")
            self.assertEqual(0, call(env, "install", skill, "--agent", "antigravity", "--user")[0])
            self.assertEqual(0, call(env, "install", skill, "--agent", "codex", "--user")[0])
            code, _, err = call(env, "install", skill, "--agent", "codex", "--user")
            self.assertEqual(1, code, err)
            code, _, err = call(env, "install", skill, "--agent", "claude", "--user")
            self.assertEqual((2, True), (code, "not supported for claude" in err))
            code, _, err = call(env, "install", skill, "--agent", "codex", "--user", "--workspace", ".")
            self.assertEqual((2, True), (code, "not allowed with argument" in err))
            lone, lone_env = self.make_home(Path(tempfile.mkdtemp(dir=t)))
            code, _, err = call(lone_env, "install", skill, "--agent", "antigravity", "--user")
            self.assertEqual((2, True, []), (code, "parent directory not found" in err, list(lone.iterdir())))

    def test_new_and_sync_in_process(self):
        import contextlib
        import io

        def call(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = studio.main(list(map(str, argv)))
                except SystemExit as exc:
                    code = exc.code
            return code, out.getvalue(), err.getvalue()

        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            common = ("--description", DESC, "--output", base / "skills", "--eval-root", base / "evals")
            self.assertEqual(0, call("new", "ip-min", *common)[0])
            self.assertEqual(0, call("new", "ip-vi", "--lang", "vi", *common)[0])
            self.assertEqual(0, call("new", "ip-full", "--full", *common)[0])
            code, _, err = call("new", "ip-bad", "--full", "--lang", "vi", *common)
            self.assertEqual((2, True), (code, "English-only" in err))
            self.assertEqual({"SKILL.md"}, {p.name for p in (base / "skills" / "ip-vi").iterdir()})
            self.assertTrue((base / "skills" / "ip-full" / "agents" / "openai.yaml").is_file())
        code, out, err = call("sync-template", "--check")
        self.assertEqual(0, code, out + err)

    def test_install_workspace_and_sync_branches_in_process(self):
        """Covers the --workspace path of install and both sync-template modes without touching the repo copies."""
        import contextlib
        import io
        from unittest import mock

        def call(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = studio.main(list(map(str, argv)))
                except SystemExit as exc:
                    code = exc.code
            return code, out.getvalue(), err.getvalue()

        with tempfile.TemporaryDirectory() as t:
            ws = Path(t) / "ws"
            ws.mkdir()
            self.assertEqual(0, call("install", ROOT / "skills" / "data-quality-audit", "--agent", "claude", "--workspace", ws)[0])
            self.assertTrue((ws / ".claude" / "skills" / "data-quality-audit" / "SKILL.md").is_file())
            code, _, err = call("install", ROOT / "skills" / "data-quality-audit", "--agent", "codex", "--workspace", Path(t) / "absent")
            self.assertEqual((2, True), (code, "workspace directory not found" in err))
        with mock.patch.object(studio, "mirror_diff", return_value=["SKILL.md"]):
            code, _, err = call("sync-template", "--check")
        self.assertEqual((1, True), (code, "template mirror differs: skill-template/SKILL.md" in err))
        with mock.patch.object(studio.shutil, "rmtree") as rm, mock.patch.object(studio.shutil, "copytree") as cp:
            code, out, _ = call("sync-template")
        self.assertEqual((0, 2, 2, True), (code, rm.call_count, cp.call_count, "Synced 2 canonical templates" in out))


class AgentskillsExportTests(unittest.TestCase):
    """`evals <skill> --export agentskills` (SPEC 9.6). Pure function plus CLI, in process so coverage sees it."""

    def call(self, *argv):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = studio.main(list(map(str, argv)))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def make_eval(self, base, name="demo-skill", cases=None, status="frozen", fixtures=None):
        folder = Path(base) / "evals" / name
        (folder / "fixtures").mkdir(parents=True)
        (folder / "rubric.md").write_text("# rubric\n", encoding="utf-8")
        for fname, data in (fixtures or {"a.csv": b"id,amount\r\n1,2\r\n", "b.csv": "id,tên\n1,Đức\n".encode("utf-8")}).items():
            (folder / "fixtures" / fname).write_bytes(data)
        cases = cases or [
            {"id": "c1", "kind": "typical", "prompt": "Audit a.csv, tiếng Việt ok", "should_trigger": True, "fixtures": ["fixtures/a.csv"], "expected_behaviors": ["Reads a.csv", "Reports rows"]},
            {"id": "c2", "kind": "edge", "prompt": "Audit b.csv", "should_trigger": True, "fixtures": ["fixtures/a.csv", "fixtures/b.csv"], "expected_behaviors": ["Handles UTF-8"]},
            {"id": "c3", "kind": "near-miss", "prompt": "Explain CALCULATE", "should_trigger": False, "fixtures": [], "expected_behaviors": ["Does not trigger"]},
        ]
        (folder / "cases.json").write_text(json.dumps({"skill_name": name, "status": status, "cases": cases}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return folder

    def test_export_agentskills_schema(self):
        real = ROOT / "evals" / "data-quality-audit"
        source = json.loads((real / "cases.json").read_text(encoding="utf-8"))["cases"]
        positive = [c for c in source if c["should_trigger"]]
        with tempfile.TemporaryDirectory() as t:
            code, findings, stats = studio.export_agentskills(real, "data-quality-audit", Path(t) / "out")
            self.assertEqual((0, []), (code, findings))
            target = Path(t) / "out" / "data-quality-audit" / "evals" / "evals.json"
            raw = target.read_text(encoding="utf-8")
            self.assertTrue(raw.endswith("}\n"))
            data = json.loads(raw)
            self.assertEqual(json.dumps(data, ensure_ascii=False, indent=2) + "\n", raw)
            self.assertEqual({"skill_name", "evals"}, set(data))
            self.assertEqual("data-quality-audit", data["skill_name"])
            self.assertEqual(list(range(1, 6)), [e["id"] for e in data["evals"]])
            for e, c in zip(data["evals"], positive):
                self.assertEqual(["id", "prompt", "expected_output", "files", "assertions"], list(e))
                self.assertEqual(c["prompt"], e["prompt"])
                self.assertEqual(c["expected_behaviors"], e["assertions"])
                self.assertEqual("; ".join(c["expected_behaviors"]), e["expected_output"])
                self.assertEqual(["evals/files/" + Path(f).name for f in c["fixtures"]], e["files"])
                for f in c["fixtures"]:
                    copy = target.parent / "files" / Path(f).name
                    self.assertEqual((real / f).read_bytes(), copy.read_bytes())
            self.assertEqual(str(target), stats["path"])
        with tempfile.TemporaryDirectory() as t:
            code, out, err = self.call("evals", "data-quality-audit", "--export", "agentskills", "--out", Path(t) / "x")
            self.assertEqual((0, ""), (code, err))
            self.assertIn("exported 5, excluded 3", out)

    def test_export_excludes_negative_cases(self):
        with tempfile.TemporaryDirectory() as t:
            code, _, stats = studio.export_agentskills(ROOT / "evals" / "data-quality-audit", "data-quality-audit", Path(t) / "out")
            self.assertEqual(0, code)
            self.assertEqual((5, 3), (stats["exported"], stats["excluded_negative"]))
            raw = (Path(t) / "out" / "data-quality-audit" / "evals" / "evals.json").read_text(encoding="utf-8")
            cases = json.loads((ROOT / "evals" / "data-quality-audit" / "cases.json").read_text(encoding="utf-8"))["cases"]
            for c in cases:
                self.assertEqual(c["should_trigger"], c["prompt"] in raw, c["id"])

    def test_export_refuses_draft(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            self.assertEqual(0, self.call("new", "draft-one", "--description", "Checks drafts. Use when testing exports.", "--output", base / "skills", "--eval-root", base / "evals")[0])
            code, out, err = self.call("evals", "draft-one", "--eval-root", base / "evals", "--export", "agentskills", "--out", base / "out")
            self.assertEqual(1, code, out + err)
            self.assertFalse((base / "out").exists())
            code, findings, stats = studio.export_agentskills(base / "evals" / "draft-one", "draft-one", base / "out")
            self.assertEqual((1, True, 0), (code, any("draft" in f["message"] for f in findings), stats["exported"]))
            self.assertFalse((base / "out").exists())

    def test_export_refuses_broken_cases(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            (folder / "cases.json").write_text("{not json", encoding="utf-8")
            code, findings, _ = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
            self.assertEqual((1, "EV1"), (code, findings[0]["code"]))
            self.assertFalse((Path(t) / "out").exists())
            code, out, err = self.call("evals", "demo-skill", "--eval-root", Path(t) / "evals", "--export", "agentskills", "--out", Path(t) / "out")
            self.assertEqual(1, code, out + err)
            self.assertFalse((Path(t) / "out").exists())

    def test_export_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            out = Path(t) / "out"
            self.assertEqual(0, studio.export_agentskills(folder, "demo-skill", out)[0])
            target = out / "demo-skill" / "evals" / "evals.json"
            target.write_text("MARK\n", encoding="utf-8")
            code, findings, _ = studio.export_agentskills(folder, "demo-skill", out)
            self.assertEqual((1, "MARK\n"), (code, target.read_text(encoding="utf-8")))
            self.assertTrue(findings)
            code, _, err = self.call("evals", "demo-skill", "--eval-root", Path(t) / "evals", "--export", "agentskills", "--out", out)
            self.assertEqual((1, "MARK\n"), (code, target.read_text(encoding="utf-8")))
            self.assertIn("--force", err)
            self.assertEqual(0, self.call("evals", "demo-skill", "--eval-root", Path(t) / "evals", "--export", "agentskills", "--out", out, "--force")[0])
            self.assertEqual("demo-skill", json.loads(target.read_text(encoding="utf-8"))["skill_name"])

    def test_export_refuses_out_under_skills(self):
        skills = ROOT / "skills"
        before = sorted(x.name for x in skills.iterdir())
        target = skills / "x-export-guard"
        self.addCleanup(shutil.rmtree, target, ignore_errors=True)  # a broken guard must not leave test data in the real skills/ tree
        code, out, err = self.call("evals", "data-quality-audit", "--export", "agentskills", "--out", target)
        self.assertEqual((2, True, False), (code, "must not be under skills/" in err, target.exists()))
        p = subprocess.run([sys.executable, str(ROOT / "studio.py"), "evals", "data-quality-audit", "--export", "agentskills", "--out", "skills/x-export-guard"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((2, True, False), (p.returncode, "must not be under skills/" in p.stderr, target.exists()))
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            (Path(t) / "skills").mkdir()
            code, findings, _ = studio.export_agentskills(folder, "demo-skill", Path(t) / "skills" / "demo-skill")
            self.assertEqual((2, False), (code, (Path(t) / "skills" / "demo-skill" / "evals").exists()))
        self.assertEqual(before, sorted(x.name for x in skills.iterdir()))

    def test_x_unsafe_fixture_names_refused(self):
        for bad in ("../cases.json", "fixtures/../cases.json", "fixtures/../../outside.txt"):
            with tempfile.TemporaryDirectory() as t:
                folder = self.make_eval(t)
                (Path(t) / "evals" / "outside.txt").write_text("x", encoding="utf-8")
                data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
                data["cases"][0]["fixtures"] = [bad]
                (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
                code, findings, stats = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
                self.assertEqual((1, 0, False), (code, stats["exported"], (Path(t) / "out").exists()), bad)
                self.assertTrue(findings, bad)

    def dir_link(self, link, target):
        """Directory symlink, or a junction on Windows without symlink rights; returns a cleanup callable or None when impossible."""
        # a link is removed as itself, never through its target: rmdir for a junction or directory symlink on Windows, unlink for a symlink on POSIX (rmdir fails there with NotADirectoryError)
        remove_link = os.rmdir if os.name == "nt" else os.unlink
        try:
            os.symlink(target, link, target_is_directory=True)
            return lambda: remove_link(link)
        except (OSError, NotImplementedError):
            pass
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return lambda: os.rmdir(link)
        return None

    def test_x_linked_fixture_dir_refused(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            real = folder / "real_fixtures"  # inside the eval folder, so check_evals accepts it and the export guard must catch the link
            (folder / "fixtures").rename(real)
            undo = self.dir_link(folder / "fixtures", real)
            if undo is None:
                self.skipTest("cannot create links here")
            try:
                code, findings, _ = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
                self.assertEqual((1, False), (code, (Path(t) / "out").exists()))
                self.assertTrue(any("symlink" in f["message"] for f in findings), findings)
            finally:
                undo()

    def test_x_force_overwrites_without_deleting_foreign_files(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            out = Path(t) / "out"
            self.assertEqual(0, studio.export_agentskills(folder, "demo-skill", out)[0])
            stray = out / "demo-skill" / "evals" / "files" / "mine.txt"
            stray.write_text("keep", encoding="utf-8")
            (out / "demo-skill" / "evals" / "files" / "a.csv").write_bytes(b"stale")
            self.assertEqual(1, studio.export_agentskills(folder, "demo-skill", out)[0])
            self.assertEqual(0, studio.export_agentskills(folder, "demo-skill", out, force=True)[0])
            self.assertEqual("keep", stray.read_text(encoding="utf-8"))
            self.assertEqual((folder / "fixtures" / "a.csv").read_bytes(), (out / "demo-skill" / "evals" / "files" / "a.csv").read_bytes())

    def test_x_force_refuses_overwriting_its_own_source(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            out = Path(t) / "out"
            (out / "demo-skill" / "evals").mkdir(parents=True)
            undo = self.dir_link(out / "demo-skill" / "evals" / "files", folder / "fixtures")
            if undo is None:
                self.skipTest("cannot create links here")
            try:
                before = (folder / "fixtures" / "a.csv").read_bytes()
                code, findings, _ = studio.export_agentskills(folder, "demo-skill", out, force=True)
                self.assertEqual((1, before), (code, (folder / "fixtures" / "a.csv").read_bytes()))
                self.assertTrue(any("symlink" in f["message"] for f in findings), findings)
            finally:
                undo()

    def test_x_same_file_destination_refused(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            out = Path(t) / "out"
            self.assertEqual(0, studio.export_agentskills(folder, "demo-skill", out)[0])
            with mock.patch.object(studio.os.path, "samefile", return_value=True):
                code, findings, _ = studio.export_agentskills(folder, "demo-skill", out, force=True)
            self.assertEqual((1, True), (code, any("source fixture itself" in f["message"] for f in findings)))

    def test_x_write_failure_is_reported(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            with mock.patch.object(studio.shutil, "copyfileobj", side_effect=OSError("disk full")):
                code, findings, stats = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
            self.assertEqual((1, 0, "EX8"), (code, stats["exported"], findings[0]["code"]))

    def test_x_fixture_name_collision_and_nested_names(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t, fixtures={"a.csv": b"1"})
            (folder / "a.csv").write_bytes(b"2")
            (folder / "fixtures" / "sub").mkdir()
            (folder / "fixtures" / "sub" / "n.csv").write_bytes(b"3")
            data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
            data["cases"][0]["fixtures"] = ["fixtures/a.csv", "a.csv"]
            data["cases"][1]["fixtures"] = ["fixtures/sub/n.csv"]
            (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
            code, findings, _ = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
            self.assertEqual((1, False), (code, (Path(t) / "out").exists()))
            self.assertTrue(any("collide" in f["message"] for f in findings))
            data["cases"][0]["fixtures"] = ["fixtures/a.csv"]
            (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
            code, _, stats = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
            self.assertEqual(0, code)
            self.assertEqual(b"3", (Path(t) / "out" / "demo-skill" / "evals" / "files" / "sub" / "n.csv").read_bytes())
            evals = json.loads(Path(stats["path"]).read_text(encoding="utf-8"))["evals"]
            self.assertEqual(["evals/files/sub/n.csv"], evals[1]["files"])

    def test_x_cli_flags_and_json_output(self):
        with tempfile.TemporaryDirectory() as t:
            self.make_eval(t)
            common = ("evals", "--all", "--eval-root", Path(t) / "evals")
            code, out, err = self.call(*common, "--out", Path(t) / "o")
            self.assertEqual(2, code)
            self.assertIn("--export", err)
            self.assertEqual(2, self.call(*common, "--force")[0])
            code, out, err = self.call(*common, "--export", "agentskills", "--out", Path(t) / "o", "--json")
            self.assertEqual(0, code, err)
            report = json.loads(out)
            self.assertEqual(0, report["model_runs_performed"])
            self.assertEqual([("demo-skill", 0, 2, 1)], [(r["skill"], r["exit"], r["stats"]["exported"], r["stats"]["excluded_negative"]) for r in report["reports"]])
            code, out, _ = self.call("evals", "--all", "--eval-root", Path(t) / "evals")
            self.assertEqual((0, True), (code, "Schema-only evaluation" in out))
            self.assertEqual(2, self.call("evals", "--export", "agentskills", "--eval-root", Path(t) / "evals")[0])
            self.assertEqual(2, self.call("evals", "--export", "bogus", "--all")[0])

    def test_x_bad_skill_name_refused(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            code, findings, _ = studio.export_agentskills(folder, "..", Path(t) / "out")
            self.assertEqual((1, False), (code, (Path(t) / "out").exists()))
            self.assertTrue(findings)

    def refused(self, folder, base, name="demo-skill"):
        code, findings, stats = studio.export_agentskills(folder, name, Path(base) / "out")
        self.assertFalse((Path(base) / "out").exists(), findings)
        return code, findings, stats

    def test_x_evals_json_bytes_exact(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            code, _, stats = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
            self.assertEqual(0, code)
            expected = {"skill_name": "demo-skill", "evals": [
                {"id": 1, "prompt": "Audit a.csv, tiếng Việt ok", "expected_output": "Reads a.csv; Reports rows", "files": ["evals/files/a.csv"], "assertions": ["Reads a.csv", "Reports rows"]},
                {"id": 2, "prompt": "Audit b.csv", "expected_output": "Handles UTF-8", "files": ["evals/files/a.csv", "evals/files/b.csv"], "assertions": ["Handles UTF-8"]},
            ]}
            raw = Path(stats["path"]).read_bytes()
            self.assertEqual((json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), raw)
            self.assertIn("tiếng Việt".encode("utf-8"), raw)
            self.assertNotIn(b"\r", raw)

    def test_x_draft_gate_each_half_refuses(self):
        def cases(prompt="Audit a.csv", behavior="Reads a.csv"):
            return [
                {"id": "c1", "kind": "typical", "prompt": prompt, "should_trigger": True, "fixtures": ["fixtures/a.csv"], "expected_behaviors": [behavior]},
                {"id": "c2", "kind": "edge", "prompt": "Audit b.csv", "should_trigger": True, "fixtures": ["fixtures/b.csv"], "expected_behaviors": ["Handles UTF-8"]},
                {"id": "c3", "kind": "near-miss", "prompt": "Explain CALCULATE", "should_trigger": False, "fixtures": [], "expected_behaviors": ["Does not trigger"]},
            ]
        variants = {
            "status draft only": dict(status="draft", cases=cases()),
            "marker text in prompt only": dict(status="frozen", cases=cases(prompt="<!-- STUDIO-DRAFT --> Audit a.csv")),
            "marker text in behaviors only": dict(status="frozen", cases=cases(behavior="STUDIO-DRAFT replace me")),
        }
        for label, kwargs in variants.items():
            with tempfile.TemporaryDirectory() as t:
                folder = self.make_eval(t, **kwargs)
                code, findings, stats = self.refused(folder, t)
                self.assertEqual((1, ["EX3"], 0), (code, [f["code"] for f in findings], stats["exported"]), label)
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(0, studio.export_agentskills(self.make_eval(t, status="frozen", cases=cases()), "demo-skill", Path(t) / "out")[0])

    def test_x_all_reports_worst_exit_whatever_the_order(self):
        for first, second in (("aaa-broken", "zzz-good"), ("aaa-good", "zzz-broken")):
            with tempfile.TemporaryDirectory() as t:
                for name in (first, second):
                    folder = self.make_eval(t, name=name)
                    if "broken" in name:
                        (folder / "cases.json").write_text("{not json", encoding="utf-8")
                common = ("evals", "--all", "--eval-root", Path(t) / "evals", "--export", "agentskills", "--out", Path(t) / "o")
                code, out, err = self.call(*common)
                self.assertEqual(1, code, (first, out, err))
                self.assertIn("broken", err)
                good = "aaa-good" if "good" in first else "zzz-good"
                self.assertTrue((Path(t) / "o" / good / "evals" / "evals.json").is_file())
                self.assertEqual(1, self.call(*common, "--json", "--force")[0])

    def test_x_cases_missing_keys_refused(self):
        def trio(*drop):
            rows = [
                {"id": "c1", "kind": "typical", "prompt": "Audit a.csv", "should_trigger": True, "fixtures": ["fixtures/a.csv"], "expected_behaviors": ["Reads a.csv"]},
                {"id": "c2", "kind": "edge", "prompt": "Audit b.csv", "should_trigger": True, "fixtures": ["fixtures/b.csv"], "expected_behaviors": ["Handles UTF-8"]},
                {"id": "c3", "kind": "near-miss", "prompt": "Explain CALCULATE", "should_trigger": False, "fixtures": [], "expected_behaviors": ["Does not trigger"]},
            ]
            for key in drop:
                del rows[0][key]
            return rows
        payloads = {
            "no cases key": {"skill_name": "demo-skill", "status": "frozen"},
            "case without expected_behaviors": {"skill_name": "demo-skill", "cases": trio("expected_behaviors")},
            "case without should_trigger": {"skill_name": "demo-skill", "cases": trio("should_trigger")},
            "case without prompt": {"skill_name": "demo-skill", "cases": trio("prompt")},
        }
        for label, payload in payloads.items():
            with tempfile.TemporaryDirectory() as t:
                folder = self.make_eval(t)
                (folder / "cases.json").write_text(json.dumps(payload), encoding="utf-8")
                code, findings, stats = self.refused(folder, t)
                self.assertEqual((1, 0, True), (code, stats["exported"], bool(findings)), label)
                self.assertEqual(1, self.call("evals", "demo-skill", "--eval-root", Path(t) / "evals", "--export", "agentskills", "--out", Path(t) / "out")[0], label)
                self.assertFalse((Path(t) / "out").exists(), label)

    def test_x_prompt_and_behavior_whitespace_preserved(self):
        prompt, behavior = "  Audit a.csv\n\t", " Reads a.csv "
        cases = [
            {"id": "c1", "kind": "typical", "prompt": prompt, "should_trigger": True, "fixtures": ["fixtures/a.csv"], "expected_behaviors": [behavior, "Reports rows"]},
            {"id": "c2", "kind": "edge", "prompt": "Audit b.csv", "should_trigger": True, "fixtures": ["fixtures/b.csv"], "expected_behaviors": ["Handles UTF-8"]},
            {"id": "c3", "kind": "near-miss", "prompt": "Explain CALCULATE", "should_trigger": False, "fixtures": [], "expected_behaviors": ["Does not trigger"]},
        ]
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t, cases=cases)
            code, _, stats = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
            self.assertEqual(0, code)
            first = json.loads(Path(stats["path"]).read_text(encoding="utf-8"))["evals"][0]
            self.assertEqual((prompt, " Reads a.csv ; Reports rows", [behavior, "Reports rows"]), (first["prompt"], first["expected_output"], first["assertions"]))

    def test_x_fixture_names_differing_only_in_case_or_unicode_form_collide(self):
        composed, decomposed = unicodedata.normalize("NFC", "é.csv"), unicodedata.normalize("NFD", "é.csv")
        pairs = {"case": ("a.csv", "A.csv"), "unicode form": (composed, decomposed), "case and form": (composed, unicodedata.normalize("NFD", "É.csv"))}
        for label, (inside, outside) in pairs.items():
            with tempfile.TemporaryDirectory() as t:
                folder = self.make_eval(t, fixtures={inside: b"1"})
                (folder / outside).write_bytes(b"2")  # a different file one level up, so a case-insensitive disk still holds both
                data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
                data["cases"][0]["fixtures"] = ["fixtures/" + inside, outside]
                data["cases"][1]["fixtures"] = []
                (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
                code, findings, _ = self.refused(folder, t)
                self.assertEqual((1, True), (code, any("collide" in f["message"] for f in findings)), label)

    def test_x_one_file_spelled_in_two_cases_with_different_case_collides(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t, fixtures={"a.csv": b"1"})
            if not (folder / "fixtures" / "A.csv").exists():
                self.skipTest("case-sensitive disk: A.csv is a different file here")
            data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
            data["cases"][0]["fixtures"] = ["fixtures/a.csv"]
            data["cases"][1]["fixtures"] = ["fixtures/A.csv"]  # same file on this disk, two exported names
            (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
            code, findings, _ = self.refused(folder, t)
            self.assertEqual((1, True), (code, any("collide" in f["message"] for f in findings)))

    def test_x_out_under_eval_root_refused(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            snapshot = sorted(str(x) for x in Path(t).rglob("*"))
            for out in (Path(t) / "evals", Path(t) / "evals" / "x", folder, folder / "sub"):
                code, findings, _ = studio.export_agentskills(folder, "demo-skill", out)
                self.assertEqual((2, True), (code, any("must not be under evals/" in f["message"] for f in findings)), str(out))
            self.assertEqual(snapshot, sorted(str(x) for x in Path(t).rglob("*")))
            old = os.getcwd()
            try:
                os.chdir(t)
                code, out, err = self.call("evals", "demo-skill", "--eval-root", "evals", "--export", "agentskills", "--out", "evals")
                self.assertEqual((2, True), (code, "must not be under evals/" in err), out + err)
                self.assertEqual(snapshot, sorted(str(x) for x in Path(t).rglob("*")))
                self.assertEqual(0, self.call("evals", "demo-skill", "--eval-root", "evals", "--export", "agentskills", "--out", "o")[0])
            finally:
                os.chdir(old)
            self.assertTrue((Path(t) / "o" / "demo-skill" / "evals" / "evals.json").is_file())

    def test_x_out_under_repo_evals_dir_refused_for_a_foreign_eval_root(self):
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t) / "repo"
            (repo / "standards").mkdir(parents=True)
            (repo / "standards" / "SKILL_AUTHORING_STANDARD.md").write_text("x", encoding="utf-8")
            (repo / "templates" / "skill-template").mkdir(parents=True)
            (repo / "templates" / "skill-template" / "SKILL.md").write_text("x", encoding="utf-8")
            (repo / "evals").mkdir()
            other = Path(t) / "other"
            other.mkdir()
            self.make_eval(other)
            old = os.getcwd()
            try:
                os.chdir(repo)
                code, out, err = self.call("evals", "demo-skill", "--eval-root", other / "evals", "--export", "agentskills", "--out", "evals/x")
                self.assertEqual((2, True, []), (code, "must not be under evals/" in err, list((repo / "evals").iterdir())), out + err)
            finally:
                os.chdir(old)

    def test_x_packaged_copy_refuses_out_inside_its_own_skill_dir(self):
        with tempfile.TemporaryDirectory() as t:
            self.make_eval(t)
            pkg = Path(t) / "pkg" / "skill-creator-studio"  # a copy whose parent is not named skills/
            shutil.copytree(ROOT / "skills" / "skill-creator-studio", pkg, ignore=shutil.ignore_patterns("__pycache__"))

            def run(out):
                return subprocess.run([sys.executable, "-X", "utf8", str(pkg / "scripts" / "studio.py"), "evals", "demo-skill", "--eval-root", str(Path(t) / "evals"), "--export", "agentskills", "--out", str(out)],
                                      cwd=t, text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            bad = run(pkg / "dist")
            self.assertEqual((2, True, False), (bad.returncode, "must not be under skills/" in bad.stderr, (pkg / "dist").exists()), bad.stderr)
            good = run(Path(t) / "out")
            self.assertEqual((0, True), (good.returncode, (Path(t) / "out" / "demo-skill" / "evals" / "evals.json").is_file()), good.stderr)

    def test_x_colon_in_fixture_name_refused(self):
        for bad in ("fixtures/a:b.csv", "fixtures/a.csv:hid", "C:fixtures/a.csv", "fixtures/dir:/a.csv"):
            source, parts, problem = studio.export_fixture_source(Path("."), bad)
            self.assertEqual((None, [], True), (source, parts, "unsafe fixture path" in problem), bad)
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t, fixtures={"a.csv": b"1", "b.csv": b"2"})
            try:
                with open(str(folder / "fixtures" / "a.csv") + ":hid", "wb") as handle:  # an NTFS alternate data stream on Windows
                    handle.write(b"hidden")
            except OSError:
                self.skipTest("cannot create a colon-named fixture here")
            data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
            data["cases"][0]["fixtures"] = ["fixtures/a.csv:hid"]
            data["cases"][1]["fixtures"] = []
            (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
            code, findings, _ = self.refused(folder, t)
            self.assertEqual((1, True), (code, any(f["code"] == "EX4" for f in findings)), findings)

    def test_x_failed_write_removes_files_this_run_created(self):
        from unittest import mock
        real = shutil.copyfileobj
        for label in ("second fixture fails", "evals.json fails"):
            with tempfile.TemporaryDirectory() as t:
                folder = self.make_eval(t)
                out = Path(t) / "out"
                files = out / "demo-skill" / "evals" / "files"
                self.assertEqual(0, studio.export_agentskills(folder, "demo-skill", out)[0])
                survivor = files / "b.csv"
                survivor.write_bytes(b"old")
                (files / "a.csv").unlink()
                (out / "demo-skill" / "evals" / "evals.json").unlink()
                calls = []

                def flaky(src, dst):
                    calls.append(dst)
                    if label.startswith("second") and len(calls) == 2:
                        raise OSError("disk full")
                    return real(src, dst)
                with mock.patch.object(studio.shutil, "copyfileobj", side_effect=flaky):
                    if label.startswith("evals"):
                        with mock.patch.object(studio.tempfile, "mkstemp", side_effect=OSError("denied")):
                            code, findings, stats = studio.export_agentskills(folder, "demo-skill", out, force=True)
                    else:
                        code, findings, stats = studio.export_agentskills(folder, "demo-skill", out, force=True)
                self.assertEqual((1, "EX8", 0), (code, findings[0]["code"], stats["exported"]), label)
                self.assertEqual(["b.csv"], sorted(x.name for x in out.rglob("*") if x.is_file()), label)  # only the file that existed before the run
                self.assertTrue(survivor.is_file(), label)


class ExportFixtureHardeningTests(unittest.TestCase):
    """The export must refuse a secret-named, zoned, linked or hard-linked fixture from names and lstat alone: no open, stat or copy of it, no file written."""

    call = AgentskillsExportTests.call
    make_eval = AgentskillsExportTests.make_eval

    def export_traced(self, folder, out, watch):
        """Run the export; return (code, findings, stats, touched) where touched lists every open/stat/copyfile aimed at a path whose last part is in `watch`."""
        import builtins
        from unittest import mock
        touched = []
        real_open, real_stat, real_path_stat, real_copy = builtins.open, os.stat, Path.stat, shutil.copyfile

        def seen(arg):
            try:
                return os.path.basename(os.fspath(arg)).lower() in watch
            except TypeError:
                return False

        def spy_open(file, *args, **kwargs):
            if seen(file):
                touched.append(("open", str(file)))
            return real_open(file, *args, **kwargs)

        def spy_stat(path, *args, **kwargs):
            if seen(path) and kwargs.get("follow_symlinks", True):  # stat(follow_symlinks=False) is lstat: metadata of the entry itself, allowed
                touched.append(("stat", str(path)))
            return real_stat(path, *args, **kwargs)

        def spy_path_stat(self, *args, **kwargs):
            if seen(self) and kwargs.get("follow_symlinks", True):
                touched.append(("Path.stat", str(self)))
            return real_path_stat(self, *args, **kwargs)

        def spy_copy(src, dst, *args, **kwargs):
            if seen(src):
                touched.append(("copyfile", str(src)))
            return real_copy(src, dst, *args, **kwargs)
        with mock.patch("builtins.open", spy_open), mock.patch.object(os, "stat", spy_stat), \
                mock.patch.object(Path, "stat", spy_path_stat), mock.patch.object(studio.shutil, "copyfile", spy_copy):
            code, findings, stats = studio.export_agentskills(folder, "demo-skill", out)
        return code, findings, stats, touched

    def one_fixture_eval(self, base, name, content=b"CANARY"):
        """An eval whose only positive case names fixtures/<name>."""
        folder = self.make_eval(base, fixtures={name: content})
        data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
        data["cases"][0]["fixtures"] = ["fixtures/" + name]
        data["cases"][1]["fixtures"] = []
        (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
        return folder

    def assert_refused_untouched(self, folder, base, watch, label):
        out = Path(base) / "out"
        code, findings, stats, touched = self.export_traced(folder, out, watch)
        self.assertEqual((1, "EX4", 0, []), (code, findings[0]["code"] if findings else "no finding", stats["exported"], touched), "%s: %s" % (label, findings))
        self.assertFalse(out.exists(), label)
        return findings

    def test_x_secret_named_fixture_refused_before_any_read(self):
        for name in (".env", ".env.local", ".ENV", "auth.json", "AUTH.JSON", "canary.pem", "canary.key", "canary.credentials.json", "credentials.json", "secrets.json", "id_rsa"):
            with tempfile.TemporaryDirectory() as t:
                folder = self.one_fixture_eval(t, name)
                findings = self.assert_refused_untouched(folder, t, {name.lower()}, name)
                self.assertIn("secret or credential name", findings[0]["message"], name)

    def test_x_innocent_look_alike_names_are_still_exported(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t, fixtures={"environment.csv": b"1", "authors.json": b"2", "pem.csv": b"3", "monkey.csv": b"4"})
            data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
            data["cases"][0]["fixtures"] = ["fixtures/environment.csv", "fixtures/authors.json"]
            data["cases"][1]["fixtures"] = ["fixtures/pem.csv", "fixtures/monkey.csv"]
            (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
            code, _, stats = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
            self.assertEqual((0, 2), (code, stats["exported"]))
            self.assertEqual(["authors.json", "environment.csv", "monkey.csv", "pem.csv"], sorted(x.name for x in (Path(t) / "out" / "demo-skill" / "evals" / "files").iterdir()))

    def test_x_secret_named_fixture_in_a_negative_case_is_refused_too(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.one_fixture_eval(t, "a.csv")
            (folder / "fixtures" / "auth.json").write_bytes(b"CANARY")
            data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
            data["cases"][2]["fixtures"] = ["fixtures/auth.json"]  # c3 is a should_trigger false case: check_evals would still stat it
            (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
            self.assert_refused_untouched(folder, t, {"auth.json"}, "negative case")

    def test_x_fixture_folder_named_like_a_zone_refused(self):
        for zone in (".secret", ".SECRET", "OneDrive - X", "sharepoint-sync"):
            with tempfile.TemporaryDirectory() as t:
                folder = self.one_fixture_eval(t, "a.csv")
                (folder / "fixtures" / zone).mkdir()
                (folder / "fixtures" / zone / "canary.csv").write_bytes(b"CANARY")
                data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
                data["cases"][0]["fixtures"] = ["fixtures/%s/canary.csv" % zone]
                (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
                findings = self.assert_refused_untouched(folder, t, {"canary.csv"}, zone)
                self.assertIn("secret or cloud-synced zone", findings[0]["message"], zone)

    def test_x_eval_folder_inside_a_zone_refused_without_reading_cases_json(self):
        for zone in ("OneDrive - X", ".secret"):
            with tempfile.TemporaryDirectory() as t:
                base = Path(t) / zone
                base.mkdir()
                folder = self.make_eval(base, fixtures={"canary.csv": b"CANARY"})
                data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
                data["cases"][0]["fixtures"] = ["fixtures/canary.csv"]
                data["cases"][1]["fixtures"] = []
                (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
                findings = self.assert_refused_untouched(folder, t, {"canary.csv", "cases.json"}, zone)
                self.assertIn("eval folder is inside", findings[0]["message"], zone)

    def test_x_eval_folder_under_a_fake_home_secret_refused(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "home"
            (home / ".secret").mkdir(parents=True)
            studio._secret_dirs.cache_clear()
            try:
                with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                    self.assertEqual("secret-zone", studio.zone_reason(home / ".secret" / "e"))
                    folder = self.make_eval(home / ".secret", fixtures={"canary.csv": b"CANARY"})
                    data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
                    data["cases"][0]["fixtures"] = ["fixtures/canary.csv"]
                    data["cases"][1]["fixtures"] = []
                    (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
                    self.assert_refused_untouched(folder, t, {"canary.csv", "cases.json"}, "fake HOME/.secret")
            finally:
                studio._secret_dirs.cache_clear()

    def test_x_cloud_placeholder_or_resolved_zone_refused(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            folder = self.one_fixture_eval(t, "canary.csv")
            with mock.patch.object(studio, "path_is_cloud", lambda path: os.path.basename(os.fspath(path)) == "canary.csv"):
                findings = self.assert_refused_untouched(folder, t, {"canary.csv"}, "placeholder")
            self.assertIn("cloud placeholder", findings[0]["message"])
        with tempfile.TemporaryDirectory() as t:
            folder = self.one_fixture_eval(t, "canary.csv")
            real_realpath = os.path.realpath

            def through_a_junction(path, *args, **kwargs):  # the fixtures folder "resolves" into a synced folder although no spelling in cases.json says so
                found = real_realpath(path, *args, **kwargs)
                return os.path.join(os.path.dirname(found), "OneDrive - Y") if os.path.basename(found) == "fixtures" else found
            with mock.patch.object(os.path, "realpath", through_a_junction):
                findings = self.assert_refused_untouched(folder, t, {"canary.csv"}, "resolved zone")
            self.assertIn("resolves into", findings[0]["message"])

    def test_x_symlink_and_hard_link_fixtures_refused(self):
        with tempfile.TemporaryDirectory() as t:
            outside = Path(t) / "outside.csv"
            outside.write_bytes(b"CANARY")
            folder = self.one_fixture_eval(t, "x.csv")
            (folder / "fixtures" / "x.csv").unlink()
            link = folder / "fixtures" / "canary.csv"
            try:
                os.link(outside, link)
            except OSError:
                self.skipTest("hard links are not available here")
            data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
            data["cases"][0]["fixtures"] = ["fixtures/canary.csv"]
            (folder / "cases.json").write_text(json.dumps(data), encoding="utf-8")
            findings = self.assert_refused_untouched(folder, t, {"canary.csv"}, "hard link")
            self.assertIn("hard link", findings[0]["message"])
            link.unlink()
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError):
                return
            findings = self.assert_refused_untouched(folder, t, {"canary.csv"}, "symlink")
            self.assertIn("symlink or junction", findings[0]["message"])

    def test_x_fixture_source_refuses_by_spelling_alone(self):
        # the per-fixture entry point (also used by the export loop) must not need the eval-level pre-pass: it decides from names, nothing exists on disk here
        with tempfile.TemporaryDirectory() as t:
            for zone in ("OneDrive - X", ".secret", "SharePoint"):
                source, parts, problem = studio.export_fixture_source(Path(t) / zone / "evals" / "demo-skill", "fixtures/a.csv")
                self.assertEqual((None, [], True), (source, parts, "inside a secret or cloud-synced folder" in problem), zone)
            for name in (".env", "auth.json", "k.pem"):
                source, _, problem = studio.export_fixture_source(Path(t) / "e", "fixtures/" + name)
                self.assertEqual((None, True), (source, "secret or credential name" in problem), name)
            self.assertEqual("missing/outside eval fixture 'fixtures/a.csv'", studio.export_fixture_source(Path(t) / "e", "fixtures/a.csv")[2])

    def test_x_cases_json_that_is_not_valid_still_reports_ev1(self):
        with tempfile.TemporaryDirectory() as t:
            folder = self.make_eval(t)
            (folder / "cases.json").write_text("{not json", encoding="utf-8")
            code, findings, _ = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
            self.assertEqual((1, "EV1"), (code, findings[0]["code"]), findings)


class ExportWindowsNameAndRaceTests(unittest.TestCase):
    """SPR-01 TK2: Windows name aliases, normalised names, TOCTOU on the source, atomic evals.json. Labels: bắt-lỗi (red before the fix, goes through
    the CLI or functions that already exist at df875ce) and đơn-vị-hàm-mới (the new helpers)."""

    call = AgentskillsExportTests.call
    make_eval = AgentskillsExportTests.make_eval

    def named_eval(self, base, names, fixtures=None):
        folder = self.make_eval(base, fixtures=fixtures or {"a.csv": b"1"})
        data = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
        data["cases"][0]["fixtures"] = list(names)
        data["cases"][1]["fixtures"] = []
        (folder / "cases.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return folder

    def cli_export(self, base, *extra):
        return self.call("evals", "demo-skill", "--eval-root", Path(base) / "evals", "--export", "agentskills", "--out", Path(base) / "out", *extra)

    def test_bat_loi_seven_aliases_refused_with_their_own_code(self):
        """bắt-lỗi: the 7 aliases of dossier 3a, by CLI."""
        expected = {"auth.json.": "EX9", "auth.json ": "EX9", "secrets.json ": "EX9", "k.pem.": "EX9", "AUTH~1.JSO": "EX11", "CON": "EX10", "NUL": "EX10"}
        for alias, code in expected.items():
            with tempfile.TemporaryDirectory() as t:
                self.named_eval(t, ["fixtures/" + alias])
                rc, out, err = self.cli_export(t)
                self.assertEqual((1, True, False), (rc, code in out + err, (Path(t) / "out").exists()), (alias, out + err))

    def test_bat_loi_combined_aliases_and_device_parent(self):
        """bắt-lỗi: combined aliases and a device name as a parent component."""
        expected = {"AUTH~1.JSO.": "EX9", "con.txt ": "EX9", "nul.csv": "EX10", "CONIN$": "EX10", "COM¹.csv": "EX10", "con/x.csv": "EX10", "dir./x.csv": "EX9"}
        for alias, code in expected.items():
            with tempfile.TemporaryDirectory() as t:
                self.named_eval(t, ["fixtures/" + alias])
                rc, out, err = self.cli_export(t)
                self.assertEqual((1, True, False), (rc, code in out + err, (Path(t) / "out").exists()), (alias, out + err))

    def test_bat_loi_nfd_name_written_as_nfc_keeping_case(self):
        """bắt-lỗi: regression RF7 - disk name == files entry == NFC, case kept."""
        nfd = unicodedata.normalize("NFD", "Dữ liệu.csv")
        nfc = unicodedata.normalize("NFC", nfd)
        with tempfile.TemporaryDirectory() as t:
            try:
                self.named_eval(t, ["fixtures/Data.csv", "fixtures/" + nfd], fixtures={"Data.csv": b"1", nfd: b"2"})
            except OSError:
                self.skipTest("cannot create an NFD-named file here")
            rc, out, err = self.cli_export(t)
            self.assertEqual(0, rc, out + err)
            files = Path(t) / "out" / "demo-skill" / "evals" / "files"
            listed = sorted(os.listdir(files))
            data = json.loads((files.parent / "evals.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(["Data.csv", nfc]), listed)
            self.assertEqual(sorted(["evals/files/Data.csv", "evals/files/" + nfc]), sorted(data["evals"][0]["files"]))

    def test_bat_loi_file_and_directory_collide(self):
        """bắt-lỗi: fixture `x` and `x/y.csv` cannot both be exported."""
        with tempfile.TemporaryDirectory() as t:
            folder = self.named_eval(t, ["fixtures/x", "x/y.csv"], fixtures={"x": b"1"})
            (folder / "x").mkdir()
            (folder / "x" / "y.csv").write_bytes(b"2")
            rc, out, err = self.cli_export(t)
            self.assertEqual((1, True, False), (rc, "EX12" in out + err, (Path(t) / "out").exists()), out + err)

    def swap_during_export(self, t, make_swap):
        """Run the export; the moment it first asks is_link about the destination (after it checked the source), swap the source."""
        from unittest import mock
        folder = self.named_eval(t, ["fixtures/a.csv"], fixtures={"a.csv": b"SAFE"})
        source = folder / "fixtures" / "a.csv"
        outside = Path(t) / "outside.csv"
        outside.write_bytes(b"CANARY")
        real, done = studio.is_link, []

        def spy(path):
            if not done and os.path.basename(os.fspath(path)) == "demo-skill" and "out" in Path(path).parts:
                done.append(1)
                source.unlink()
                make_swap(source, outside)
            return real(path)
        with mock.patch.object(studio, "is_link", spy):
            result = studio.export_agentskills(folder, "demo-skill", Path(t) / "out")
        self.assertTrue(done, "swap hook never fired")
        return result

    def assert_no_canary(self, t):
        for p in (Path(t) / "out").rglob("*"):
            if p.is_file():
                self.assertNotIn(b"CANARY", p.read_bytes(), str(p))

    def test_bat_loi_source_swapped_for_symlink_refused(self):
        """bắt-lỗi: TOCTOU, source becomes a symlink between check and copy."""
        def swap(source, outside):
            try:
                os.symlink(outside, source)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available here")
        with tempfile.TemporaryDirectory() as t:
            code, findings, stats = self.swap_during_export(t, swap)
            self.assert_no_canary(t)
            self.assertEqual((1, 0), (code, stats["exported"]), findings)

    def test_bat_loi_source_swapped_for_hard_link_refused(self):
        """bắt-lỗi: TOCTOU, source becomes a hard link between check and copy."""
        def swap(source, outside):
            try:
                os.link(outside, source)
            except OSError:
                self.skipTest("hard links are not available here")
        with tempfile.TemporaryDirectory() as t:
            code, findings, stats = self.swap_during_export(t, swap)
            self.assert_no_canary(t)
            self.assertEqual((1, 0), (code, stats["exported"]), findings)

    def test_bat_loi_force_is_atomic_for_evals_json(self):
        """bắt-lỗi: --force with os.replace failing keeps the old evals.json byte for byte and leaves no temp file."""
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            self.make_eval(t)
            self.assertEqual(0, self.cli_export(t)[0])
            target = Path(t) / "out" / "demo-skill" / "evals" / "evals.json"
            target.write_text("OLD-CONTENT\n", encoding="utf-8")
            with mock.patch.object(os, "replace", side_effect=OSError("boom")):
                rc, out, err = self.cli_export(t, "--force")
            self.assertEqual((1, "OLD-CONTENT\n"), (rc, target.read_text(encoding="utf-8")), out + err)
            self.assertEqual(["evals.json"], [x for x in os.listdir(target.parent) if x != "files"])

    def test_don_vi_ham_moi_unsafe_windows_name(self):
        """đơn-vị-hàm-mới: unsafe_windows_name."""
        bad = ["a.", "a ", "CON", "con", "Nul.txt", "aux.csv", "COM1", "lpt9.x", "COM²", "LPT³.csv", "CONIN$", "conout$", "CLOCK$", "AUTH~1.JSO", "a~12", "a:b", "PRN "]
        for name in bad:
            self.assertTrue(studio.unsafe_windows_name(name), name)
        for name in ["a.csv", "Data.csv", "console.csv", "com10", "com", "lpt0", "x~y", "Dữ liệu.csv", "confile", "a b.csv"]:
            self.assertIsNone(studio.unsafe_windows_name(name), name)

    def test_don_vi_ham_moi_open_nofollow_read_and_create_exclusive(self):
        """đơn-vị-hàm-mới: open_nofollow_read / create_exclusive."""
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "f.bin"
            with studio.create_exclusive(f) as handle:
                handle.write(b"abc")
            with self.assertRaises(FileExistsError):
                studio.create_exclusive(f)
            with studio.open_nofollow_read(f, os.lstat(f)) as handle:
                self.assertEqual(b"abc", handle.read())
            other = Path(t) / "g.bin"
            other.write_bytes(b"zzz")
            with self.assertRaises(OSError):
                studio.open_nofollow_read(f, os.lstat(other))  # a different identity than the one checked
            try:
                os.link(f, Path(t) / "h.bin")
            except OSError:
                pass
            else:
                with self.assertRaises(OSError):
                    studio.open_nofollow_read(f, os.lstat(f))  # two names
            link = Path(t) / "l.bin"
            try:
                os.symlink(other, link)
            except (OSError, NotImplementedError):
                return
            with self.assertRaises(OSError):
                studio.open_nofollow_read(link, os.lstat(link))  # a symlink source is refused on every OS: the handle is the target's, the lstat is the link's
            with self.assertRaises(OSError):
                studio.create_exclusive(link)

    def test_bat_loi_create_exclusive_refuses_any_existing_name_even_a_link(self):
        """bắt-lỗi: a name that lexists (a dangling symlink on Windows, where O_EXCL follows it) is never opened; no handle, no file."""
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            target = Path(t) / "victim.bin"
            with mock.patch.object(os.path, "lexists", return_value=True):
                with self.assertRaises(FileExistsError):
                    studio.create_exclusive(target)
            self.assertFalse(target.exists())

    def test_bat_loi_create_exclusive_rejects_a_handle_that_is_not_the_named_path(self):
        """bắt-lỗi: after the open, fstat(fd) must match lstat(path); an lstat that is a link (or another file) closes the handle and raises."""
        from unittest import mock
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "f.bin"
            as_link = os.stat_result((stat.S_IFLNK | 0o777, 1, 1, 1, 0, 0, 0, 0, 0, 0))
            with mock.patch.object(os.path, "lexists", return_value=False), mock.patch.object(os, "lstat", return_value=as_link):  # lexists calls lstat: pin it
                with self.assertRaises(studio.UnsafeOpen):
                    studio.create_exclusive(f)
            self.assertEqual(0, f.stat().st_size if f.exists() else 0)  # nothing was written
            f.unlink(missing_ok=True)
            other = os.stat_result((stat.S_IFREG | 0o666, 987654321, 1, 1, 0, 0, 0, 0, 0, 0))
            with mock.patch.object(os.path, "lexists", return_value=False), mock.patch.object(os, "lstat", return_value=other):
                with self.assertRaises(studio.UnsafeOpen):
                    studio.create_exclusive(f)


if __name__ == "__main__":
    unittest.main()
