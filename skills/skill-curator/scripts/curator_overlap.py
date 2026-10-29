"""Pairs of skills that may overlap, and the one label each pair gets: `catalog --overlap` (SPR-04 TK11, FR4).

Internal module of `skill-curator` (imported by `curator_catalog`); do not run it. It uses the engine modules `studio_*` that its loader has already put in
`sys.modules`. Read-only and only a suggestion: every pair is `needs_review`, no label says "delete" and nothing here opens a file's content (a skill's
`references/` and `scripts/` are listed by name only, through the same link, cloud and secret checks as every other walk).

An *item* is a dict: `key` ("<plugin>:<skill>" for a source skill, "<harness>/<plugin>:<skill>" for an installed copy), `plugin`, `skill` (the folder name),
`name` (the frontmatter `name:`), `desc`, `path` (the real folder), `harness` (None for a source) and, when the caller has it, `sha` (the tree hash, None
when the tree cannot be hashed whole).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import studio_const as C
import studio_fs as fs

NOMINATE = 0.20       # a pair of different names is put forward when the descriptions are at least this alike (spike: 20 pairs in 124 skills)
SAME_FUNCTION = 0.30  # ... and it is `same_function` only from here AND with at least two file names in common (never on text alone, FR4.2)
MIN_SHARED_FILES = 2
OVERLAP_MAX_PAIRS = 20000  # nominated pairs per run: a library whose descriptions fall into two word groups would otherwise give a quadratic list (RF-S2)
SUGGESTION = {"distribution_copy": "keep", "version_drift": "sync", "same_function": "merge", "same_name_other_role": "keep", "insufficient_evidence": "keep"}
NOT_NAMES = ("readme.md", "__init__.py")
# Fixed list (EN and VI). Words under four characters never reach it: the word test drops them first.
STOPWORDS = frozenset("""
about above after also another because been before being between both can could does doing each either else even every from have having here
into just like make many more most much must need only other over same should some such than that their them then there these they this those through
thus under until upon used uses using very want were what when where whether which while will with within without would your

những được trong không cùng khi để của các cho với này đó khác nhiều mỗi tất cả hoặc nhưng nếu rồi sau trước thì là
""".split())
_WORD = re.compile(r"[a-zà-ỹ0-9]+")
_NOT_CLAUSE = re.compile(r"(?<!\w)(?:not|không)(?!\w)[^.!?]*", re.IGNORECASE)  # from «Not»/«Không» to the end of the sentence


def words(text: str) -> set:
    """The set of words of a description: lower case, `[a-zà-ỹ0-9]+`, at least four characters, not a stop word."""
    return {w for w in _WORD.findall(text.lower()) if len(w) >= 4 and w not in STOPWORDS}


def doc_freq(descriptions: list) -> tuple:
    """(df, n): in how many of the `n` descriptions each word occurs."""
    df: dict = {}
    for text in descriptions:
        for w in words(text):
            df[w] = df.get(w, 0) + 1
    return df, len(descriptions)


def _weights(text: str, df: dict, n: int) -> dict:
    return {w: (math.log(n / max(df.get(w, 1), 1)) if n > 0 else 0.0) for w in words(text)}


def _cosine(wa: dict, wb: dict) -> float:
    na, nb = math.sqrt(sum(v * v for v in wa.values())), math.sqrt(sum(v * v for v in wb.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    small, large = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return max(0.0, min(1.0, sum(v * large[w] for w, v in small.items() if w in large) / (na * nb)))


def similarity(a, b, df: dict, n: int) -> float:
    """Cosine of the TF-IDF vectors of two descriptions (strings, or items that carry `desc`) over the set of their words; the weight of a word is
    log(n / df): a word every skill has weighs nothing."""
    a = a["desc"] if isinstance(a, dict) else a
    b = b["desc"] if isinstance(b, dict) else b
    return _cosine(_weights(a, df, n), _weights(b, df, n))


def file_names(skill: Path, markers: tuple = C.CLOUD_MARKERS) -> set:
    """The file names (not paths, lower case) under `references/` and `scripts/` of a skill folder, without README.md, __init__.py and compiled files. Only
    names are read: a skill folder or a subfolder that is a link, a cloud placeholder or in a zone is not entered, and a skill under such a path gives {}."""
    skill = Path(skill)
    if fs.zone_reason(skill, markers) or fs.is_link(skill) or fs.path_is_cloud(skill):
        return set()
    names: set = set()
    for sub in ("references", "scripts"):
        folder = skill / sub
        if fs.zone_reason(folder, markers) or fs.is_link(folder) or fs.path_is_cloud(folder) or not fs._is_dir_quiet(folder):
            continue
        found, links, dirs, cloud, _ = fs.walk_files(folder, markers, skip_names=("__pycache__",))
        for path in found:
            low = path.name.casefold()
            if path in dirs or path in links or path in cloud or low in NOT_NAMES or low.endswith(".pyc"):
                continue
            names.add(low)
    return names


def _excludes(item: dict, other: dict) -> str | None:
    """The «Not …/Không …» sentence of `item`'s description that names `other` (its folder or its `name:`, any case), else None."""
    wanted = [x for x in {other["skill"], other["name"]} if x]
    for clause in _NOT_CLAUSE.finditer(item["desc"]):
        text = clause.group(0)
        for name in wanted:
            if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(name), text, re.IGNORECASE):
                return " ".join(text.split())
    return None


