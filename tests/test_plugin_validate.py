"""SPR-03 TK7 (FR6.1, SC4): `claude plugin validate --json .` reports no error and no warning other than the accepted one.

The accepted warning is the one Claude Code prints for a root `CLAUDE.md` (the owner kept it at the root at Gate 1). The real run is
skipped when `claude` is not on PATH (CI has none); the evaluation itself is unit-tested on synthetic reports and always runs.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTED_WARNING = "CLAUDE.md at the plugin root"


def problems(report: dict) -> list:
    """What makes a validate report unacceptable. Exactly two things are accepted (SPEC mục 5, SC4): the `CLAUDE.md at the plugin root`
    warning once, in the contents entry of type `plugin`; and directory findings of code ICON_MISSING that do not block. Anything else is a problem."""
    found = []
    if report.get("success") is not True:
        found.append("success is not true")
    sections = [("manifest", report.get("manifest") or {})]
    sections += [("contents[%d] %s" % (i, item.get("file")), item) for i, item in enumerate(report.get("contents") or [])]
    accepted = 0
    for label, section in sections:
        for error in section.get("errors") or []:
            found.append("%s error: %s" % (label, error))
        for warning in section.get("warnings") or []:
            message = warning.get("message", "") if isinstance(warning, dict) else str(warning)
            if message.startswith(ACCEPTED_WARNING) and section.get("type") == "plugin":
                accepted += 1
            else:
                found.append("%s warning: %s" % (label, message))
    if accepted != 1:
        found.append("the '%s' warning must appear exactly once in a plugin contents entry, found %d" % (ACCEPTED_WARNING, accepted))
    for finding in (report.get("directory") or {}).get("findings") or []:
        if finding.get("code") != "ICON_MISSING" or finding.get("blocking") is True:
            found.append("directory finding not accepted: %s (blocking=%s)" % (finding.get("code"), finding.get("blocking")))
    return found


class PluginValidateTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("claude") is None, "claude is not on PATH (CI): the real validate run is skipped")
    def test_plugin_validate(self):
        claude = shutil.which("claude")  # on Windows this may be a .cmd; use exactly what `which` returns
        result = subprocess.run([claude, "plugin", "validate", "--json", "."], shell=False, capture_output=True, text=True,
                                encoding="utf-8", cwd=str(ROOT), timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(problems(json.loads(result.stdout)), [])

    def test_accepts_only_the_root_claude_md_warning(self):
        ok = {"success": True, "manifest": {"errors": [], "warnings": []},
              "contents": [{"file": "CLAUDE.md", "type": "plugin", "errors": [], "warnings": [
                  {"path": "root", "message": ACCEPTED_WARNING + " is not loaded as project context. To ship...", "code": None}]}],
              "directory": {"findings": [{"code": "ICON_MISSING", "severity": "warning", "blocking": False}]}}
        self.assertEqual(problems(ok), [])

    def test_accepts_exactly_one_root_claude_md_warning_and_only_icon_missing(self):
        # Round 1: the accepted set is exact. The CLAUDE.md warning appears once, in the plugin's contents; the only directory finding is ICON_MISSING.
        warning = {"path": "root", "message": ACCEPTED_WARNING + " is not loaded as project context.", "code": None}
        base = {"success": True, "manifest": {"errors": [], "warnings": []},
                "contents": [{"file": "CLAUDE.md", "type": "plugin", "errors": [], "warnings": [warning]}],
                "directory": {"findings": [{"code": "ICON_MISSING", "blocking": False}]}}
        self.assertEqual(problems(base), [])
        twice = json.loads(json.dumps(base))
        twice["contents"][0]["warnings"].append(warning)
        self.assertTrue(problems(twice), "the CLAUDE.md warning twice must be red")
        twice_sections = json.loads(json.dumps(base))
        twice_sections["contents"].append(json.loads(json.dumps(base["contents"][0])))
        self.assertTrue(problems(twice_sections), "the CLAUDE.md warning in two contents entries must be red")
        in_manifest = json.loads(json.dumps(base))
        in_manifest["manifest"]["warnings"].append(warning)
        self.assertTrue(problems(in_manifest), "the CLAUDE.md warning in the manifest must be red")
        absent = json.loads(json.dumps(base))
        absent["contents"][0]["warnings"] = []
        self.assertTrue(problems(absent), "the accepted warning must be there exactly once")
        other = json.loads(json.dumps(base))
        other["directory"]["findings"].append({"code": "X_OTHER", "severity": "warning", "blocking": False})
        self.assertTrue(problems(other), "a non-blocking finding other than ICON_MISSING must be red")
        icon_blocking = json.loads(json.dumps(base))
        icon_blocking["directory"]["findings"][0]["blocking"] = True
        self.assertTrue(problems(icon_blocking))

    def test_rejects_errors_other_warnings_and_blocking_findings(self):
        base = {"success": True, "manifest": {"errors": [], "warnings": []}, "directory": {"findings": []},
                "contents": [{"file": "CLAUDE.md", "type": "plugin", "errors": [], "warnings": [{"message": ACCEPTED_WARNING + " is not loaded."}]}]}
        self.assertEqual(problems(base), [])
        for mutate in (
            lambda r: r["manifest"]["errors"].append({"message": "bad"}),
            lambda r: r["manifest"]["warnings"].append({"message": "something else"}),
            lambda r: r["contents"].append({"file": "x", "errors": [{"message": "bad"}], "warnings": []}),
            lambda r: r["contents"].append({"file": "x", "errors": [], "warnings": [{"message": "Some other CLAUDE.md warning"}]}),
            lambda r: r["directory"]["findings"].append({"code": "X", "blocking": True}),
            lambda r: r.update(success=False),
        ):
            report = json.loads(json.dumps(base))
            mutate(report)
            self.assertTrue(problems(report), report)


if __name__ == "__main__":
    unittest.main()
