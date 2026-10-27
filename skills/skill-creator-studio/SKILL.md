---
name: skill-creator-studio
description: "Creates, audits, refines and packages reusable Agent Skills using portable authoring rules and evidence-based quality checks. Use when asked to build a new SKILL.md, review an existing skill library, fix a failing skill, or prepare skill releases for Claude Code, Codex or Google Antigravity."
metadata:
  version: "0.1.0"
  author: "Agent Skill Studio"
---

# Skill Creator Studio

Creates or improves Agent Skills with evidence, independent checks and no silent edits. This Skill is a **factory workflow**, not a license to bypass approvals or host policies.

## Critical rules for every run

1. **Report before changing in AUDIT.** Produce findings with file/line/rule/severity and suggested edits; do not modify any existing Skill unless the user requests specified changes. A direct request to create a new Skill or fix a named issue authorizes that scope only.
2. **Portable by default.** Use only Agent Skills spec frontmatter for shared Skill artifacts. Explain runtime-specific features in separate adapter files, not in a cross-agent YAML header.
3. **Minimum effective guidance.** State why a rule exists. Apply one rule in one canonical location; don't append duplicate and stale layers.
4. **Risk determines freedom.** For expensive, destructive or external actions, require approvals and deterministic runtime gates. Natural-language rules are not enforcement; use runtime gates for anything that must always hold.
5. **Evals outside runtime.** Keep tests, oracle/expected behaviors and baseline logs under `evals/<name>/` when in a Studio repo. Exclude them when packaging Skill.
6. **No invented test results.** Static checks are not model A/B tests. The absence of model execution must be recorded as `not_run`.
7. **Review real outputs.** Do not request hidden internal reasoning; request conclusions, verifiable assumptions, evidence and concise rationale.

## Gotchas

- Claude Code-only frontmatter keys such as `when_to_use` or `hooks` fail `FM4` unless you run `validate --target claude-code`.
- `package` refuses a `SKILL.md` that still has the `STUDIO-DRAFT` HTML comment marker; delete it once the body is real (`package` does not check evals).
- `fmt --fix` copies every file it changes to `<file>.bak-<ISO>`; in a git repo pass `--no-backup`, and delete stray `*.bak-*` before `package`.

## Pick mode

| Mode | Trigger | Output |
|---|---|---|
| **NEW** | New repeated job without a dedicated Skill | Scope, tests/baseline plan, new Skill folder, runnable checks |
| **AUDIT** | Check/score/review existing SKILL or library | Static report + semantic review; **no edits** |
| **REFINE** | Existing Skill fails or new evidence arrives | Proposed targeted changes; apply approved changes, regression checks |

Commands below run from this Skill's folder as `python3 scripts/studio.py <command>` (commands: `new`, `check`, `validate`, `audit`, `evals`, `package`, `install`, `doctor`, `fmt`; Python 3.9+, standard library only; `--help` lists exact parameters), or `studio.py` at a Studio repo root. It is never an automatic agent action: run it only where you have permission. In any mode, when a claim about a rule or its source needs checking, read [references/SOURCE_NOTES.md](references/SOURCE_NOTES.md). Internal engine modules (imported by `studio.py`, do not run directly): `scripts/studio_const.py`, `scripts/studio_dist.py`, `scripts/studio_doctor.py`, `scripts/studio_evals.py`, `scripts/studio_fmt.py`, `scripts/studio_fs.py`, `scripts/studio_lint.py`, `scripts/studio_scaffold.py`, `scripts/studio_validate.py`.

## NEW — create a Skill

1. Define one job, positive trigger, negative trigger, input/output and side effects. Done when scope and success criteria can be explained in two sentences.
2. Read [references/NEW_WORKFLOW.md](references/NEW_WORKFLOW.md) before drafting, for shape, manifest, resources and the eval-first workflow. Write >=3 realistic test scenarios plus no-skill baseline plan **before extensive instructions**.
3. Run `python3 scripts/studio.py new <name> --description "<what>. Use when <trigger>." --output <target>`. The default scaffold is the minimal template: one `SKILL.md` with `## Gotchas`. Add `--lang vi` for a Vietnamese body (frontmatter stays English), or `--full` for the full template with `references/`, `scripts/`, `assets/` and `agents/` (it follows `--lang`, so `--full --lang vi` gives the full template with a Vietnamese body). `new` always takes the scaffold from `assets/skill-template*/` of this Skill, inside or outside the Studio repo. Done when scaffold exists, `evals/<name>` is separate and name/description match.
4. Replace scaffold draft wording, add necessary refs/assets/scripts. Never ship an unedited `STUDIO-DRAFT` template or marker as a finished Skill.
5. Validate with `python3 scripts/studio.py validate <path> --require-evals` in a Studio repo, then `evals` static check; run model tests separately using external evals runbook. If validation fails, return to step 4.
6. Document actual runtime coverage and package after passing relevant release gates.

## AUDIT — assess without editing

1. Run static validator: `python3 scripts/studio.py audit <skill-folder>` or `audit --all` inside a Studio repo. For Claude Code-only frontmatter keys see Gotchas. For a library spread over many skill folders, run `doctor --roots "<dir1>;<dir2>"` (report-only scan). All of these list findings without changing files.
2. Read [references/AUDIT_CHECKLIST.md](references/AUDIT_CHECKLIST.md) before the manual review, or for a release check: it maps the 15 rules `SK-01`…`SK-15` (plus the `SK-00` manifest gate) to observable checks. Inspect `SKILL.md`, each linked reference, scripts and assets. Done when syntax and semantic risks have evidence, not only impressions.
3. Read [references/SOURCE_NOTES.md](references/SOURCE_NOTES.md) only when a finding needs a source: which requirement is official and which is community advice.
4. Write report: `Path:line | Rule | Severity | Evidence | Proposed fix | Risk`. Separate auto-checks and manual checks; prioritize high-impact issues.
5. Stop before modifications; ask which numbered fixes to apply, unless current request explicitly names them.

## REFINE — change based on evidence

1. Record what failed in actual use: prompt, model/runtime, expected vs observed. Read [references/REFINE_WORKFLOW.md](references/REFINE_WORKFLOW.md) before changing or deleting any rule: it covers evidence capture, A/B trimming and approval scope.
2. Identify the smallest rule/principle causing the miss. Propose diff and affected test cases before changing high-impact Skill behavior.
3. Apply only approved or directly requested edits; remove superseded rule in same pass. Prefer shorter instructions if tests show it is safe.
4. Rerun static validator and targeted eval. If a check fails, return to step 3. For safety-critical edits, verify a fresh-session allow and deny case.
5. Report change list, files touched, checks actually run, missing model evaluation and rollback path.

## Definition of Done

One well-scoped Skill exists (NEW) or an evidence-based report exists (AUDIT) or the approved problem is corrected with regression checks (REFINE). Actual verification is reported, untested models are identified and no unapproved files have been changed.
