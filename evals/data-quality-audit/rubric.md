# Data Quality Audit — Evaluation rubric

**Status:** cases, oracle (`expected/`) and rubric frozen for SPR-18 (see `runs/SPR-18/manifest.json`); model runs recorded under `runs/SPR-18/`.

Kinds in `cases.json`: `typical` (2), `edge` (2), `input-error` (1), `near-miss` (3). Positive = every kind except `near-miss`.

## Activation (counted from the transcript by `evals/tools/activation.py`, never self-reported)

- **A1** — on a positive case, the Skill tool call for this skill, or a read of its `SKILL.md`, appears in the transcript.
- **A2** — on a `near-miss` case, neither appears.

A1/A2 are reported in their own columns and never enter the better/equal/worse tally.
Skill name in the system prompt or skill catalogue is not activation.

## Outcome criteria (A/B)

Judged only from the output text and the oracle `expected/<case-id>.json`. Matching rule, fixed in `evals/tools/oracle.py` (run
`python evals/tools/oracle.py grade expected/<case-id>.json output.txt`; exit 0 = oracle satisfied): each entry is a regular expression searched with
`re.IGNORECASE | re.DOTALL` (so `.` crosses newlines; entries bound it with `.{0,N}`); every `must_contain` entry must match, no `must_not_contain` entry may match.
Row numbers are accepted in both conventions (file row with the header as row 1, as the script prints, and data row as plain prose usually counts),
so a correct baseline answer is not scored lower for its numbering. `tests/test_oracle.py` runs the real script and a baseline-style answer through every positive oracle.
Only these criteria count toward better / equal / worse.

- **O1** — every `must_contain` entry of the oracle is satisfied (the exact row, column or count the fixture produces).
- **O2** — no `must_not_contain` entry is matched (no claim that the data is clean beyond the checked constraints).
- **O3** — the input file is not modified or rewritten (observable from the transcript / output: no write to the fixture).
- **O4** — the output names which constraints were checked (required columns, key columns, numeric columns) or states the assumption it made.

`activation-only` (recorded, never compared): validation script executed (`files_read_expected`, `scripts` field of the activation counter).

## Hard fail

Claims the data is clean when the oracle lists an issue; invents an issue the fixture does not contain; rewrites the source file; unsolicited network request.

A PASS requires observable output and input check details; static manifest validation alone is insufficient.
