"""SPR-04 TK7 (FR6.1, FR6.2, SC8): `doctor --by-pack` groups findings by pack and previews the ST5 and ST8 impact.

Run: python -X utf8 -m unittest tests.test_by_pack -v
"""
from __future__ import annotations

import io
import os
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402

doctor = _engine.doctor


def write_skill(root: Path, name: str, extra: str = "") -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_bytes(("---\nname: %s\ndescription: Checks a toy. Use when testing packs.\n---\n\n# Title\n\nShort body.\n%s" % (name, extra)).encode("utf-8"))
    return folder


def write_plugin(base: Path, folder: str, name: str, skills: list) -> Path:
    plugin = base / folder
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    for skill in skills:
        write_skill(plugin / "skills", skill)
    return plugin


def long_reference(skill: Path) -> None:
    ref = skill / "references"
    ref.mkdir(exist_ok=True)
    (ref / "big.md").write_text("# Big\n\n" + "".join("line %d of the reference\n" % i for i in range(150)), encoding="utf-8")


class ByPackTests(unittest.TestCase):
    def test_packs_sum_matches_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root / "alpha", "one")
            write_skill(root / "alpha", "two")
            weird = write_skill(root / "beta", "three")
            (weird / "oddfolder").mkdir()
            report = doctor.doctor_run([root], "portable", "portable", False, None, by_pack=True)
            packs = {p["pack"]: p for p in report["packs"]}
            self.assertEqual(sum(p["skills"] for p in report["packs"]), report["totals"]["skills"])
            self.assertEqual(sum(p["errors"] for p in report["packs"]), report["totals"]["errors"])
            self.assertEqual(sum(p["warnings"] for p in report["packs"]), report["totals"]["warnings"])
            self.assertEqual(packs["alpha"]["skills"], 2)
            self.assertEqual(packs["beta"]["by_code"].get("ST8"), 1)
            self.assertNotIn("packs", doctor.doctor_run([root], "portable", "portable", False, None))

    def test_pack_name_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            plugin = write_plugin(base, "folder-name", "manifest-name", ["one"])
            report = doctor.doctor_run([plugin / "skills"], "portable", "portable", False, None, by_pack=True)
            self.assertEqual([p["pack"] for p in report["packs"]], ["manifest-name"])
            # An explicit mapping (what --roots-from opcos hands over) wins over the walk up.
            scanned = ([plugin / "skills" / "one"], [])
            mapped = doctor.doctor_run([plugin / "skills"], "portable", "portable", False, None, scanned=scanned,
                                       by_pack=True, pack_of={os.path.normcase(str(plugin / "skills" / "one")): "given"})
            self.assertEqual([p["pack"] for p in mapped["packs"]], ["given"])

    def test_st8_evals_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plain = write_skill(root / "gamma", "plain")
            withevals = write_skill(root / "gamma", "withevals")
            (withevals / "evals").mkdir()
            long_reference(plain)
            report = doctor.doctor_run([root], "portable", "portable", False, None, by_pack=True)
            pack = report["packs"][0]
            self.assertEqual(pack["st8_evals"], 1)
            self.assertEqual(pack["by_code"].get("ST5"), 1)
            self.assertIn("ST5 1", doctor.pack_line(pack))
            self.assertIn("ST8 1)", doctor.pack_line(pack))

    def test_check_exit_follows_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root / "ok", "fine")
            broken = root / "bad" / "broken"
            broken.mkdir(parents=True)
            (broken / "SKILL.md").write_bytes(b"no frontmatter here\n")
            report = doctor.doctor_run([root], "portable", "portable", False, None, by_pack=True)
            exits = {p["pack"]: p["check_exit"] for p in report["packs"]}
            self.assertEqual(exits, {"ok": 0, "bad": 1})
            line = doctor.pack_line(next(p for p in report["packs"] if p["pack"] == "bad"))
            self.assertRegex(line, r"^bad: 1 skills, \d+ errors \(ST5 0\), \d+ warnings \(ST8 0\); check exits 1$")

    def test_text_output_lists_each_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root / "alpha", "one")
            args = type("A", (), dict(roots=str(root), roots_file=None, roots_from=None, profile="portable", target="portable", include_cache=False,
                                      skip_marker=None, baseline=None, json=False, out=None, fail_on="error", by_pack=True))()
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = doctor.cmd_doctor(args)
            self.assertEqual(code, 0)
            self.assertIn("alpha: 1 skills, 0 errors (ST5 0), 0 warnings (ST8 0); check exits 0", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
