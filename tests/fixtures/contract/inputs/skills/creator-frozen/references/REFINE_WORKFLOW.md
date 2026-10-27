# REFINE Workflow — Test before deleting

## 1. Capture failure evidence

Record prompt, environment/model, expected vs observed behavior, files actually accessed, scripts executed, output/QA result. Identify why existing instruction did not work; test whether the issue is activation, missing reference, execution or output quality.

## 2. Identify principle, not patch pile

A new exception can often be expressed as a clearer existing rule. Edit the canonical location and remove superseded duplicate. If file grows substantially, ask whether details belong in a reference or a separate Skill with distinct trigger.

## 3. Before simplifying older instructions

Copy version A (current) and B (trimmed). Run identical cases with fresh sessions and the intended model; keep deletion only if B performs no worse on important scenarios. Restoring a line is cheaper than an unseen production regression.

## 4. Permission-sensitive change

For actions with side effects, propose exact diff, user approval scope, rollback plan and allow+deny tests. Do not silently edit hooks/permissions while optimizing wording.

## 5. Verification

Run `validate` -> `evals` schema -> actual agent tasks; inspect generated files if any. A new error means return to step 2/3. No final "success" claim without a traceable check.

## 6. Release note

Version, files touched, why, tests run, tests not run, any new dependency, trigger changes and rollback instructions.
