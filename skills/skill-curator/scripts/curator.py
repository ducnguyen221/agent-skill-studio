#!/usr/bin/env python3
"""Skill Curator: a read-only view of a whole Agent Skills library (SPR-04 TK9).

Python 3.9+, standard library only. Commands: `catalog` (one row per source skill, root states, JSON and CATALOG.md) and `doctor` (the engine's
report-only scan, unchanged). The shared engine modules `studio_*` come from `scripts/_engine/` when that folder is next to this file (the packaged
copy), else from `../../skill-creator-studio/scripts/` (the repository or plugin layout); a folder that lacks one of them is refused, never mixed.
The modules a folder must hold are the ones `ENGINE_DEPS` (next to this file) names: one list, shared with `package` and `install`.

Use `python3 curator.py --help` and per-command --help.
"""

from __future__ import annotations

import importlib.util
import os
import re
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE_CANDIDATES = (HERE / "_engine", HERE.parent.parent / "skill-creator-studio" / "scripts")
ENGINE_DEPS = HERE / "ENGINE_DEPS"
ENGINE_DEPS_LIMIT = 4096
ENGINE_DEP_NAME = re.compile(r"^studio_[a-z_]+\.py$")


class EngineListError(Exception):
    """`ENGINE_DEPS` is missing, a link, too big, or not a list of `studio_*.py` names: an install that lost its file (reinstall), never guessed around."""


def _fail(message: str) -> int:
    sys.stderr.write("ERROR: %s\n" % message)
    return 2


def _read_engine_deps() -> bytes:
    """The bytes of `ENGINE_DEPS`, opened as itself: a link, a second hard link or a file swapped after the check is refused. This is `open_nofollow_read` in
    miniature, because that function lives in the engine folder, which is not chosen until this list is read."""
    info = os.lstat(ENGINE_DEPS)
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError("not a plain file")
    fd = os.open(ENGINE_DEPS, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise OSError("the file changed while it was opened")
        return handle.read(ENGINE_DEPS_LIMIT + 1)


def engine_modules() -> list:
    """The module file names (`studio_const.py`, ...) `ENGINE_DEPS` lists, in file order; '#' lines and blank lines are skipped. Raises EngineListError."""
    problem = EngineListError("engine list ENGINE_DEPS missing or unreadable in %s; reinstall skill-curator" % HERE)
    try:
        raw = _read_engine_deps()
        if len(raw) > ENGINE_DEPS_LIMIT:
            raise ValueError("over %d bytes" % ENGINE_DEPS_LIMIT)
        lines = [line.strip() for line in raw.decode("utf-8").splitlines()]
    except (OSError, ValueError) as exc:  # UnicodeError is a ValueError
        raise problem from exc
    names = []
    for line in lines:
        if line and not line.startswith("#") and line not in names:
            if not ENGINE_DEP_NAME.match(line):
                raise problem
            names.append(line)
    if not names:
        raise problem
    return names


def find_engine(names: list | None = None) -> Path | None:
    """The first candidate folder that holds every module `ENGINE_DEPS` lists, else None. Raises EngineListError when the list cannot be read."""
    names = engine_modules() if names is None else names
    for folder in ENGINE_CANDIDATES:
        if folder.is_dir() and all((folder / name).is_file() for name in names):
            return folder
    return None


def load_engine(folder: Path, names: list | None = None) -> str | None:
    """Put `folder` first on sys.path (dropping any other entry for it) and check that every `studio_*` module already loaded sits in it. Returns a
    complaint, or None. A module found anywhere else would mix two code bases."""
    names = engine_modules() if names is None else names
    sys.path[:] = [entry for entry in sys.path if entry != str(folder)]
    sys.path.insert(0, str(folder))
    complaint = _foreign_module(folder)  # before the imports: a foreign `studio_*` already loaded would be handed back by them, or break them
    if complaint:
        return complaint
    for name in names:
        __import__(name[:-3])
    return _foreign_module(folder)


def _foreign_module(folder: Path) -> str | None:
    for name, module in sorted(sys.modules.items()):
        where = getattr(module, "__file__", None)
        if name.startswith("studio_") and where and Path(where).resolve().parent != folder.resolve():
            return "engine module %s loaded from %s, expected %s" % (name, Path(where).resolve().parent, folder)
    return None


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        names = engine_modules()
    except EngineListError as exc:
        return _fail(str(exc))
    folder = find_engine(names)
    if folder is None:
        return _fail("curator needs the shared engine modules (%s) in %s or %s" % (", ".join(names), ENGINE_CANDIDATES[0], ENGINE_CANDIDATES[1]))
    complaint = load_engine(folder, names)
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
        complaint = _foreign_module(folder)  # studio.py is code too: whatever it pulled in while loading is checked before its main runs
        if complaint:
            return _fail(complaint)
        return engine.main(argv)
    return _fail("unknown command %r; use catalog or doctor" % argv[0])


if __name__ == "__main__":
    sys.exit(main())
