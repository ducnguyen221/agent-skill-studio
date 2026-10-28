"""Helpers for tests that need compact evidence files (SPR-03 TK1, FR3).

`activation` is evals/tools/activation.py loaded once as a module (it is a tool, not part of the engine); `write_compact` builds the compact file
of a raw run folder the way the `compact` command does, so a test can lay out a raw folder, mutate it, and give the gate the result.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "batch"
RAW = FIXTURE / "raw"
COMPACT = FIXTURE / "compact.json"
TOOL_PATH = ROOT / "evals" / "tools" / "activation.py"

_spec = importlib.util.spec_from_file_location("activation_for_tests", TOOL_PATH)
activation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(activation)


def write_compact(raw_dir, skill: str, batch: str, out) -> Path:
    """Write the compact evidence file of `raw_dir` to `out` (parents created); returns `out`."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(activation.compact_text(raw_dir, skill, batch))
    return out
