"""Rules for the engine's sibling modules `skills/skill-creator-studio/scripts/studio_*.py` (SPR-02 TK4a, SPEC FR4.5, ADR-0001).

Run: python -X utf8 -m pytest tests/test_engine_modules.py -q -p no:cacheprovider
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402
from _batches import activation  # noqa: E402

E = _engine

ENGINE_DIR = _engine.ENGINE_DIR
ENGINE_PATH = _engine.ENGINE_PATH
MODULES = sorted(ENGINE_DIR.glob("studio_*.py"))


def _top_level_definitions(tree: ast.Module) -> set:
    """Names a module defines at its top level with def, class or assignment (imports do not count)."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
    return names


def _top_level_bindings(tree: ast.Module) -> set:
    """Every name bound at the top level, imports included."""
    names = _top_level_definitions(tree)
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
    return names


def _public(names) -> set:
    return {n for n in names if not n.startswith("_")}


# The child loads an engine from A, then, in the same process, a copy of the engine from B.
CHILD = (
    "import importlib.util, sys\n"
    "def load(path, name):\n"
    "    spec = importlib.util.spec_from_file_location(name, path)\n"
    "    module = importlib.util.module_from_spec(spec)\n"
    "    spec.loader.exec_module(module)\n"
    "load(sys.argv[1], 'engine_a'); print('A-LOADED', flush=True)\n"
    "load(sys.argv[2], 'engine_b'); print('B-LOADED', flush=True)\n"
)


