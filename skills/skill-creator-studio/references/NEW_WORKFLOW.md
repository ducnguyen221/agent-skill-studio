# NEW Workflow — Design a skill with tests first

## 1. Need and scope

Before creating a folder, obtain a concrete repeated job, users' words, expected output and a negative case. Define one primary activity and a few synonyms; avoid trying to claim everything related to "analysis" or "code".

## 2. Baseline and evaluations

Write at least three real prompts **before** extensive instruction writing. Test no-skill responses in fresh sessions when runtime is available. If the runtime is unavailable, create `evals/<skill-name>/cases.json` with `status: draft`, record baseline `not_run`, and be explicit.

Each test identifies trigger expectation, file inputs, observed outputs and hard acceptance criteria. Include one unrelated prompt that should not invoke this Skill, one typical happy path and one edge case.

## 3. Choose shape and degree of freedom

- **Single file** for short workflow, few dependencies.
- **Bundle** for references, scripts, assets used conditionally.
- **Router** when work branches into independently detailed jobs; prefer separate Skills if they have distinct triggers and ownership.

High freedom for varied writing, medium for templates and standard practices, low for destructive or deterministic operations. Permission control lives in the runtime, not prose alone.

## 4. Write portable manifest

Six Agent Skills fields are recognized: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`; the first two are required. Place version under `metadata`, not top-level. `description`: first state job, then "Use when ..." with real trigger vocabulary.

## 5. Write the main workflow

Critical rules → purpose → when/when not → numbered steps with done-when and if-fail return → resource routing → acceptance. Keep references linked directly; make reference >100 lines start with Contents. `SKILL.md` should ideally be under 500 body lines.

## 6. Add resources only when warranted

- Domain knowledge -> `references/`.
- Deterministic repeatable operations -> `scripts/` with usage, inputs, errors and dependencies.
- Templates/data/images/config -> `assets/`.
- Test prompts/fixtures/baselines -> **repo external** `evals/<name>/`.

## 7. Verify and ship

Run static validation, semantic review, model A/B test and packaging. If `STUDIO-DRAFT` remains or evals still empty, release is blocked. Review permissions for high-risk scripts. Never invent a pass status.
