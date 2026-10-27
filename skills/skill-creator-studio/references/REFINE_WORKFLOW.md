# REFINE Workflow — Test before deleting

> **Conclusion:** to change a Skill that failed in use, capture the failure as evidence, find the principle behind it instead of piling on patches, test any trimming against the current version, and verify with a traceable check before reporting success.

## When to use / not

- Use when the REFINE mode applies: an existing Skill fails or new evidence arrives.
- Not for creating a Skill (use [NEW_WORKFLOW.md](NEW_WORKFLOW.md)) and not for a read-only review (use the AUDIT checklist).

## Steps

### Step 1 — Capture failure evidence

Record prompt, environment/model, expected vs observed behavior, files actually accessed, scripts executed, output/QA result. Identify why existing instruction did not work; test whether the issue is activation, missing reference, execution or output quality.

- Command: write down the prompt, the environment and model, expected versus observed behavior, files accessed, scripts run and the QA result.
- Expect: the failure is classified as activation, missing reference, execution or output quality, with the reason the existing instruction did not work.
- Stop if: the failure cannot be reproduced or described; do not edit the Skill yet.

### Step 2 — Identify principle, not patch pile

A new exception can often be expressed as a clearer existing rule. Edit the canonical location and remove superseded duplicate. If file grows substantially, ask whether details belong in a reference or a separate Skill with distinct trigger.

- Command: find the smallest existing rule that caused the miss and edit it at its canonical location, removing any superseded duplicate.
- Expect: one clearer rule replaces the exception; the file does not grow substantially.
- Stop if: the file would grow substantially; decide whether the detail belongs in a reference or a separate Skill with a distinct trigger.

### Step 3 — Simplify older instructions only after a test

Copy version A (current) and B (trimmed). Run identical cases with fresh sessions and the intended model; keep deletion only if B performs no worse on important scenarios. Restoring a line is cheaper than an unseen production regression.

- Command: keep a copy of version A, make version B, and run the same cases on both in fresh sessions with the intended model.
- Expect: B performs no worse than A on the important scenarios; only then is the deletion kept.
- Stop if: B is worse on any important scenario; restore the line.

### Step 4 — Handle a permission-sensitive change

For actions with side effects, propose exact diff, user approval scope, rollback plan and allow+deny tests. Do not silently edit hooks/permissions while optimizing wording.

- Command: propose the exact diff with the approval scope, the rollback plan and the allow and deny tests, and wait for approval.
- Expect: the user approves a stated scope before any hook or permission text changes.
- Stop if: a wording change would alter a hook or permission without that approval.

### Step 5 — Verify

Run `validate` -> `evals` schema -> actual agent tasks; inspect generated files if any. A new error means return to step 2/3. No final "success" claim without a traceable check.

- Command: `python3 scripts/studio.py validate <path>`, then `python3 scripts/studio.py evals --all --eval-root <evals folder>` (inside the Studio repository `--eval-root` may be left out), then the actual agent tasks; inspect any generated files.
- Expect: validation and the evals schema check exit 0, and the agent tasks give the expected result.
- Stop if: a new error appears; return to Step 2 or Step 3. Claim no success without a traceable check.

### Step 6 — Write the release note

Version, files touched, why, tests run, tests not run, any new dependency, trigger changes and rollback instructions.

- Command: write the release note with version, files touched, why, tests run, tests not run, any new dependency, trigger changes and rollback instructions.
- Expect: a reader can tell what changed, what was checked, what was not, and how to roll back.
- Stop if: a test was not run and the note does not say so; add it to "tests not run".

## Gotchas

- A failure is not always in the instructions: activation, a missing reference, execution and output quality each need a different fix, so classify before editing.
- Trimming is a change like any other: without the A/B run of Step 3, a deleted line can cause a regression nobody sees.

## Done when

- The failure evidence is recorded and the fix sits at the canonical location, with no superseded duplicate left.
- Static validation and the targeted evals pass, and a safety-critical edit has a fresh-session allow case and deny case.
- The release note lists tests run and tests not run, with the rollback path.
