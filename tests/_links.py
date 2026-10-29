"""Link fixtures for the SPR-05 tests: a directory junction, a symlink, a hard link, and the link kind that needs no privilege.

`make_symlink` skips the test with the reason `symlink-privilege` when the machine cannot make a symlink (Windows winerror 1314, POSIX EPERM),
unless `STUDIO_REQUIRE_SYMLINK=1` is set (the CI runners set it): then it fails instead, so a runner cannot pass the symlink cases by skipping them.
`make_junction`, `make_hardlink` and `dir_link` need no privilege, so they always run.
"""
from __future__ import annotations

import errno
import os
import unittest
from pathlib import Path

REQUIRE_ENV = "STUDIO_REQUIRE_SYMLINK"


def _privilege_missing(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == 1314 or exc.errno == errno.EPERM


def make_symlink(target, link, is_dir: bool = False) -> None:
    """Make `link` a symlink to `target`; skip (or, with STUDIO_REQUIRE_SYMLINK=1, fail) when the account may not make one."""
    try:
        os.symlink(os.fspath(target), os.fspath(link), target_is_directory=is_dir)
    except OSError as exc:
        if not _privilege_missing(exc):
            raise
        if os.environ.get(REQUIRE_ENV) == "1":
            raise AssertionError("symlink required on this runner") from exc
        raise unittest.SkipTest("symlink-privilege") from exc


def make_junction(target, link) -> None:
    """A directory junction on Windows (no privilege needed); a directory symlink elsewhere."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(Path(target).resolve()), str(link))
    else:
        os.symlink(os.fspath(target), os.fspath(link), target_is_directory=True)


def make_hardlink(target, link) -> None:
    os.link(os.fspath(target), os.fspath(link))


def dir_link(target, link) -> None:
    """The folder link that needs no privilege on this OS: a junction on Windows, a directory symlink on POSIX."""
    make_junction(target, link)
