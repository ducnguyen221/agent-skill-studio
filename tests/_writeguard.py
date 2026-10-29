"""In-process write guard for tests that must prove «nothing is written there» (SPR-04 TK3, FR12.5).

`block_writes_outside(allowed)` is a context manager: inside it, every way the engine and the tests write a file or make a folder (`open` and
`io.open` in a writing mode, `Path.open`, `Path.write_text`, `Path.write_bytes`, `Path.touch`, `os.open` with a writing flag, `Path.mkdir`,
`os.mkdir`) raises `PermissionError` for a path that is not under one of `allowed`. Reads are left alone. Paths are compared after `realpath`
and case folding, so a temporary folder behind a link (macOS `/var`) and a drive letter in another case both match.
Not a security boundary: it only stops code that goes through these names, which is all the engine's writers do.
"""
from __future__ import annotations

import builtins
import contextlib
import io
import os
from pathlib import Path
from unittest import mock

_WRITE_MODE_CHARS = set("wax+")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _key(path) -> str:
    return os.path.normcase(os.path.realpath(os.fsdecode(path)))


def _under(path, roots: list) -> bool:
    key = _key(path)
    return any(key == root or key.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


@contextlib.contextmanager
def block_writes_outside(allowed: list):
    """Raise PermissionError for any write or folder creation outside the folders in `allowed` while the block runs."""
    roots = [_key(p) for p in allowed]
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    real_write_text, real_write_bytes, real_touch = Path.write_text, Path.write_bytes, Path.touch
    real_mkdir, real_os_mkdir = Path.mkdir, os.mkdir

    def refuse(path):
        raise PermissionError(13, "write guard: not under an allowed folder", os.fsdecode(path))

    def check(path):
        if not _under(path, roots):
            refuse(path)

    def guarded_open(file, mode="r", *args, **kwargs):
        if not isinstance(file, int) and _WRITE_MODE_CHARS & set(mode):
            check(file)
        return real_open(file, mode, *args, **kwargs)

    def guarded_io_open(file, mode="r", *args, **kwargs):
        if not isinstance(file, int) and _WRITE_MODE_CHARS & set(mode):
            check(file)
        return real_io_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        if not isinstance(path, int) and flags & _WRITE_FLAGS:
            check(path)
        return real_os_open(path, flags, *args, **kwargs)

    def guarded_write_text(self, *args, **kwargs):
        check(self)
        return real_write_text(self, *args, **kwargs)

    def guarded_write_bytes(self, *args, **kwargs):
        check(self)
        return real_write_bytes(self, *args, **kwargs)

    def guarded_touch(self, *args, **kwargs):
        check(self)
        return real_touch(self, *args, **kwargs)

    def guarded_mkdir(self, *args, **kwargs):
        if not os.path.isdir(self):  # a folder that is there is not made again
            check(self)
        return real_mkdir(self, *args, **kwargs)

    def guarded_os_mkdir(path, *args, **kwargs):
        if not os.path.isdir(path):
            check(path)
        return real_os_mkdir(path, *args, **kwargs)

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(builtins, "open", guarded_open))
        stack.enter_context(mock.patch.object(io, "open", guarded_io_open))
        stack.enter_context(mock.patch.object(os, "open", guarded_os_open))
        stack.enter_context(mock.patch.object(Path, "write_text", guarded_write_text))
        stack.enter_context(mock.patch.object(Path, "write_bytes", guarded_write_bytes))
        stack.enter_context(mock.patch.object(Path, "touch", guarded_touch))
        stack.enter_context(mock.patch.object(Path, "mkdir", guarded_mkdir))
        stack.enter_context(mock.patch.object(os, "mkdir", guarded_os_mkdir))
        yield
