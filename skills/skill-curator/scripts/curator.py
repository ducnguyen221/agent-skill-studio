#!/usr/bin/env python3
"""Skill Curator: a read-only view of a whole Agent Skills library (SPR-04 TK9).

Python 3.9+, standard library only. Commands: `catalog` (one row per source skill, root states, JSON and CATALOG.md) and `doctor` (the engine's
report-only scan, unchanged). The shared engine modules `studio_*` come from `scripts/_engine/` when that folder is next to this file (the packaged
copy), else from `../../skill-creator-studio/scripts/` (the repository or plugin layout); a folder that lacks one of them is refused, never mixed.

Use `python3 curator.py --help` and per-command --help.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE_CANDIDATES = (HERE / "_engine", HERE.parent.parent / "skill-creator-studio" / "scripts")
# The modules `studio_doctor` and `studio_roots` import, and the engine's own entry point: a folder must hold all of them.
ENGINE_MODULES = ("studio_const", "studio_doctor", "studio_doctypes", "studio_evals", "studio_fs", "studio_lint", "studio_roots", "studio_validate")


def _fail(message: str) -> int:
    sys.stderr.write("ERROR: %s\n" % message)
    return 2


def find_engine() -> Path | None:
    """The first candidate folder that holds every shared module, else None."""
    for folder in ENGINE_CANDIDATES:
        if folder.is_dir() and all((folder / (name + ".py")).is_file() for name in ENGINE_MODULES):
            return folder
    return None


def load_engine(folder: Path) -> str | None:
    """Put `folder` first on sys.path (dropping any other entry for it) and check that every `studio_*` module already loaded sits in it. Returns a
    complaint, or None. A module found anywhere else would mix two code bases."""
    sys.path[:] = [entry for entry in sys.path if entry != str(folder)]
    sys.path.insert(0, str(folder))
    for name in ENGINE_MODULES:
        __import__(name)
    for name, module in sorted(sys.modules.items()):
        where = getattr(module, "__file__", None)
        if name.startswith("studio_") and where and Path(where).resolve().parent != folder.resolve():
            return "engine module %s loaded from %s, expected %s" % (name, Path(where).resolve().parent, folder)
    return None


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    folder = find_engine()
    if folder is None:
        return _fail("curator needs the shared engine modules (%s) in %s or %s" % (", ".join(ENGINE_MODULES), ENGINE_CANDIDATES[0], ENGINE_CANDIDATES[1]))
    complaint = load_engine(folder)
    if complaint:
        return _fail(complaint)
    sys.path.insert(1, str(HERE))
    import curator_catalog  # noqa: E402  (after the engine folder is first on the path)
    if Path(curator_catalog.__file__).resolve().parent != HERE:
        return _fail("curator_catalog loaded from %s, expected %s" % (Path(curator_catalog.__file__).resolve().parent, HERE))
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: curator.py {catalog,doctor} ...\n\n"
              "  catalog   one row per source skill, root states, JSON schema 1 and CATALOG.md (read-only)\n"
              "  doctor    the engine's report-only scan of many skill roots (same flags as studio.py doctor)\n\n"
              "Run `curator.py <command> --help` for the flags.")
        return 0
    if argv[0] == "catalog":
        return curator_catalog.run(curator_catalog.build_parser("curator.py catalog").parse_args(argv[1:]))
    if argv[0] == "doctor":
        entry = folder / "studio.py"
        if not entry.is_file():
            return _fail("doctor needs studio.py in %s" % folder)
        spec = importlib.util.spec_from_file_location("studio_engine_for_curator", entry)
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        return engine.main(argv)
    return _fail("unknown command %r; use catalog or doctor" % argv[0])


if __name__ == "__main__":
    sys.exit(main())