class EngineModuleRulesTests(unittest.TestCase):
    def test_there_are_sibling_modules_to_check(self):
        """tương-đương: the glob finds the sibling modules, so the rules below are not checked on an empty list."""
        self.assertTrue(ENGINE_PATH.is_file())
        names = {p.name for p in MODULES}
        self.assertTrue({"studio_const.py", "studio_fs.py"} <= names, sorted(names))

    def test_sibling_modules_do_not_import_each_other_by_name_or_the_engine(self):
        """tương-đương: no `from studio_* import`, no `import studio`, no relative import, and `from __future__ import annotations` first (FR4.5, Python 3.9)."""
        for path in MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            body = list(tree.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                body = body[1:]  # the module docstring
            self.assertTrue(body and isinstance(body[0], ast.ImportFrom) and body[0].module == "__future__"
                            and [a.name for a in body[0].names] == ["annotations"],
                            "%s must open with `from __future__ import annotations`" % path.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    self.assertEqual(node.level, 0, "%s: relative import" % path.name)
                    self.assertFalse(module == "studio" or module.startswith("studio_"),
                                     "%s: `from %s import ...` (call through the module object instead)" % (path.name, module))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(alias.name, "studio", "%s: `import studio`" % path.name)

    def test_engine_does_not_re_export_names_of_the_sibling_modules(self):
        """tương-đương: the engine file defines or imports no public name that a sibling module defines (a patch on the engine must fail, not pass for nothing)."""
        engine_tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
        engine_names = _public(_top_level_bindings(engine_tree))
        for path in MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            clash = engine_names & _public(_top_level_definitions(tree))
            self.assertEqual(clash, set(), "studio.py re-exports names of %s" % path.name)
        for node in ast.walk(engine_tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith("studio_"), "studio.py: from-import of a sibling module")
                self.assertNotIn("*", [a.name for a in node.names])

    def test_loaded_engine_has_no_attribute_of_the_sibling_modules(self):
        """tương-đương: on the loaded engine object, patching a name that moved raises AttributeError."""
        moved = set()
        for path in MODULES:
            moved |= _public(_top_level_definitions(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
        self.assertGreater(len(moved), 100)
        present = sorted(n for n in moved if hasattr(_engine.engine, n))
        self.assertEqual(present, [])


class EngineIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="studio-ident-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.a = self.tmp / "a" / "scripts"
        self.b = self.tmp / "b" / "scripts"
        for target in (self.a, self.b):
            shutil.copytree(ENGINE_DIR, target, ignore=shutil.ignore_patterns("__pycache__"))

    def run_child(self, first, second):
        return subprocess.run([sys.executable, "-X", "utf8", "-c", CHILD, str(first / "studio.py"), str(second / "studio.py")],
                              capture_output=True, text=True, timeout=60)

    def test_second_engine_from_another_folder_in_one_process_exits_2(self):
        """bắt-lỗi: an engine copy loaded after another one from a different folder, in the same process, exits 2 and names the module and both folders (RF25)."""
        done = self.run_child(self.a, self.b)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("A-LOADED", done.stdout)
        self.assertNotIn("B-LOADED", done.stdout)
        self.assertIn("ERROR: engine module studio_", done.stderr)
        self.assertIn("loaded from", done.stderr)
        self.assertIn(", expected ", done.stderr)

    def test_same_engine_loaded_twice_from_one_folder_is_fine(self):
        """tương-đương: loading the engine twice from the same folder passes the identity check."""
        done = self.run_child(self.a, self.a)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("B-LOADED", done.stdout)


class Rq029EngineTests(unittest.TestCase):
    """SPR-04 TK2 (FR11.1, FR11.2, RQ-029): the activation tool checks every engine module, and the catalog gate does not look through a linked evals folder."""

    def test_rq029_engine_checks_every_sibling_module(self):
        """bắt-lỗi (red at c3deee2: `_engine()` returns the module, no EngineMismatch): FR11.1 a `studio_*` sibling loaded from another folder is a mismatch, not only `studio_evals`."""
        other = Path(tempfile.mkdtemp(prefix="studio-alien-")).resolve()
        self.addCleanup(shutil.rmtree, other, True)
        alien = types.ModuleType("studio_fs")
        alien.__file__ = str(other / "studio_fs.py")
        with mock.patch.object(sys, "path", list(sys.path)), mock.patch.dict(sys.modules, {"studio_fs": alien}):
            with self.assertRaises(activation.EngineMismatch) as caught:
                activation._engine()
        self.assertIn("studio_fs", str(caught.exception))
        self.assertIn(str(other), str(caught.exception))

    def test_rq029_catalog_gate_skips_a_linked_evals_entry(self):
        """bắt-lỗi (red at c3deee2: the junction passes `is_dir(follow_symlinks=False)` and `evidence` is probed through it): FR11.2 an evals/<x> that is a link is left out, said in one line, and `<x>/evidence` is never probed."""
        tmp = Path(tempfile.mkdtemp(prefix="studio-evlink-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "evals").mkdir()
        (tmp / "evals" / "catalog.json").write_text('{"skills": []}', encoding="utf-8")
        (tmp / "evals" / "plain" / "evidence").mkdir(parents=True)
        (tmp / "evals" / "door" / "evidence").mkdir(parents=True)
        door = tmp / "evals" / "door"
        real_link, real_lexists, probed = E.fs.is_link, os.path.lexists, []

        def lexists(path):
            probed.append(os.path.normcase(os.fspath(path)))
            return real_lexists(path)

        with mock.patch.object(E.fs, "is_link", side_effect=lambda p: Path(p) == door or real_link(p)),                 mock.patch.object(E.evals.os.path, "lexists", lexists):
            problems = E.evals.model_evaluated_problems(tmp / "evals" / "catalog.json", tmp)
        self.assertEqual([], [p for p in probed if os.path.normcase(os.fspath(door)) in p], "the linked folder was probed")
        self.assertTrue(any("evals/door" in p and "link" in p for p in problems), problems)
        self.assertTrue(any("evals/plain/evidence has no catalog entry" in p for p in problems), problems)
        self.assertFalse(any("evals/door/evidence" in p for p in problems), problems)


    def _linked_evals_root(self):
        tmp = Path(tempfile.mkdtemp(prefix="studio-evlink-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "evals").mkdir()
        (tmp / "evals" / "catalog.json").write_text('{"skills": []}', encoding="utf-8")
        (tmp / "evals" / "elsewhere" / "evidence").mkdir(parents=True)
        return tmp

    def test_rq029_catalog_gate_says_a_real_symlink(self):
        """bắt-lỗi (red at 43bfbc5 where the symlink is skipped silently; RED only seen on CI Ubuntu, this machine cannot make a symlink): FR11.2 a real symlink evals/<x> gets its line and is not probed."""
        tmp = self._linked_evals_root()
        try:
            os.symlink(tmp / "evals" / "elsewhere", tmp / "evals" / "door", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("cannot create a symlink here: %s" % exc)
        problems = E.evals.model_evaluated_problems(tmp / "evals" / "catalog.json", tmp)
        self.assertTrue(any("evals/door is a link" in p for p in problems), problems)
        self.assertFalse(any("evals/door/evidence" in p for p in problems), problems)

    def test_rq029_catalog_gate_says_an_entry_that_reports_a_symlink(self):
        """bắt-lỗi (red at 43bfbc5: `is_dir(follow_symlinks=False)` False -> skipped, no line): FR11.2 an entry with is_symlink() True and is_dir(follow_symlinks=False) False, as a real symlink answers, is said."""
        tmp = self._linked_evals_root()
        (tmp / "evals" / "door").mkdir()
        real_scandir = os.scandir

        class Entry:
            def __init__(self, entry):
                self._entry = entry

            def __getattr__(self, name):
                return getattr(self._entry, name)

            def is_symlink(self):
                return True

            def is_dir(self, *, follow_symlinks=True):
                return follow_symlinks

        class Scan:
            def __init__(self, path):
                self._inner = real_scandir(path)

            def __enter__(self):
                self._inner.__enter__()
                return self

            def __exit__(self, *exc):
                return self._inner.__exit__(*exc)

            def __iter__(self):
                return (Entry(e) if e.name == "door" else e for e in self._inner)

        with mock.patch.object(E.evals.os, "scandir", Scan):
            problems = E.evals.model_evaluated_problems(tmp / "evals" / "catalog.json", tmp)
        self.assertTrue(any("evals/door is a link" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