HARNESS_ORDER = {"claude": 0, "codex": 1, "antigravity": 2}


def _representatives(items: list) -> list:
    """Indexes into `items`, one per (plugin, skill): the source copy when there is one, else the first installed copy in a fixed order (harness, key, path)."""
    best: dict = {}
    for i, it in enumerate(items):
        rank = (0, 0, "", "") if it["harness"] is None else (1, HARNESS_ORDER.get(it["harness"], len(HARNESS_ORDER)), it["key"], it["path"])
        slot = (it["plugin"], it["skill"])
        if slot not in best or rank < best[slot][0]:
            best[slot] = (rank, i)
    return sorted(i for _, i in best.values())


class _Full(Exception):
    """The nominated pairs reached OVERLAP_MAX_PAIRS."""


def candidates(rows: list, installed: list, cut: list | None = None) -> list:
    """Every pair worth a label, as (a, b) items, each once: the same (plugin, skill) between a source and its installed copies or between two copies; the same
    `name:` in two plugins (one representative per (plugin, skill), so a skill that is only installed is compared too and the copies of one skill are not
    paired with the copies of the other); and two source skills of different names whose descriptions are alike (cosine >= NOMINATE). `rows` are the source items.
    At most OVERLAP_MAX_PAIRS pairs are put forward; when that stops the search `True` is appended to `cut` (when a list is given)."""
    items = list(rows) + list(installed)
    seen: set = set()
    out: list = []

    def add(i: int, j: int) -> None:
        if i != j and (min(i, j), max(i, j)) not in seen:
            if len(out) >= OVERLAP_MAX_PAIRS:
                raise _Full
            seen.add((min(i, j), max(i, j)))
            first, second = sorted((items[i], items[j]), key=lambda x: (x["harness"] is not None, x["key"], x["path"]))
            out.append((first, second))

    try:
        by_key: dict = {}
        for i, it in enumerate(items):
            by_key.setdefault((it["plugin"], it["skill"]), []).append(i)
        for group in by_key.values():
            for x in range(len(group)):
                for y in range(x + 1, len(group)):
                    add(group[x], group[y])
        by_name: dict = {}
        for i in _representatives(items):
            by_name.setdefault(items[i]["name"].casefold(), []).append(i)
        for group in by_name.values():
            for x in range(len(group)):
                for y in range(x + 1, len(group)):
                    if items[group[x]]["plugin"] != items[group[y]]["plugin"]:
                        add(group[x], group[y])
        df, n = doc_freq([r["desc"] for r in rows])
        vectors = [_weights(r["desc"], df, n) for r in rows]
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if rows[i]["name"].casefold() != rows[j]["name"].casefold() and _cosine(vectors[i], vectors[j]) >= NOMINATE:
                    add(i, j)
    except _Full:
        if cut is not None:
            cut.append(True)
    return out


def _cat():
    import curator_catalog  # late: curator_catalog imports this module, and the one comparison of `match` lives there (FR3.2)
    return curator_catalog


def _sha(item: dict, markers: tuple, cache=None):
    if "sha" in item:
        return item["sha"]
    anchor = item.get("anchor")  # the scan root the item was found under: its folder chain is pinned while the tree is read
    return cache.sha(Path(item["path"]), anchor) if cache is not None else _cat().roots_mod.tree_sha256(Path(item["path"]), markers, anchor)


def _short(sha) -> str:
    return sha[:12] if sha else "-"


