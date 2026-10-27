"""Load the engine once for the whole test run (SPR-02 TK2, FR1.3).

The engine is `skills/skill-creator-studio/scripts/studio.py`. The root `studio.py` is only a shim, so tests never load it as a
module; they run it as a subprocess when they test the command line. The engine's sibling modules (`studio_*.py`) are loaded
by the engine itself; `const`, `fs`, `evals`, `lint`, `validate`, `scaffold`, `dist`, `doctor` and `fmt` below are those same module objects, so `patch.object` on them is seen by every caller.
Every engine module is exported here by its short name.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT / "skills" / "skill-creator-studio" / "scripts"
ENGINE_PATH = ENGINE_DIR / "studio.py"
SHIM_PATH = ROOT / "studio.py"
# Every file that holds engine code; tests that read the code as text or AST scan this list.
ENGINE_FILES = [ENGINE_PATH] + sorted(ENGINE_DIR.glob("studio_*.py"))


def _load():
    spec = importlib.util.spec_from_file_location("studio_engine_under_test", ENGINE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


engine = _load()
const = sys.modules["studio_const"]
fs = sys.modules["studio_fs"]
evals = sys.modules["studio_evals"]
lint = sys.modules["studio_lint"]
validate = sys.modules["studio_validate"]
scaffold = sys.modules["studio_scaffold"]
dist = sys.modules["studio_dist"]
doctor = sys.modules["studio_doctor"]
fmt = sys.modules["studio_fmt"]


def clear_caches(module=None) -> None:  # `module` is kept for old callers; the cache lives in studio_fs
    """Empty the lru_cache that tests change HOME for (`_secret_dirs`); call it in setUp and again when the test is done."""
    fs._secret_dirs.cache_clear()


def engine_source() -> str:
    """The text of all engine files joined, for tests that read the code as text."""
    return "\n".join(p.read_text(encoding="utf-8") for p in ENGINE_FILES)
