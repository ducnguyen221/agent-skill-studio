"""Offline tests for Studio manifest, CLI, package and install.

Run: python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import re
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
                    continue
                if row is not None:
                    for key, ok, text in AB_THRESHOLDS:
                        if not ok(row.get(key, -1)):
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


def _fake_evidence(base, write_ab=True, drop_harness=None, extra_runtime=None, status=None, model_evaluated=True, claim_positive=4, mutate=None, flag=None):
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
                {"runtime": rt, "case_id": "pos%d" % i, "with_skill": True, "status": "ran", "kind": "typical", "triggered": i < 4}), encoding="utf-8")
            (runs / ("%s_base%d.json" % (rt, i))).write_text(json.dumps(
                {"runtime": rt, "case_id": "pos%d" % i, "with_skill": False, "status": "ran", "kind": "typical", "triggered": False}), encoding="utf-8")
        for i in range(3):
            (runs / ("%s_neg%d.json" % (rt, i))).write_text(json.dumps(
                {"runtime": rt, "case_id": "neg%d" % i, "with_skill": True, "status": "ran", "kind": "near-miss", "triggered": False}), encoding="utf-8")
    row = lambda: {"positive_triggered": claim_positive, "negative_triggered": 0, "better": 3, "equal": 2, "worse": 0, "pairs": 5}
    ab = {"per_runtime": {"claude-code": row(), "codex": row()}}
    harnesses = {"claude-code": "ran", "codex": "ran", "antigravity": "not_run:headless-no-skill-catalog"}
    if drop_harness:
        del harnesses[drop_harness]
    if status is None:
        status = "model-evaluated" if model_evaluated else "prototype-static-validated"
    evaluated = {"sprint": "SPR-18", "date": "2026-10-18", "harnesses": harnesses,
                 "ab_report": "evals/fake-skill/runs/SPR-18/ab-2026-10-18.md"}
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
        return subprocess.run([sys.executable, str(ROOT / "studio.py"), *map(str, args)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

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


if __name__ == "__main__":
    unittest.main()