def _pair(a: dict, b: dict, label: str, evidence: list) -> dict:
    if a["harness"] is not None or b["harness"] is not None:  # two copies of one skill: say where each sits
        cat = _cat()
        evidence = evidence + ["đường: a=%s; b=%s" % (cat.home_path(a["path"]), cat.home_path(b["path"]))]
    return {"a": a["key"], "b": b["key"], "label": label, "evidence": evidence, "suggestion": SUGGESTION[label], "needs_review": True}


def classify(a: dict, b: dict, df: dict, n: int, markers: tuple = C.CLOUD_MARKERS, names: dict | None = None, cache=None) -> dict:
    """The Pair for two items: the first row of the decision table that fits (SPEC FR4.1), always `needs_review`. `df`, `n` come from `doc_freq` over the
    source descriptions; `names` is an optional cache {path: file_names}, `cache` an optional curator_catalog.TreeCache."""
    if (a["plugin"], a["skill"]) == (b["plugin"], b["skill"]):
        head = "cùng (plugin, skill): %s:%s" % (a["plugin"], a["skill"])
        sha_a, sha_b = _sha(a, markers, cache), _sha(b, markers, cache)
        if sha_a is None or sha_b is None:  # a tree that cannot be hashed whole is neither equal nor different
            return _pair(a, b, "insufficient_evidence", [head, "không băm được cả cây: chưa biết hai bản có cùng nội dung không"])
        same, how = _cat().same_content(a, b, markers, cache)
        hashes = "tree_sha256 a=%s b=%s" % (_short(sha_a), _short(sha_b))
        if same:
            return _pair(a, b, "distribution_copy", [head, "compare: %s" % how, hashes])
        return _pair(a, b, "version_drift", [head, "compare: none", hashes])
    same_name = a["name"].casefold() == b["name"].casefold() and a["plugin"] != b["plugin"]
    for first, second, tag in ((a, b, "a"), (b, a, "b")):
        said = _excludes(first, second)
        if said:
            note = "mô tả của %s loại trừ bên kia: «%s»" % (tag, _cat().short_description(said, 120))
            if same_name:
                return _pair(a, b, "same_name_other_role", ["cùng name: %s" % a["name"], note])
            return _pair(a, b, "insufficient_evidence", [note])
    sim = similarity(a, b, df, n)
    cosine = "cosine mô tả %.2f" % sim
    shared: list = []
    if sim >= SAME_FUNCTION:
        cache = names if names is not None else {}
        for item in (a, b):
            if item["path"] not in cache:
                cache[item["path"]] = file_names(Path(item["path"]), markers)
        shared = sorted(cache[a["path"]] & cache[b["path"]])
        if len(shared) >= MIN_SHARED_FILES:
            return _pair(a, b, "same_function", [cosine, "tên file trùng (%d): %s" % (len(shared), ", ".join(shared))])
    files = "tên file trùng: %d (cần ≥ %d)" % (len(shared), MIN_SHARED_FILES)
    if same_name:
        return _pair(a, b, "same_name_other_role", ["cùng name: %s; plugin %s ≠ %s" % (a["name"], a["plugin"], b["plugin"]), cosine] + ([files] if sim >= SAME_FUNCTION else []))
    note = "khác tên; chỉ giống chữ: chưa đủ bằng chứng cấu trúc" if sim >= NOMINATE else "khác tên, mô tả dưới ngưỡng đề cử"
    return _pair(a, b, "insufficient_evidence", [cosine, files, note] if sim >= SAME_FUNCTION else [cosine, note])


def find_pairs(rows: list, installed: list, markers: tuple = C.CLOUD_MARKERS, cache=None, notes: list | None = None, truncated: list | None = None) -> list:
    """The labelled pairs of a library: `candidates`, each through `classify`, sorted by (a, b, label) so that two runs give the same list. When the search
    stopped at OVERLAP_MAX_PAIRS one line saying so is appended to `notes` (a list, when given), and `True` to `truncated` (likewise)."""
    df, n = doc_freq([r["desc"] for r in rows])
    names: dict = {}
    cache = cache if cache is not None else _cat().TreeCache(markers)
    cut: list = []
    nominated = candidates(rows, installed, cut)
    if cut and truncated is not None:
        truncated.append(True)
    if cut and notes is not None:
        notes.append("pairs: the search stopped at %d nominated pairs (limit); the list is not complete" % OVERLAP_MAX_PAIRS)
    pairs = [classify(a, b, df, n, markers, names, cache) for a, b in nominated]
    return sorted(pairs, key=lambda p: (p["a"], p["b"], p["label"]))
