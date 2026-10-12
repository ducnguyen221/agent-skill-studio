# Skill Creator Studio — Evaluation rubric

**Status:** schema ready, **model sessions not run**.

## Hard acceptance

- NEW: created file has valid portable manifest, negative trigger scope and checkable quality gate; evals external to skill.
- AUDIT: captures offending path and line; no content edits in audit mode.
- REFINE: identifies single canonical principle, proposes correction, plans regression rather than claiming success.
- Negative case: does not invoke Skill Creator for a generic Python sorting request.

## Scoring method

For each positive test, mark PASS only if all hard acceptance conditions are observable in actual generated files/transcript. Mark FAIL for incorrect trigger, unapproved modifications or output claiming model tests ran without evidence. Compare baseline no-skill against Skill-enabled runs.
