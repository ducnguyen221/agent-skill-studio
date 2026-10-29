# Skill Curator — Evaluation rubric

**Status:** draft for SPR-04 (TK9). Cases and oracle (`expected/`) are written, no model session has been run: `model_evaluated` stays `false` in `evals/catalog.json`.

Kinds in `cases.json`: `typical` (2), `edge` (2), `input-error` (1), `near-miss` (3). Positive = every kind except `near-miss`.

## Activation (counted from the transcript by `evals/tools/activation.py`, never self-reported)

- **A1** — on a positive case, the Skill tool call for this skill, or a read of its `SKILL.md`, appears in the transcript.
- **A2** — on a `near-miss` case, neither appears. The two creator-shaped near-misses (a new skill, a fix to one skill) belong to `skill-creator-studio`.

Skill name in the system prompt or skill catalogue is not activation.

## Outcome criteria

Same matching rule as the other suites (`evals/tools/oracle.py`: `re.IGNORECASE | re.DOTALL`, every `must_contain` must match, no `must_not_contain` may match). Not scored yet.

- **O1** — catalog: the answer comes from `catalog` output (rows, root states, exit code), not from hand-listing folders.
- **O2** — partial roots: every root that is not `ok` is named with its reason; the list is not called complete.
- **O3** — read-only: no skill, installed copy or harness folder is edited, merged or deleted.
- **O4** — missing input: a folder that does not exist is reported as such, with no invented skills.
- **O5** — near-miss: the task is answered directly without a library inventory.

`activation-only` (recorded, never compared): reading `skills/skill-curator/SKILL.md` (`files_read_expected`).

## Scoring method

For each positive test, mark PASS only if the oracle entries are observable in generated files or transcript. Mark FAIL for a wrong trigger, an edit the user did not ask for, or an answer that claims model tests ran without evidence.
