"""File-system helpers of the Agent Skill Studio engine: finding, reading, creating and walking files without following links
or touching cloud placeholders, plus frontmatter parsing and finding records (SPR-02 TK4a).

Internal module of `studio.py`; do not run it. It reaches the constants through `studio_const` as an object (FR4.5).
"""

from __future__ import annotations

import ast
import contextlib
import errno
import functools
import os
import re
import stat
from pathlib import Path

import studio_const as C

def emit(level: str, code: str, path: Path, line: int, message: str) -> dict:
    return {"level": level, "code": code, "path": str(path), "line": line, "message": message}


def scalar(value: str) -> str:
    """Parse a *small, explicit subset* of YAML string scalars, not general YAML."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            if value[0] == "'":
                return value[1:-1].replace("''", "'")
            raise ValueError("malformed quoted scalar; check quote escaping")
    if ": " in value and not value.startswith("http"):
        raise ValueError("unquoted ': ' is ambiguous YAML; quote this scalar")
    if value.startswith(("[", "{", "@", "`")):
        raise ValueError("complex YAML scalar is not supported by the offline parser; quote it")
    return value


def parse_frontmatter(text: str, path: Path, opaque_keys: frozenset = frozenset()) -> tuple[dict, list, int]:
    """Parse the supported YAML subset. A key in `opaque_keys` with an empty value keeps its nested
    indented block as one raw string (no FM1); the block ends at the next top-level key."""
    lines = text.splitlines()
    findings: list[dict] = []
    if not lines or lines[0].strip() != "---":
        return {}, [emit("ERROR", "FM1", path, 1, "SKILL.md must start on line 1 with YAML '---'")], 0
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, [emit("ERROR", "FM1", path, 1, "closing frontmatter '---' not found")], 0
    parsed: dict = {}
    key = None
    mode = None  # 'block', 'meta', 'opaque' or None
    block_lines: list[str] = []
    block_kind = None

    def flush():
        nonlocal key, mode, block_lines, block_kind
        if mode == "block" and key is not None:
            parsed[key] = ("\n" if block_kind == "|" else " ").join(block_lines).strip()
        elif mode == "opaque" and key is not None:
            parsed[key] = "\n".join(block_lines)
        mode = None
        block_lines = []
        block_kind = None

    for index in range(1, end):
        raw = lines[index]
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            flush()
            match = C.FRONT_KEY_RE.fullmatch(raw.rstrip())
            if not match:
                findings.append(emit("ERROR", "FM1", path, index + 1, "invalid YAML top-level key/value line"))
                key = None
                continue
            key, val = match.group(1), (match.group(2) or "").strip()
            if key in parsed:
                findings.append(emit("ERROR", "FM1", path, index + 1, "duplicate frontmatter key '%s'" % key))
            if val in (">", ">-", "|", "|-"):
                mode, block_kind = "block", val[0]
                parsed[key] = ""
            elif key == "metadata" and val == "":
                mode = "meta"
                parsed[key] = {}
            elif key in opaque_keys and val == "":
                mode = "opaque"
                parsed[key] = ""
            else:
                try:
                    parsed[key] = scalar(val)
                except ValueError as exc:
                    findings.append(emit("ERROR", "FM1", path, index + 1, str(exc)))
                    parsed[key] = val
        else:
            if mode == "block" and raw.startswith((" ", "\t")):
                block_lines.append(raw.strip())
            elif mode == "opaque":
                block_lines.append(raw.rstrip())
            elif mode == "meta":
                match = C.META_KEY_RE.fullmatch(raw.rstrip())
                if not match:
                    findings.append(emit("ERROR", "FM1", path, index + 1, "metadata must be a simple indented key: string map"))
                    continue
                try:
                    parsed["metadata"][match.group(1)] = scalar((match.group(2) or "").strip())
                except ValueError as exc:
                    findings.append(emit("ERROR", "FM1", path, index + 1, str(exc)))
            else:
                findings.append(emit("ERROR", "FM1", path, index + 1, "unexpected indentation outside YAML block/metadata"))
    flush()
    return parsed, findings, end + 1


def repo_root(start: Path) -> Path | None:
    for candidate in [start.resolve()] + list(start.resolve().parents):
        if (candidate / ".claude-plugin" / "plugin.json").is_file() and (candidate / "standards" / "SKILL_AUTHORING_STANDARD.md").is_file():
            return candidate
    return None


def skill_dirs(root: Path, skipped: list | None = None) -> list[Path]:
    """The folders under `root/skills` that hold a SKILL.md. A link (symlink, junction), a path that cannot be probed (`is_link` is True for it, FR13.1),
    a cloud placeholder and a `skills` folder that is itself a link are neither listed nor entered, and nothing is stat-ed through a link (SPR-02 FR7.1:
    the pattern of walk_files). Each one left out is appended to `skipped` as {path, reason} (`link`, `cloud`, `unreadable`) when a list is given, so a
    caller can say that a skill was not looked at instead of reporting «all good» without it."""
    def skip(path, reason: str) -> None:
        if skipped is not None:
            skipped.append({"path": os.fspath(path), "reason": reason})

    base = root / "skills"
    if is_link(base):
        skip(base, "link")
        return []
    if path_is_cloud(base):
        skip(base, "cloud")
        return []
    try:
        with os.scandir(base) as scan:
            entries = list(scan)
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError:
        skip(base, "unreadable")
        return []
    found = []
    for entry in entries:
        path = Path(entry.path)
        try:
            if entry.is_symlink():
                skip(path, "link")
            elif entry_is_cloud(entry):
                skip(path, "cloud")
            elif not entry.is_dir(follow_symlinks=False):
                pass  # a plain file in skills/ is not a skill candidate
            elif is_link(path):
                skip(path, "link")
            else:
                manifest = path / "SKILL.md"
                if is_link(manifest):  # lstat, never stat: a SKILL.md that is a link is not a skill and its target is not asked about (FR11.1)
                    skip(manifest, "link")
                else:
                    try:
                        if stat.S_ISREG(os.lstat(manifest).st_mode):
                            found.append(path)
                    except (FileNotFoundError, NotADirectoryError):
                        pass  # no SKILL.md: not a skill
        except OSError:
            skip(path, "unreadable")
    return sorted(found)


def is_link(path: Path) -> bool:
    """True for a symlink or, on Windows, any reparse point such as a directory junction (os.path.isjunction needs Python 3.12).
    Fails closed (SPR-03 FR13.1): a path that does not exist (or whose parent is not a folder) is not a link, but any other OSError while probing
    it (PermissionError, ENAMETOOLONG, Windows winerror 123) makes it «a link», so the caller refuses or skips it instead of treating it as plain."""
    try:  # pathlib re-raises ENAMETOOLONG and the like from is_symlink(); lstat then asks again, so an error that pathlib swallows still counts
        if path.is_symlink():
            return True
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True


def valid_resolved_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


@functools.lru_cache(maxsize=8)
def _secret_dirs(home: str) -> tuple:
    """Normalized, case-folded spellings of ~/.secret. Only `home` is resolved (a lstat chain up to it), never the secret folder."""
    return (os.path.normcase(os.path.abspath(os.path.join(home, ".secret"))).casefold(),
            os.path.join(os.path.normcase(os.path.realpath(home)), ".secret").casefold())


def _long_name_text(text: str) -> str:
    """On Windows, `text` with 8.3 short names (ONEDRI~1) replaced by the long names, for the longest prefix that exists; else `text`.
    Asks the OS about names only (GetLongPathNameW lists directory entries; it opens no file). Any failure keeps `text`."""
    if os.name != "nt" or "~" not in text:
        return text
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        head, tail = text, []
        while head:
            size = ctypes.windll.kernel32.GetLongPathNameW(head, buf, len(buf))
            if 0 < size < len(buf):
                return os.path.join(buf.value, *reversed(tail)) if tail else buf.value
            up, name = os.path.split(head)
            if not name or up == head:
                break
            head, tail = up, tail + [name]
    except (OSError, AttributeError, ImportError, ValueError):
        pass
    return text


def zone_reason(path, markers=C.CLOUD_MARKERS) -> str | None:
    """'cloud' for a path naming one of `markers` (OneDrive, SharePoint and any --skip-marker; case-insensitive), 'secret-zone' for ~/.secret
    or any folder called .secret (any case, any platform), else None. It never stats or opens `path` (RK15). One exception, Windows only: a spelling with an 8.3
    short name ('~' + digit) is expanded by asking the OS for the long form (GetLongPathNameW), which reads directory entries (names only) of the folders along
    the path, cloud folders included; nothing is opened and no file content is read."""
    given = os.path.abspath(os.fspath(path))
    texts = [os.path.normcase(given).casefold()]
    long_form = os.path.normcase(_long_name_text(given)).casefold()
    if long_form != texts[0]:
        texts.append(long_form)  # an 8.3 spelling (ONEDRI~1) hides the folder's real name from a string test
    if any(marker.casefold() in text for text in texts for marker in markers):
        return "cloud"
    if any(".secret" in text.split(os.sep) for text in texts):
        return "secret-zone"
    try:
        secrets = _secret_dirs(str(Path.home()))
    except (RuntimeError, KeyError, OSError):
        return None
    return "secret-zone" if any(text == s or text.startswith(s + os.sep) for text in texts for s in secrets) else None


def _stat_is_cloud(info) -> bool:
    """Cloud attribute bits, or a cloud reparse tag (st_reparse_tag, Python 3.8+ on Windows). Reads the stat result only, never the file."""
    if getattr(info, "st_file_attributes", 0) & C.CLOUD_ATTR_MASK:
        return True
    return (getattr(info, "st_reparse_tag", 0) & C.CLOUD_TAG_MASK) == C.CLOUD_TAG


def entry_is_cloud(entry) -> bool:
    """True when a directory entry carries Windows cloud attributes or a cloud reparse tag. DirEntry.stat(follow_symlinks=False) reads the listing, not the file."""
    if not C.CLOUD_ATTRS_AVAILABLE:
        return False
    try:
        return _stat_is_cloud(entry.stat(follow_symlinks=False))
    except OSError:
        return False


def path_is_cloud(path) -> bool:
    """The same test for a path: one lstat (metadata only; it neither follows a link nor starts a download)."""
    if not C.CLOUD_ATTRS_AVAILABLE:
        return False
    try:
        return _stat_is_cloud(os.lstat(path))
    except OSError:
        return False


def _plain_path(path) -> str:
    """Case-normalised absolute spelling without a \\\\?\\ or \\\\?\\UNC\\ prefix. Names only."""
    text = os.path.abspath(os.fspath(path))
    if text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(text)


def _broad_by_name(text: str, homes: list) -> bool:
    if not os.path.splitdrive(text)[1].strip("\\/"):
        return True
    for home in homes:
        try:
            if os.path.commonpath([text, home]) == text:
                return True
        except ValueError:  # another drive
            continue
    return False


def namespace_refused(path) -> bool:
    """True for a root spelled in a Windows device namespace (\\\\.\\..., \\??\\..., and \\\\?\\ followed by anything but a drive letter or UNC\\:
    GLOBALROOT, Volume{GUID}...) or on an administrative share (\\\\host\\C$, \\\\?\\UNC\\host\\C$). Judged on the spelling alone: such a
    path can name the home folder or a whole drive in a way the other checks do not recognise, so it is never a root."""
    text = os.fspath(path).replace("/", "\\")
    if text[:4] in ("\\\\.\\", "\\??\\") or text in ("\\\\.", "\\??"):
        return True
    if text.startswith("\\\\?\\"):
        rest = text[4:]
        if re.match(r"[A-Za-z]:(\\|$)", rest):
            return False
        if rest[:4].upper() != "UNC\\":
            return True
        text = "\\\\" + rest[4:]
    if text.startswith("\\\\"):
        parts = [x for x in text[2:].split("\\") if x]
        return len(parts) >= 2 and parts[1].endswith("$")
    return False


def root_too_broad(path, markers=C.CLOUD_MARKERS) -> bool:
    """True for a drive or filesystem root, the home folder, or any folder above it, judged on the spelling given, on the normalised
    spelling (no \\\\?\\ prefix) and on the real path (a junction or symlink into the home, an 8.3 name). The real path is looked up only
    for a local path outside the cloud and secret zones; a UNC path is never resolved. A device namespace or an administrative share
    is always too broad (namespace_refused)."""
    if namespace_refused(path):
        return True
    given = _plain_path(path)
    homes = []
    try:
        home = Path.home()
        homes.append(_plain_path(home))
        if not zone_reason(home, markers):
            homes.append(_plain_path(home.resolve()))
    except (RuntimeError, KeyError, OSError):
        pass
    if _broad_by_name(given, homes):
        return True
    if given.startswith("\\\\") or zone_reason(given, markers):
        return False
    try:
        real = _plain_path(Path(given).resolve())
    except (OSError, RuntimeError):
        return False
    return real != given and _broad_by_name(real, homes)


def input_name_problem(source: Path, markers=C.CLOUD_MARKERS) -> str | None:
    """The part of `input_file_problem` decided from the spelling alone, so nothing is stat-ed or opened: an NTFS data stream (name:stream),
    a secret-looking file name, or the spelling given in a cloud or secret zone. Else None."""
    text = os.fspath(source)
    if os.name == "nt" and ":" in os.path.splitdrive(text)[1]:
        return "names an NTFS data stream; not read"
    if secret_file_name(source.name):
        return "has a secret-looking file name; not read"
    reason = zone_reason(source, markers)
    return "is inside a %s zone; not read" % reason if reason else None


def input_file_problem(source: Path, markers=C.CLOUD_MARKERS) -> str | None:
    """Why an input file (--roots-file, --baseline) may not be read, else None. Decided before opening it: not an NTFS data stream
    (name:stream), not a secret-looking name, not a cloud placeholder, and neither the spelling given nor the real path (a link, an 8.3
    name such as SECRET~1) in a cloud or secret zone."""
    named = input_name_problem(source, markers)
    if named:
        return named
    if path_is_cloud(source):
        return "is a cloud placeholder; not read"
    try:
        real = source.resolve()
    except (OSError, RuntimeError):
        return "cannot be resolved; not read"
    if secret_file_name(real.name):
        return "is a link to a file with a secret-looking name; not read"
    reason = zone_reason(real, markers)
    if not reason and path_is_cloud(real):
        return "is a cloud placeholder; not read"
    return "is inside a %s zone; not read" % reason if reason else None


def link_crosses_link(base: Path, link: str) -> bool:
    """True when walking `link` from `base` passes through a symlink or junction. One lstat per step; nothing is followed or resolved."""
    current = Path(base)
    for part in re.split(r"[\\/]+", link):
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
        else:
            current = current / part
            if is_link(current):
                return True
    return False


def read_capped(path, limit: int | None, single_link: bool = False, anchor=None) -> tuple:
    """(text, too_big). With a limit the file is read in binary up to limit+1 bytes and never further; newlines are folded as read_text does.
    Every branch opens through open_nofollow_read, so a link at the last name is refused (UnsafeOpen) and, with `single_link`, so is a file with a second name."""
    with open_nofollow_read(path, None, single_link, anchor) as handle:
        data = handle.read() if limit is None else handle.read(limit + 1)
    if limit is not None and len(data) > limit:
        return None, True
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"), False


def strip_code_spans(text: str, repl: str = " ") -> str:
    """Replace each inline code span as re.sub(r"(`+).+?\\1", repl, text) did, but in linear time: a long run of backticks made
    that regex cubic. The regex's rule, worked out per run of K backticks that starts a try: the longest opener k that has a closer wins,
    a closer being k backticks after at least one character, inside the same run (k <= (K-1)//2) or in a later run at least k long.
    A run no closer can follow stays plain text. Each line is handled alone, as `.` never matched a newline."""
    if "`" not in text:
        return text
    return "\n".join(_strip_code_spans_line(part, repl) for part in text.split("\n"))


def _strip_code_spans_line(line: str, repl: str) -> str:
    runs = [match.span() for match in C.BACKTICK_RUN_RE.finditer(line)]
    if not runs:
        return line
    longest_after = [0] * (len(runs) + 1)
    for index in range(len(runs) - 1, -1, -1):
        longest_after[index] = max(longest_after[index + 1], runs[index][1] - runs[index][0])
    out, copied, index, pos = [], 0, 0, runs[0][0]
    while index < len(runs):
        width = runs[index][1] - pos
        inside = (width - 1) // 2
        size = max(inside, min(width, longest_after[index + 1]))
        if size < 1:
            break  # no run is left to close anything
        if size == inside:
            end, last = pos + 2 * size + 1, index
        else:
            last = index + 1
            while runs[last][1] - runs[last][0] < size:
                last += 1
            end = runs[last][0] + size
        out.append(line[copied:pos])
        out.append(repl)
        copied = end
        if end < runs[last][1]:
            index, pos = last, end
        else:
            index = last + 1
            if index < len(runs):
                pos = runs[index][0]
    out.append(line[copied:])
    return "".join(out)


def has_xml_tag(text: str) -> bool:
    """Same answer as re.search(r"<[^>]+>", text), in linear time: a '<' whose first following '>' is not right behind it."""
    start = text.find("<")
    while start != -1:
        close = text.find(">", start + 1)
        if close == -1:
            return False
        if close > start + 1:
            return True
        start = text.find("<", start + 1)
    return False


def strip_html_comments(text: str, repl: str = " ") -> str:
    """Replace each `<!-- ... -->` that opens and closes on one line, as re.sub(r"<!--.*?-->") did, but in linear time:
    thousands of unclosed '<!--' made that regex quadratic."""
    out, pos = [], 0
    i = text.find("<!--")
    while i != -1:
        eol = text.find("\n", i + 4)
        j = text.find("-->", i + 4, len(text) if eol == -1 else eol)
        if j == -1:  # nothing closes on this line, so no later opener on it can either
            if eol == -1:
                break
            i = text.find("<!--", eol + 1)
            continue
        out.append(text[pos:i])
        out.append(repl)
        pos = j + 3
        i = text.find("<!--", pos)
    out.append(text[pos:])
    return "".join(out)


def lexically_inside(path, base) -> bool:
    """True when `path` is `base` or below it by name alone (`..` folded, nothing resolved or stat-ed)."""
    path, base = os.path.normcase(os.path.abspath(os.fspath(path))), os.path.normcase(os.path.abspath(os.fspath(base)))
    try:
        return os.path.commonpath([path, base]) == base
    except ValueError:  # different drives
        return False


def is_sensitive_name(name: str) -> bool:
    """File names doctor never opens, even inside a skill: .env*, *.credentials.json, auth.json, *.pem, *.key."""
    low = name.lower()
    return low.startswith(".env") or low.endswith(".credentials.json") or low == "auth.json" or low.endswith((".pem", ".key"))


def secret_file_name(name: str) -> bool:
    """is_sensitive_name plus the names the packager refuses to ship (REJECT_NAMES: secrets.json, credentials.json, id_rsa...): the names of
    files doctor is handed (--roots-file, --baseline, --out) and must not open."""
    return is_sensitive_name(name) or name.lower() in C.REJECT_NAMES


# The text patterns of a hardcoded secret (a private key header, an sk-, ghp_ or AKIA key): the one detector of `package` (SEC) and of `check` on documents.
SECRET_TEXT_RE = re.compile(r"-----BEGIN " + "PRIVATE KEY-----|" + r"\b(?:sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})\b")


def secret_in_text(text: str) -> bool:
    """True when `text` holds a hardcoded secret by the patterns above."""
    return SECRET_TEXT_RE.search(text) is not None


def unsafe_windows_name(component: str) -> str | None:
    """Why one path component is dangerous on Windows (whatever OS runs this), or None. The reason starts with its kind (see WIN_NAME_CODES):
    'stream' (a ':'), 'trailing' (ends with a dot or a space: Windows drops it, so 'auth.json.' IS auth.json), 'device' (CON, NUL, COM1, CONIN$...
    with or without an extension, any case), 'short' (8.3 alias such as AUTH~1.JSO). '.' and '..' are not judged here."""
    if component in ("", ".", ".."):
        return None
    if ":" in component:
        return "stream: '%s' contains ':' (drive letter or NTFS stream)" % component
    if component[-1] in ". ":
        return "trailing: '%s' ends with a dot or a space (Windows strips it, so it names another file)" % component
    if component.split(".", 1)[0].rstrip(" ").upper() in C.WIN_DEVICE_NAMES:
        return "device: '%s' is a reserved Windows device name" % component
    if C.SHORT_NAME_RE.search(component):
        return "short: '%s' looks like an 8.3 short name ('~' + digit), which can stand for a secret file" % component
    return None


class UnsafeOpen(OSError):
    """A file or folder is not the one that was checked (link, second hard link, swapped identity). `code` is the EX code to report."""

    def __init__(self, message: str, code: str = "EX13"):
        super().__init__(message)
        self.code = code


_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _open_no_reparse(path: str, write: bool = False, create_new: bool = False) -> int:
    """Windows only: open the last name of `path` as itself, never through a link, and return a file descriptor: for reading, or with `write` for writing, and with
    `create_new` only when no name is there yet (CREATE_NEW). CreateFile with FILE_FLAG_OPEN_REPARSE_POINT opens a symlink, junction or cloud file as the reparse
    point, and BACKUP_SEMANTICS lets it open a folder too, so both are looked at (`fstat`) and refused instead of being followed (open, then compare, left a window).
    CREATE_NEW on a name that is a link or a folder is denied (winerror 5); that becomes FileExistsError only when the name really is there (lstat), so a genuine
    permission error stays one. `_winapi` is a private module of CPython: a build without it, or one that changes it, refuses to open (fails closed) and never
    falls back to a plain open()."""
    try:
        import _winapi
        import msvcrt
    except ImportError as exc:
        raise UnsafeOpen("safe open unavailable on this Python (no _winapi): %s" % path) from exc
    access = 0x40000000 if write else 0x80000000  # GENERIC_WRITE / GENERIC_READ
    disposition = 1 if create_new else 3  # CREATE_NEW / OPEN_EXISTING
    try:
        handle = _winapi.CreateFile(path, access, 0x1 | 0x2 | 0x4, 0, disposition, 0x00200000 | 0x02000000, 0)  # share all; OPEN_REPARSE_POINT | BACKUP_SEMANTICS
    except OSError as exc:
        if create_new and getattr(exc, "winerror", None) == 5:
            try:
                os.lstat(path)
            except OSError:
                raise exc
            raise FileExistsError(errno.EEXIST, "already exists (a link or a folder counts)", path) from exc
        raise
    try:
        fd = msvcrt.open_osfhandle(handle, (os.O_WRONLY if write else os.O_RDONLY) | os.O_BINARY)
    except BaseException:
        _winapi.CloseHandle(handle)
        raise
    try:
        info = os.fstat(fd)
        if getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:  # a cloud file carries the flag too: the message names both
            raise UnsafeOpen("is a link or a cloud file (reparse point): %s" % path)
        if stat.S_ISDIR(info.st_mode):
            raise UnsafeOpen("is a folder or a folder link: %s" % path)
    except BaseException:
        os.close(fd)
        raise
    return fd


def anchor_for(path, cwd=None) -> Path:
    """The folder a chain of folders is pinned from for `path`: the working folder when `path` is below it, else the folder that holds `path`. The same
    rule `resolve_check_path` uses, so a link ABOVE the anchor (macOS /tmp, a OneDrive folder that changed owner) is accepted on purpose (FR2.2)."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    here = Path(os.path.abspath(os.fspath(cwd) if cwd is not None else os.getcwd()))
    return here if os.path.normcase(here) in {os.path.normcase(p) for p in absolute.parents} else absolute.parent


class _Pin:
    """What `pin_chain` yields: `dir_fd` is the pinned folder that holds the file (a POSIX descriptor; None on Windows, where the full path is safe while pinned)."""

    def __init__(self, dir_fd):
        self.dir_fd = dir_fd


def _pin_component(name: str, dir_fd: int, stack) -> int:
    """POSIX: open one folder of the chain by `name` under the pinned `dir_fd` (None for the anchor, which is given as a path) without following a link."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=dir_fd) if dir_fd is not None else os.open(name, flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, getattr(errno, "EMLINK", -1)):
            try:
                is_symlink = stat.S_ISLNK(os.lstat(name, dir_fd=dir_fd).st_mode if dir_fd is not None else os.lstat(name).st_mode)
            except OSError:
                is_symlink = False
            if is_symlink:
                raise UnsafeOpen("a folder on the path is a link: %s" % name) from exc
        raise
    stack.callback(os.close, fd)
    return fd


def _pin_component_windows(path: str, stack) -> None:
    """Windows: open one folder of the chain as itself (FILE_LIST_DIRECTORY, reparse point not followed, BACKUP_SEMANTICS to open a folder) with a share mode
    that has no FILE_SHARE_DELETE, so while the handle is held nobody can rename or remove the folder or one above it (a handle with only FILE_READ_ATTRIBUTES
    would not block that). A reparse point on the way is refused; a folder another process holds open for delete cannot be pinned (winerror 32)."""
    try:
        import _winapi
        import msvcrt
    except ImportError as exc:
        raise UnsafeOpen("safe open unavailable on this Python (no _winapi): %s" % path) from exc
    try:
        handle = _winapi.CreateFile(path, 0x1, 0x1 | 0x2, 0, 3, 0x00200000 | 0x02000000, 0)  # FILE_LIST_DIRECTORY; share read+write; OPEN_EXISTING
    except OSError as exc:
        if getattr(exc, "winerror", None) == 32:
            raise UnsafeOpen("a folder on the path is in use: %s" % path) from exc
        raise
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except BaseException:
        _winapi.CloseHandle(handle)
        raise
    stack.callback(os.close, fd)
    info = os.fstat(fd)
    if getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise UnsafeOpen("a folder on the path is a link: %s" % path)
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafeOpen("a folder on the path is not a folder: %s" % path)


@contextlib.contextmanager
def pin_chain(anchor, path):
    """Hold every folder from `anchor` (included) down to the folder of `path` open, as itself and not through a link, until the with block ends (an exception
    included): between the check and the open nobody can swap one of them for a junction or symlink. `path` must be below `anchor` by spelling (os.path.abspath,
    never resolve: `..`, an 8.3 name or a name:stream stay what they are), else ValueError. A link on the way is UnsafeOpen. POSIX holds directory descriptors,
    and the caller must do every later step through `.dir_fd` (a descriptor does not stop a rename); Windows holds handles without FILE_SHARE_DELETE, which do.
    The anchor is given in the same spelling the path will be opened by (the resolved root where the scan resolved it). Never asks is_link/link_in_chain:
    those are the early checks, and a pin that leaned on them would vanish with them."""
    anchor_text, path_text = os.path.abspath(os.fspath(anchor)), os.path.abspath(os.fspath(path))
    parent = os.path.dirname(path_text)
    if not lexically_inside(parent, anchor_text):
        raise ValueError("%s is not below the anchor %s" % (path_text, anchor_text))
    relative = path_text[len(anchor_text):] if os.path.normcase(parent).startswith(os.path.normcase(anchor_text)) else ""
    names = [part for part in re.split(r"[\\/]+", os.path.dirname(relative)) if part]
    with contextlib.ExitStack() as stack:
        if os.name == "nt":
            current = anchor_text
            _pin_component_windows(current, stack)
            for name in names:
                current = os.path.join(current, name)
                _pin_component_windows(current, stack)
            yield _Pin(None)
        else:
            fd = _pin_component(anchor_text, None, stack)
            for name in names:
                fd = _pin_component(name, fd, stack)
            yield _Pin(fd)


class _PinnedFile:
    """A binary file object that also holds the pinned folder chain until it is closed (a `with` block, or `close()`); every other attribute is the file's."""

    def __init__(self, handle, stack):
        self._handle, self._stack = handle, stack

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __iter__(self):
        return iter(self._handle)

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def close(self) -> None:
        try:
            self._handle.close()
        finally:
            self._stack.close()


def _open_read_fd(path: str, dir_fd) -> int:
    """The descriptor of `path` opened for reading as itself: Windows through `_open_no_reparse`, POSIX with O_NOFOLLOW (by name under `dir_fd` when pinned)."""
    if os.name == "nt":
        return _open_no_reparse(path)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        return os.open(os.path.basename(path), flags, dir_fd=dir_fd) if dir_fd is not None else os.open(path, flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
            raise UnsafeOpen("source is a symlink: %s" % path) from exc
        raise


def _pin_for(path, anchor, stack) -> tuple:
    """(path, dir_fd) for an open under `anchor`: the chain from the anchor to the folder of `path` is pinned on `stack` and `path` is made absolute. A path that is
    not below `anchor` is pinned from its own folder. Without an anchor nothing is pinned: (path, None)."""
    if anchor is None:
        return path, None
    absolute = os.path.abspath(os.fspath(path))
    if not lexically_inside(os.path.dirname(absolute), anchor):
        anchor = os.path.dirname(absolute)
    return absolute, stack.enter_context(pin_chain(anchor, absolute)).dir_fd


def open_nofollow_read(path, expect_stat=None, single_link: bool = True, anchor=None):
    """Open `path` for binary reading without following a link; return the file object. POSIX: O_NOFOLLOW. Windows: `_open_no_reparse` (CreateFile
    that opens a reparse point as itself, then refuses it). Both: the handle must be a regular file, with `expect_stat` (the lstat taken when the file was
    checked) the same (st_dev, st_ino), and with `single_link` exactly one name. Any mismatch raises UnsafeOpen. With `anchor` the folders from the anchor down
    to the file are pinned first (pin_chain) and stay pinned until the returned file is closed; a path that is not below `anchor` is pinned from its own folder."""
    stack = contextlib.ExitStack()
    fd = None
    try:
        path, dir_fd = _pin_for(path, anchor, stack)
        fd = _open_read_fd(os.fspath(path), dir_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeOpen("source is not a regular file: %s" % path)
        if expect_stat is not None and (info.st_dev, info.st_ino) != (expect_stat.st_dev, expect_stat.st_ino):
            raise UnsafeOpen("source changed between check and copy: %s" % path)
        if single_link and info.st_nlink != 1:
            raise UnsafeOpen("source has %d names (hard link): %s" % (info.st_nlink, path))
        handle = os.fdopen(fd, "rb")
        fd = None
        return _PinnedFile(handle, stack) if anchor is not None else handle
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        stack.close()
        raise


def _create_new_fd(path: str, dir_fd) -> int:
    """The descriptor of a file made new at `path` for writing: Windows through `_open_no_reparse` (CREATE_NEW, the reparse point not followed), POSIX with
    O_CREAT|O_EXCL|O_NOFOLLOW (by name under `dir_fd` when pinned). A name that is there, a link included, is FileExistsError, and nothing is made at a link's target."""
    if os.name == "nt":
        return _open_no_reparse(path, write=True, create_new=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.open(os.path.basename(path), flags, 0o666, dir_fd=dir_fd) if dir_fd is not None else os.open(path, flags, 0o666)


def create_exclusive(path, anchor=None):
    """Create `path` for binary writing, failing (FileExistsError) when anything, a link included, is already there; never writes through a link, and never
    leaves an empty file at the target of a link that sits at the name (the create itself does not follow it: no check-then-create window). With `anchor` the
    folders from the anchor down to the file are pinned first and stay pinned until the returned file is closed."""
    stack = contextlib.ExitStack()
    fd = None
    try:
        path, dir_fd = _pin_for(path, anchor, stack)
        fd = _create_new_fd(os.fspath(path), dir_fd)
        opened = os.fstat(fd)
        named = os.lstat(os.path.basename(path), dir_fd=dir_fd) if dir_fd is not None else os.lstat(path)  # the handle must be the very file the name holds now
        if stat.S_ISLNK(named.st_mode) or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise UnsafeOpen("created file is not the named path (link raced in): %s" % path)
        handle = os.fdopen(fd, "wb")
        fd = None
        return _PinnedFile(handle, stack) if anchor is not None else handle
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        stack.close()
        raise


def _names_a_folder(info) -> bool:
    """True for a folder or a folder link by its lstat: a directory, or (Windows) the directory attribute, which a junction and a directory symlink carry."""
    return stat.S_ISDIR(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x10)


def _refuse_folder_target(target: Path, dir_fd) -> None:
    """UnsafeOpen when the name `target` is a folder or a folder link now (a file, a file link or nothing is fine: a rename replaces the name itself)."""
    try:
        info = os.lstat(target.name, dir_fd=dir_fd) if dir_fd is not None else os.lstat(target)
    except FileNotFoundError:
        return
    if _names_a_folder(info):
        raise UnsafeOpen("output is a folder or a folder link: %s" % target)


class _Staged:
    """A file written beside its target under a temp name, not yet in place: `commit()` renames it over the target, `discard()` removes it."""

    def __init__(self, target: Path, tmp: Path, anchor: Path):
        self.target, self.tmp, self.anchor = target, tmp, anchor

    def commit(self) -> None:
        with pin_chain(self.anchor, self.target) as pin:
            _refuse_folder_target(self.target, pin.dir_fd)
            if pin.dir_fd is not None:
                os.replace(self.tmp.name, self.target.name, src_dir_fd=pin.dir_fd, dst_dir_fd=pin.dir_fd)
            else:
                os.replace(self.tmp, self.target)

    def discard(self) -> None:
        """Remove the temp file; never raises. A folder on the way that is a link now is not entered (the temp stays, it holds only what this run wrote)."""
        try:
            with pin_chain(self.anchor, self.tmp) as pin:
                os.unlink(self.tmp.name, dir_fd=pin.dir_fd) if pin.dir_fd is not None else os.unlink(self.tmp)
        except (OSError, ValueError):
            pass


def stage_write(target, fill, anchor=None) -> _Staged:
    """Write a file next to `target` under a temp name (`.<name>.<8 hex>.spr05tmp`): `fill(handle)` writes its bytes, then it is flushed and fsynced. The target
    itself is not touched until `commit()`. The chain of folders from `anchor` (default `anchor_for(target)`) down to the target's folder is pinned for every step; a
    target that is a folder or a folder link is refused before anything is written. An error removes the temp file and is raised again."""
    target = Path(os.path.abspath(os.fspath(target)))
    anchor = Path(os.path.abspath(os.fspath(anchor))) if anchor is not None else anchor_for(target)
    if not lexically_inside(target.parent, anchor):
        anchor = target.parent
    tmp = target.with_name(".%s.%s%s" % (target.name, os.urandom(4).hex(), C.REPLACE_TMP_SUFFIX))
    with pin_chain(anchor, target) as pin:
        _refuse_folder_target(target, pin.dir_fd)
        fd = _create_new_fd(os.fspath(tmp), pin.dir_fd)
        try:
            with os.fdopen(fd, "wb") as handle:
                fill(handle)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                os.unlink(tmp.name, dir_fd=pin.dir_fd) if pin.dir_fd is not None else os.unlink(tmp)
            except OSError:
                pass
            raise
    return _Staged(target, tmp, anchor)


def replace_with(target, fill, anchor=None) -> None:
    """Replace `target` by what `fill(handle)` writes: staged beside it and renamed over it, so the old file stays as it was until the new one is complete."""
    staged = stage_write(target, fill, anchor)
    try:
        staged.commit()
    except BaseException:
        staged.discard()
        raise


def write_replace(target, data: bytes, anchor=None) -> None:
    """Replace `target` by `data` atomically: the bytes go to a temp file beside it (create_exclusive semantics, the chain from `anchor` pinned) and an os.replace puts
    it over the name, which replaces a link at the name instead of writing through it. A folder or folder link at the name is UnsafeOpen. Any error removes the temp file and
    leaves the old target as it was."""
    replace_with(target, lambda handle: handle.write(data), anchor)


def link_in_chain(path, stop):
    """The first link/junction among `path` and its parents up to and including `stop` (all of them when `stop` is not above `path`), else None."""
    current, stop = Path(path), Path(stop)
    while True:
        if is_link(current):
            return current
        if current == stop or current.parent == current:
            return None
        current = current.parent


def zone_named(name: str, markers=C.CLOUD_MARKERS) -> bool:
    """A single folder name that is a cloud/secret zone by itself (.secret, or one containing a marker such as OneDrive/SharePoint)."""
    low = name.casefold()
    return low == ".secret" or any(marker.casefold() in low for marker in markers)


def walk_files(base: Path, markers=C.CLOUD_MARKERS, max_files: int | None = None, max_depth: int | None = None, skip_names=()) -> tuple[list[Path], set, set, set, bool]:
    """(every file and folder under `base`, sorted; the links, the real folders and the cloud placeholders the listing itself reports; cut short).
    A symlink or junction (any reparse point) is listed as a link and never entered, a folder named like a cloud/secret zone and
    anything carrying cloud attributes are listed but never entered or opened, and nothing else is stat-ed per entry except folders about to be entered.
    The walk stops after `max_files` entries (default DOCTOR_MAX_FILES_PER_SKILL) and does not enter folders `max_depth` levels down
    (default DOCTOR_MAX_SKILL_DEPTH); either sets the last value, True. An entry whose name is in `skip_names` (letter case ignored) is left out unlisted and unentered."""
    max_files = C.DOCTOR_MAX_FILES_PER_SKILL if max_files is None else max_files
    max_depth = C.DOCTOR_MAX_SKILL_DEPTH if max_depth is None else max_depth
    found, links, dirs, cloud, stack, cut = [], set(), set(), set(), [(base, 0)], False
    skip_names = {name.casefold() for name in skip_names}  # Evals/ and TESTS/ are the same folder as evals/ and tests/ on Windows and macOS
    while stack and not cut:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as scan:
                entries = list(scan)
        except OSError:
            continue
        for entry in entries:
            if entry.name.casefold() in skip_names:
                continue
            if len(found) >= max_files:
                cut = True
                break
            path = Path(entry.path)
            found.append(path)
            try:
                if entry_is_cloud(entry):
                    cloud.add(path)
                    if entry.is_dir(follow_symlinks=False):
                        dirs.add(path)
                elif entry.is_symlink():
                    links.add(path)
                elif entry.is_dir(follow_symlinks=False):
                    if zone_named(entry.name, markers):  # decided from the name: no stat, even for a link
                        dirs.add(path)
                    elif is_link(path):
                        links.add(path)
                    else:
                        dirs.add(path)
                        if depth + 1 < max_depth:
                            stack.append((path, depth + 1))
                        else:
                            cut = True
            except OSError:
                continue
    return sorted(found), links, dirs, cloud, cut


def _remove_quietly(path) -> None:
    """Delete a file this run made; one that is read-only (copied mode) loses that bit first. Never raises."""
    for attempt in (0, 1):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt:
                return
            try:
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                return


def _is_dir_quiet(path: Path) -> bool:
    """True for a real folder. A link (symlink, junction), a cloud placeholder, a missing path and an OSError the stdlib does not swallow
    (ENAMETOOLONG on POSIX) are 'not a directory'; one lstat, so the target of a link is never stat-ed (SPR-02 FR7.1)."""
    try:  # is_link() is True for a path that cannot be probed (ENAMETOOLONG and similar): not a directory; any other OSError means the same
        if is_link(path) or path_is_cloud(path):
            return False
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False
