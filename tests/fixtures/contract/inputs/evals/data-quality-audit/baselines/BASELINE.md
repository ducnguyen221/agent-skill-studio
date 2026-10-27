# No-Skill Baseline — SPR-18 (2026-10-17)

Fresh-session runs, one session per case, pinned model, same prompt and fixtures as the with-skill run of the same case. Prompts are the verbatim `cases.json` prompts.
The A/B comparison itself (blind grading against `expected/`) is a separate step; this file only records what was run and where the logs are.

| Runtime | Model | Baseline cases (positive only) | Status | Logs |
|---|---|---|---|---|
| Claude Code | `claude-sonnet-5-5` | 5 of 5 (`csv-clean`, `csv-duplicate`, `csv-invalid-numeric`, `data-quality-audit-edge-2`, `data-quality-audit-input-error`) | ran | `runs/SPR-18/*_claude-code_*_base.json`, outputs in `runs/SPR-18/out/` |
| Codex | `gpt-6-luna` | 5 of 5 (same five cases) | ran (batch 18/10/2026, second pass; the 17/10 attempt was blocked and its smoke `smoke/codex_base.json` stays as contamination evidence) | `runs/SPR-18/2026-10-18T02-*_codex_*_base.json`, outputs in `runs/SPR-18/out/` |
| Antigravity | — | 0 of 5 | **NOT RUN** — out of scope for SPR-18 (headless bridge has no transcript and no isolated skill root; see `harness-status.json`). | — |

## How the Claude Code "no skill" condition was produced and checked

- Plugin switched off for the process only: `--settings '{"enabledPlugins":{"agent-skill-studio@agent-skill-studio":false}}'`. Machine settings were not changed.
- Absence proof taken at the start of the batch (`runs/SPR-18/smoke/claude-code_base_batch.json`): asked to list skills whose name contains `data-quality` or `skill-creator`; the catalogue of the session holds 0 mentions of `agent-skill-studio`, `data-quality-audit`, `skill-creator-studio` (filtered transcript), and the answer lists only unrelated `skill-creator` skills.
- Every baseline run: `triggered: false`, no `SKILL.md` read, no skill script run (counted by `evals/tools/activation.py`).
## How the Codex "no skill" condition was produced and checked (18/10/2026)

- Codex has no per-process plugin switch, so the machine-wide plugin was switched off for one batch window with the official writer `codex-config.ps1 -Set 'plugins."agent-skill-studio@agent-skill-studio".enabled=false'` and switched back on (`=true`) in a `finally` block. Precondition: no interactive Codex session (only background daemons). After the window the config file hash equalled the hash before the window and the line read `enabled = true`.
- Absence proof taken at the start of the window (`runs/SPR-18/smoke/codex_base_clean.json`): asked for skills whose name contains `data-quality` or `skill-creator`; the session catalogue holds no `agent-skill-studio:*` skill. The answer lists `data-analytics:analyze-data-quality`, `skill-creator`, `anthropic-skills:skill-creator`, which are unrelated skills that only match the substring.
- Every Codex baseline run: clean directory containing only `fixtures/` (no `.agents/skills`), `triggered: false`, no `SKILL.md` read, no skill script run (`evals/tools/activation.py`, full and filtered transcripts agree), `actual_model` = `gpt-6-luna` from the bridge ledger.
- The Claude-Code-only notes above about `preamble` apply here too: the machine's global instructions load in Codex.

- Both conditions run in a clean directory outside this repository; user-level global instructions of the machine still load (field `preamble` in each log).
