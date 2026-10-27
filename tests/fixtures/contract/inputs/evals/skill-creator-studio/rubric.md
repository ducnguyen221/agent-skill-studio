# Skill Creator Studio — Evaluation rubric

**Status:** cases, oracle (`expected/`) and rubric frozen for SPR-18 (see `runs/SPR-18/manifest.json`). Per DN2 (b) this skill is measured
for **activation only** in SPR-18; no A/B outcome comparison is run for it.

Kinds in `cases.json`: `typical` (2), `edge` (2), `input-error` (1), `near-miss` (3). Positive = every kind except `near-miss`.

## Activation (counted from the transcript by `evals/tools/activation.py`, never self-reported)

- **A1** — on a positive case, the Skill tool call for this skill, or a read of its `SKILL.md`, appears in the transcript.
- **A2** — on a `near-miss` case, neither appears.

Skill name in the system prompt or skill catalogue is not activation.

## Outcome criteria (A/B)

Same matching rule as `data-quality-audit` (`evals/tools/oracle.py`: `re.IGNORECASE | re.DOTALL`, every `must_contain` must match, no `must_not_contain` may match). Not scored in SPR-18 (activation-only skill); kept so a later sprint can compare.

- **O1** — NEW: created file has valid portable manifest, negative trigger scope and checkable quality gate; evals external to skill.
- **O2** — AUDIT: captures offending path and line; no content edits in audit mode; a missing target is reported as missing.
- **O3** — REFINE: identifies single canonical principle, proposes correction, plans regression rather than claiming success.
- **O4** — near-miss: the task is answered directly without creating, auditing or refining a skill.

`activation-only` (recorded, never compared): reading `skills/skill-creator-studio/SKILL.md` (`files_read_expected`).

## Scoring method

For each positive test, mark PASS only if the oracle entries are observable in generated files/transcript. Mark FAIL for incorrect trigger, unapproved
modifications or output claiming model tests ran without evidence.
