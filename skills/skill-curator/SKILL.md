---
name: skill-curator
description: "Inventories, checks and de-duplicates a whole Agent Skills library across repos and installed harness copies. Use when asked which skills exist, where they are installed, which are broken, over budget or duplicated, or to prepare a catalog for review. Not for writing or fixing one skill (use skill-creator-studio)."
metadata:
  version: "0.1.0"
  author: "Agent Skill Studio"
---

# Skill Curator

Shows the whole skill library at once: which source skills exist, in which repo, what `doctor` finds in each, and (as later commands arrive) where they are installed and which ones overlap. It only reads. It writes the two report files you name and nothing else, and it never edits, installs or deletes a skill.

## Critical rules for every run

1. **Read-only.** Run `catalog` and `doctor` to look; never change a skill because a report says so. A fix is a separate request, and one skill at a time belongs to `skill-creator-studio`.
2. **Reports go outside the library.** `--out` and `--md` are refused inside a scanned root, a skill, a harness folder (`~/.claude`, `~/.codex`, `~/.gemini`) or a secret zone; an existing file is replaced only when it is already a catalog.
3. **A report is a lead, not a verdict.** A root marked `partial` or `error` means something was not read; say what, never present the list as complete.
4. **Never open cloud placeholders or secrets.** The scan skips them and says so; do not work around it by copying files out.

## Gotchas

- Exit code 1 from `catalog` means a root is `partial` or `error`, not that the command failed; read the `Gốc không ok` section before trusting the counts.
- `catalog --roots-from opcos` needs a `paths.json` (found from `$OPCOS_ROOT`, else up from the working folder); outside an OpcOS tree pass `--roots` instead.
- `--installed` and `--overlap` are accepted but not available yet: every harness shows `—` and `pairs` stays null.
- Paths under the home folder are written `~/…`, so a shared `CATALOG.md` does not carry a user name.

## Commands

Run from this skill's folder as `python3 scripts/curator.py <command>`, or as `studio.py catalog` from a Studio repo root (Python 3.9+, standard library only; `--help` lists exact flags). `scripts/curator.py` is the entry point: it finds the shared engine modules, then runs `catalog` (code in `scripts/curator_catalog.py`) or hands `doctor` to the engine. `scripts/curator_catalog.py` is imported by `curator.py` and `studio.py`; do not run it directly.

| Command | Use | Output |
|---|---|---|
| `catalog` | one row per source skill: name, short description, repo, version, tree hash, `doctor` errors and warnings, `model_evaluated`, `metadata.opcos_*` keys | table on screen, JSON with `--out`, `CATALOG.md` with `--md` |
| `doctor` | the engine's report-only scan of many roots (same flags as `studio.py doctor`) | findings per skill |

## Steps

1. Pick the roots: `--roots-from opcos` for an OpcOS tree, or `--roots "<dir1>;<dir2>"` for plain skill folders.
2. Run `python3 scripts/curator.py catalog --roots-from opcos --out <folder>/catalog.json --md <folder>/CATALOG.md` with a folder outside the library. Done when exit is 0 or the exit-1 roots are named.
3. Open `CATALOG.md`; read [references/CATALOG_GUIDE.md](references/CATALOG_GUIDE.md) for the columns, the root states and the exit codes.
4. Report what you found: counts, roots not ok with their reasons, skills with `doctor` errors. Ask before acting on any of it.

## Definition of Done

A catalog exists (screen, JSON or `CATALOG.md`) or the exit code explains why not, every root that is not `ok` is named with its reason, and no skill file was changed.
