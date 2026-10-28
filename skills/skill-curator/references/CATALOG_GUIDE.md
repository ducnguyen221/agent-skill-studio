# Catalog guide — read the catalog

> **Conclusion:** the catalog has one row per source skill, one state per scan root and a count of `doctor` findings; trust the rows only as far as the roots are `ok`.

## When to use / not

- Use when you need to read `CATALOG.md` or the JSON of `catalog`, or explain an exit code.
- Not for fixing a skill the catalog flags (use `skill-creator-studio`).

## Steps

1. Read the summary line: skills, repos, roots not ok, pairs to look at.
2. Read `Gốc không ok` first: a root that is `partial` or `error` hides skills from every count above it.
3. Scan the table of each repo and open the skills whose `Lỗi` is not `0 / 0`.
4. Treat every pair in `Cặp trùng` as a question for a person, never as an instruction to merge or delete.

## Columns

| Column | Meaning |
|---|---|
| Skill | the `name` of the skill (folder name when the manifest cannot be read) |
| Việc | description, one line, at most 160 characters |
| Bản | version in the plugin manifest of the repo |
| Claude, Codex, Antigravity | installed copy: `khớp` same tree hash, or the same after folding what an adapter rewrites (the JSON `compare` says `byte` or `semantic`), `khác (version)` different, `—` none, or the harness was not asked for with `--installed` |
| Lỗi | `doctor` ERROR / WARN count for the skill |
| Đã đo | `model_evaluated` from the repo's `evals/catalog.json`; `—` when the repo has none |

The JSON adds the tree hash (SHA-256 over every file of the skill, bytes as they are, `.git` left out) and the `metadata.opcos_*` keys (values cut to 160 characters; a list or mapping value is left out with a NOTE on stderr).

## Root states

- `ok`: everything the rules ask for was read. Folders left out **by rule** (`vendor-*`, an install with no manifest of the harness and no `skills/` (`no-manifest`), worktrees, `.agents/skills` copies, fixtures) are listed in `skipped_by_rule` and do not change the state.
- `partial`: something was not read that no rule excuses: a cloud placeholder, a link, a secret zone, a manifest pointing outside its plugin, a size limit.
- `error`: the root cannot be used at all (missing, too broad, a link, in a zone).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | every root is `ok` |
| 1 | at least one root is `partial` or `error` |
| 2 | nothing was scanned (no usable root, no skill found) or a flag cannot be used |

## Gotchas

- The output file may not sit inside a scanned root, a skill, a harness folder or a secret zone; point it at a scratch folder.
- A `Chỉ có bản cài` entry is an installed copy with no source in the scanned roots, usually a third-party plugin.
- `semantic` folds quoted frontmatter values, CRLF vs LF in text files and `.gitkeep`; a file an adapter dropped or added (a Dockerfile, a `.tsx`, a nested skill split flat) still makes the copy `khác`.
- For Antigravity the locator also reads `config/plugins/<plugin>/plugin.json`, only for the version (size-capped, refused behind a link, zone or cloud placeholder).

## Done when

You can say how many skills exist, which roots were not fully read and why, and which skills `doctor` flags, without having changed a file.
