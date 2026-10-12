# Data Quality Audit — Evaluation rubric

**Status:** model runs not executed.

## Criteria

1. Skill triggered on CSV data-validation requests only, not DAX-only explanatory requests.
2. CSV input and key grain identified; missing key assumption surfaced.
3. Validation script executed read-only when runtime permits; exact issues and data rows reported.
4. For clean fixture, checked constraints passed; for duplicate/invalid fixtures, issues surfaced correctly.
5. No source rewrite or unsolicited network request.

A PASS requires observable output and input check details; static manifest validation alone is insufficient.
