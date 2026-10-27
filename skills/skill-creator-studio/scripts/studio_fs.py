"""File-system helpers of the Agent Skill Studio engine: finding, reading, creating and walking files without following links
or touching cloud placeholders, plus frontmatter parsing and finding records (SPR-02 TK4a).

Internal module of `studio.py`; do not run it. It reaches the constants through `studio_const` as an object (FR4.5).
"""

from __future__ import annotations

import ast
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


def skill_dirs(root: Path) -> list[Path]:
    """The folders under `root/skills` that hold a SKILL.md. A link (symlink, junction), a cloud placeholder and a `skills` folder that is
    itself a link are neither listed nor entered, and nothing is stat-ed through a link (SPR-02 FR7.1: the pattern of walk_files)."""
    base = root / "skills"
    if is_link(base) or path_is_cloud(base):
        return []
    try:
        with os.scandir(base) as scan:
            entries = list(scan)
    except OSError:
        return []
    found = []
    for entry in entries:
        path = Path(entry.path)
        try:
            if entry.is_symlink() or entry_is_cloud(entry) or not entry.is_dir(follow_symlinks=False) or is_link(path):
                continue
        except OSError:
            continue
        if (path / "SKILL.md").exists():
            found.append(path)
    return sorted(found)


def is_link(path: Path) -> bool:
    """True for a symlink or, on Windows, any reparse point such as a directory junction (os.path.isjunction needs Python 3.12)."""
    if path.is_symlink():
        return True
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False


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


def input_file_problem(source: Path, markers=C.CLOUD_MARKERS) -> str | None:
    """Why an input file (--roots-file, --baseline) may not be read, else None. Decided before opening it: not an NTFS data stream
    (name:stream), not a secret-looking name, not a cloud placeholder, and neither the spelling given nor the real path (a link, an 8.3
    name such as SECRET~1) in a cloud or secret zone."""
    text = os.fspath(source)
    if os.name == "nt" and ":" in os.path.splitdrive(text)[1]:
        return "names an NTFS data stream; not read"
    if secret_file_name(source.name):
        return "has a secret-looking file name; not read"
    reason = zone_reason(source, markers)
    if not reason:
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


def read_capped(path, limit: int | None) -> tuple:
    """(text, too_big). With a limit the file is read in binary up to limit+1 bytes and never further; newlines are folded as read_text does."""
    if limit is None:
        return Path(path).read_text(encoding="utf-8"), False
    with open(path, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
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


def open_nofollow_read(path, expect_stat=None, single_link: bool = True):
    """Open `path` for binary reading without following a link; return the file object. POSIX: O_NOFOLLOW. Windows (no O_NOFOLLOW): open, then compare
    (st_dev, st_ino) of the open handle with `expect_stat` (the lstat taken when the file was checked). Both: the handle must be a regular file and,
    with `single_link`, have exactly one name. Any mismatch raises UnsafeOpen. Windows residue: the open itself already follows a reparse point
    before the comparison (see README, "Rủi ro còn lại")."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
            raise UnsafeOpen("source is a symlink: %s" % path) from exc
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeOpen("source is not a regular file: %s" % path)
        if expect_stat is not None and (info.st_dev, info.st_ino) != (expect_stat.st_dev, expect_stat.st_ino):
            raise UnsafeOpen("source changed between check and copy: %s" % path)
        if single_link and info.st_nlink != 1:
            raise UnsafeOpen("source has %d names (hard link): %s" % (info.st_nlink, path))
        return os.fdopen(fd, "rb")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def create_exclusive(path):
    """Create `path` for binary writing, failing (FileExistsError) when anything, a link included, is already there; never writes through a link."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if os.path.lexists(path):  # Windows has no O_NOFOLLOW and CREATE_NEW follows a dangling symlink: a name that is there at all, a link included, is refused first
        raise FileExistsError(errno.EEXIST, "already exists (a link counts)", os.fspath(path))
    fd = os.open(path, flags, 0o666)
    try:
        opened, named = os.fstat(fd), os.lstat(path)  # the handle must be the very file the name holds now, not a link's target
        if stat.S_ISLNK(named.st_mode) or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise UnsafeOpen("created file is not the named path (link raced in): %s" % path)
        return os.fdopen(fd, "wb")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


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
    try:  # is_link() asks pathlib first, which re-raises ENAMETOOLONG and similar: every OSError means 'not a directory'
        if is_link(path) or path_is_cloud(path):
            return False
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False
