"""Rules for the engine's sibling modules `skills/skill-creator-studio/scripts/studio_*.py` (SPR-02 TK4a, SPEC FR4.5, ADR-0001).

Run: python -X utf8 -m pytest tests/test_engine_modules.py -q -p no:cacheprovider
"""
from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _engine  # noqa: E402

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
        moved = _public(vars(_engine.const)) | _public(vars(_engine.fs))
        moved -= {"annotations", "os", "re", "ast", "errno", "functools", "stat", "Path", "C"}
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


if __name__ == "__main__":
    unittest.main()
