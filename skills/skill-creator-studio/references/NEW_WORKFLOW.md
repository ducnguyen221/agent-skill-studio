# NEW Workflow — Design a skill with tests first

> **Conclusion:** to create a Skill, fix the need and scope first, write at least three test prompts before extensive instructions, then choose the shape, write the manifest and the workflow, add resources only when warranted, and verify before shipping.

## When to use / not

- Use when the NEW mode applies: a repeated job has no dedicated Skill yet.
- Not for reviewing an existing Skill (use the AUDIT checklist) and not for fixing one that failed in use (use [REFINE_WORKFLOW.md](REFINE_WORKFLOW.md)).

## Steps

### Step 1 — Define need and scope

Before creating a folder, obtain a concrete repeated job, users' words, expected output and a negative case. Define one primary activity and a few synonyms; avoid trying to claim everything related to "analysis" or "code".

- Command: ask the user for the job, their own words, the expected output and one negative case.
- Expect: one primary activity with a few synonyms, a concrete input and output, and a negative case, all written down.
- Stop if: no concrete repeated job can be named; create no folder.

### Step 2 — Write baseline and evaluations

Write at least three real prompts **before** extensive instruction writing. Test no-skill responses in fresh sessions when runtime is available. If the runtime is unavailable, create `evals/<skill-name>/cases.json` with `status: draft`, record baseline `not_run`, and be explicit.

Each test identifies trigger expectation, file inputs, observed outputs and hard acceptance criteria. Include one unrelated prompt that should not invoke this Skill, one typical happy path and one edge case.

- Command: write `evals/<skill-name>/cases.json` with at least three prompts, then run each prompt without the Skill in a fresh session.
- Expect: every case states trigger expectation, inputs, observed outputs and acceptance criteria; one case is unrelated, one typical, one an edge case. With no runtime, the file has `status: draft` and baseline `not_run`.
- Stop if: fewer than three real prompts exist; do not draft instructions yet.

### Step 3 — Choose shape and degree of freedom

- **Single file** for short workflow, few dependencies.
- **Bundle** for references, scripts, assets used conditionally.
- **Router** when work branches into independently detailed jobs; prefer separate Skills if they have distinct triggers and ownership.

High freedom for varied writing, medium for templates and standard practices, low for destructive or deterministic operations. Permission control lives in the runtime, not prose alone.

`studio.py new` scaffolds the minimal template by default: one `SKILL.md` with a `## Gotchas` section, enough for a single file. `--lang {en,vi}` picks the language of the body (default `en`; the frontmatter stays English). `--full` scaffolds the full template (`references/`, `scripts/`, `assets/`, `agents/`) for a bundle and also follows `--lang`: `--full --lang vi` writes the Vietnamese `SKILL.md` and leaves no `SKILL.vi.md` in the new Skill. `--output` sets the parent folder and `--eval-root` the external evals folder.

- Command: `python3 scripts/studio.py new <name> --description "<what>. Use when <trigger>." --output <target>`, adding `--lang vi` and `--full` as the shape needs.
- Expect: the scaffold exists, `evals/<name>` is separate from it, and name and description match.
- Stop if: the work splits into jobs with distinct triggers and owners; make separate Skills instead of a router.

### Step 4 — Write portable manifest

Six Agent Skills fields are recognized: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`; the first two are required. Place version under `metadata`, not top-level. `description`: first state job, then "Use when ..." with real trigger vocabulary.

- Command: edit the frontmatter of the new `SKILL.md`, then run `python3 scripts/studio.py validate <path>`.
- Expect: no frontmatter finding; the description names the job first and then "Use when ..." with real trigger words.
- Stop if: a field outside the six is needed; move it to a runtime-specific adapter instead of the portable header.

### Step 5 — Write the main workflow

Critical rules → purpose → when/when not → numbered steps with done-when and if-fail return → resource routing → acceptance. Keep references linked directly; make reference >100 lines start with Contents. `SKILL.md` should ideally be under 500 body lines.

- Command: write the body of `SKILL.md` in that order, linking each reference directly from it.
- Expect: every step has a done-when and an if-fail return; each reference over 100 lines starts with Contents; the body is ideally under 500 lines.
- Stop if: the body grows past the limit; move detail into a reference or a separate Skill.

### Step 6 — Add resources only when warranted

- Domain knowledge -> `references/`.
- Deterministic repeatable operations -> `scripts/` with usage, inputs, errors and dependencies.
- Templates/data/images/config -> `assets/`.
- Test prompts/fixtures/baselines -> **repo external** `evals/<name>/`.

- Command: add a file only for a need from the list above, and link it from `SKILL.md`.
- Expect: each script documents usage, inputs, errors and dependencies; no eval fixture or baseline sits inside the Skill folder.
- Stop if: a resource has no step that needs it; leave it out.

### Step 7 — Verify and ship

Run static validation, semantic review, model A/B test and packaging. If `STUDIO-DRAFT` remains or evals still empty, release is blocked. Review permissions for high-risk scripts. Never invent a pass status.

- Command: `python3 scripts/studio.py validate <path> --require-evals`, then `python3 scripts/studio.py evals --all`, then the model A/B test from the external evals runbook, then `python3 scripts/studio.py package <path>`.
- Expect: validation and the evals check exit 0, the A/B result is recorded with its evidence, and the package is built.
- Stop if: `STUDIO-DRAFT` remains, the evals are still empty, or a high-risk script has not been reviewed for permissions; return to Step 5.

## Gotchas

- A fresh scaffold still carries the `STUDIO-DRAFT` marker and three draft eval cases; `package` refuses the Skill until the marker is deleted, and the cases need real prompts before release.
- `SKILL.vi.md` is only the source of the Vietnamese body: `new` writes it as `SKILL.md` and never copies it into the new Skill.
- Static checks are not model tests: without a runtime, record the model evaluation as `not_run`.

## Done when

- The Skill folder and the separate `evals/<name>` folder exist with matching name and description.
- `validate --require-evals` and the evals check exit 0, and no `STUDIO-DRAFT` remains.
- Every claim of model testing has real evidence; anything not run is recorded as `not_run`.
