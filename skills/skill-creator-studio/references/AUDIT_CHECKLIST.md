# Audit Checklist — Findings before fixes

## Contents
- How to report
- Portable manifest & discovery
- Structure & resources
- Workflow quality & safety
- Evaluations & reliability
- Report template

## How to report

For every check mark PASS / FAIL / N/A with **file:line**, actual text/command or rationale. Static checker is the floor; manual audit covers judgment. Do not edit while in AUDIT mode.

## Portable manifest & discovery

- **SK-00:** YAML starts line 1, name regex/folder match, description <=1024 chars, portable fields only; no top-level `version`, `triggers` or Claude-only `hooks` in portable file.
- **SK-05:** description contains what+when in user words, third-person, narrow enough to not overlap library.
- Test one positive and one negative trigger on intended runtimes.

## Structure & resources

- **SK-01:** entrypoint is a router, not manual; body ~<500 lines; all essential references directly linked, no dead paths.
- **SK-02:** cutting questions per kept passage: would the agent go wrong without it? does it repeat another file (link instead of copy)? are conditions nested more than two levels?
- **SK-15:** Markdown reference >100 lines has `## Contents` at the top (`ST5`); body >100 lines should have one (`ST7`); what must always hold sits in the first 5 000 tokens.
- **SK-09:** scripts clearly `run`/`read`; packages, install/permissions documented; paths portable; assets not secrets or eval fixtures.
- Check orphan reference files, obsolete copies, duplicate guidance and stale links.

## Workflow quality & safety

- **SK-03:** each step has freedom appropriate to risk; side effects gated.
- **SK-06:** complex job has checkable `Done when` and fail->return path.
- **SK-07:** concrete validation and actionable errors, no premature completion.
- **SK-08:** strict/flexible templates, real input/output examples, clear fork where needed.
- **SK-10:** risky must-hold requirements implemented with host-compatible enforcement; test allow/deny cases.
- **SK-12:** governing principles at top for long sessions.
- **SK-13:** no request to expose private internal reasoning.
- **SK-14:** forcing words (`MUST`, `NEVER`, `ALWAYS`, `CRITICAL`) carry a reason or sit in a low-freedom block (`CT10`, WARN).

## Evaluations & reliability

- **SK-04:** test on model(s) actually used; compare overly prescriptive variants empirically.
- **SK-11:** at least 3 cases, negative trigger, no-skill baseline; no fake pass when agent eval not run.
- Check regression results, actual output artifacts, model versions and provenance.

## Report template

```text
Skill: <name> | Runtime: <target> | Date: <date>

Rule | Result | Location | Evidence | Proposed change | Risk
SK-00| FAIL   | SKILL.md:3 | name has uppercase | normalize & match folder | high
...

Most important fixes: (1)... (2)...
No files modified in AUDIT.
Needs approval: numbered edits.
```

**Rule provenance:** Consult `SOURCE_NOTES.md` and external `standards/SOURCE_TRACEABILITY.md` when available. The full RoboNuggets 46-rule mapping lives in repo standards and is not required for every small Skill.
